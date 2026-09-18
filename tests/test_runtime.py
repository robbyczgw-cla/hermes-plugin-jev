import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from jev_router.config import Config
from jev_router.decisions import CompletionDecision, RiskDecision, TurnDecision
from jev_router.hooks import Router
from jev_router.middleware import shape_tools
from jev_router.privacy import Sanitizer


def chat(**kw):
    return replace(TurnDecision("chat", "trivial", 0.01, 0.01, 0.01, 0.01, 0.01, "low", 0.99), **kw)


class Engine:
    def __init__(self):
        self.turn_calls = self.risk_calls = self.verify_calls = 0
        self.states = []
        self.turn = chat()
        self.risk = RiskDecision(0.99, 0.01, 0.01, 0.01, 0.01, 0.01)
        self.completion = CompletionDecision(0.99, 0.99, 0.01, 0.01)
        self.error = False
        self.delay = 0

    def _record(self, state):
        self.states.append(state)
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise ValueError("SECRET_EXCEPTION_MUST_NOT_LEAK")

    def classify_turn(self, state):
        self.turn_calls += 1
        self._record(state)
        return self.turn

    def assess_tool_risk(self, state):
        self.risk_calls += 1
        self._record(state)
        return self.risk

    def assess_completion(self, state):
        self.verify_calls += 1
        self._record(state)
        return self.completion


def setup(engine=None, **config):
    engine = engine or Engine()
    r = Router(Config(**config), engine=engine, approval_order_safe=lambda: True)
    return r, engine


def start(r, s="s", t="t", text="hello"):
    return r.pre_llm_call(session_id=s, turn_id=t, user_message=text, platform="test", model="test")


def tools():
    return {
        "model": "test",
        "messages": [],
        "tools": [
            {"type": "function", "function": {"name": n, "parameters": {"type": "object"}}}
            for n in ("terminal", "read_file", "web_search", "clarify", "todo", "mystery_tool")
        ],
    }


def test_once_per_turn_and_sessions():
    r, e = setup()
    start(r)
    start(r)
    r.llm_request(request=tools(), session_id="s", turn_id="t", api_call_count=1)
    assert e.turn_calls == 1
    start(r, t="t2")
    start(r, s="other")
    assert e.turn_calls == 3
    assert r.cache.get("s", "t").decision == e.turn


def test_concurrent_singleflight():
    r, e = setup()
    e.delay = 0.03
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: start(r), range(8)))
    assert e.turn_calls == 1


def test_failure_cached_and_private(caplog):
    r, e = setup()
    e.error = True
    start(r)
    start(r)
    assert e.turn_calls == 1
    assert r.llm_request(request=tools(), session_id="s", turn_id="t") is None
    assert "SECRET_EXCEPTION" not in caplog.text


def test_timeout_is_bounded_and_cache_failed():
    r, e = setup(timeout_seconds=0.04)
    e.delay = 0.2
    before = time.monotonic()
    start(r)
    start(r)
    assert time.monotonic() - before < 0.15
    assert e.turn_calls == 1
    assert r.cache.get("s", "t").decision is None


def test_eviction_and_cleanup():
    r, e = setup(cache_size=2)
    start(r, t="1")
    start(r, t="2")
    start(r, t="3")
    assert len(r.cache) == 2
    r.on_session_end(session_id="s")
    assert len(r.cache) == 0


def test_missing_ids_no_cross_session_guess():
    r, e = setup()
    r.pre_llm_call(user_message="hello")
    assert e.turn_calls == 0
    assert r.llm_request(request=tools()) is None


def test_shaping_pure_conservative():
    original = tools()
    before = copy.deepcopy(original)
    shaped = shape_tools(original, chat(), 0.95)
    assert shaped and len(shaped["tools"]) < len(original["tools"])
    names = [x["function"]["name"] for x in shaped["tools"]]
    assert {"clarify", "todo", "mystery_tool"} <= set(names)
    assert original == before


@pytest.mark.parametrize(
    "d",
    [
        chat(confidence=0.9),
        chat(intent="coding"),
        chat(needs_terminal=0.2),
        chat(should_delegate=0.3),
    ],
)
def test_not_certain_chat_preserves(d):
    assert shape_tools(tools(), d, 0.95) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"tools": [{"strange": 1}]},
        {"tools": "bad"},
        {"tools": [{"type": "web_search_preview"}]},
        dict(tools(), tool_choice="required"),
        dict(tools(), tool_choice={"type": "function", "function": {"name": "terminal"}}),
    ],
)
def test_unknown_or_required_payload_untouched(payload):
    before = copy.deepcopy(payload)
    assert shape_tools(payload, chat(), 0.95) is None
    assert payload == before


def test_shaping_stops_after_tool_or_followup_request():
    r, e = setup()
    start(r)
    assert r.llm_request(request=tools(), session_id="s", turn_id="t", api_call_count=1)
    assert r.llm_request(request=tools(), session_id="s", turn_id="t", api_call_count=2) is None
    r.post_tool_call(session_id="s", turn_id="t", tool_name="read_file", args={}, result={})
    assert r.llm_request(request=tools(), session_id="s", turn_id="t", api_call_count=1) is None


def test_read_bypass_and_low_risk():
    r, e = setup()
    start(r)
    assert (
        r.pre_tool_call(tool_name="read_file", args={"path": "a"}, session_id="s", turn_id="t")
        is None
    )
    assert e.risk_calls == 0
    assert (
        r.pre_tool_call(tool_name="terminal", args={"command": "pwd"}, session_id="s", turn_id="t")
        is None
    )
    assert e.risk_calls == 1


def test_high_risk_and_uncertainty_request_approval():
    r, e = setup()
    start(r)
    e.risk = RiskDecision(0.99, 0.99, 0.99, 0.99, 0.01, 0.99)
    assert (
        r.pre_tool_call(
            tool_name="terminal", args={"command": "delete data"}, session_id="s", turn_id="t"
        )["action"]
        == "approve"
    )
    e.risk = RiskDecision(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
    assert (
        r.pre_tool_call(tool_name="terminal", args={}, session_id="s", turn_id="t")["action"]
        == "approve"
    )


def test_risk_failure_no_directive_and_later_guard_preserved():
    r, e = setup()
    start(r)
    e.error = True
    assert r.pre_tool_call(tool_name="terminal", args={}, session_id="s", turn_id="t") is None
    e.error = False
    e.risk = RiskDecision(0.1, 1, 1, 1, 1, 1)
    r.approval_order_safe = lambda: False
    assert r.pre_tool_call(tool_name="terminal", args={}, session_id="s", turn_id="t") is None


def test_action_dependent_memory_not_allowlisted():
    r, e = setup()
    start(r)
    r.pre_tool_call(tool_name="memory", args={"action": "remove"}, session_id="s", turn_id="t")
    assert e.risk_calls == 1


def test_verify_no_changes_and_success():
    r, e = setup()
    start(r, text="Implement a feature")
    assert r.pre_verify(session_id="s", coding=True, changed_paths=[], attempt=0) is None
    assert e.verify_calls == 0
    r.post_tool_call(
        session_id="s",
        turn_id="t",
        tool_name="terminal",
        args={"command": "pytest"},
        result=json.dumps({"exit_code": 0, "output": "10 passed"}),
    )
    assert (
        r.pre_verify(
            session_id="s",
            coding=True,
            changed_paths=["a.py"],
            attempt=0,
            final_response="Done, tests passed",
        )
        is None
    )
    assert e.verify_calls == 1


def test_verify_incomplete_bounded_and_evidence_invalidated():
    r, e = setup()
    start(r, text="Implement feature")
    e.completion = CompletionDecision(0.99, 0.01, 0.99, 0.99)
    kw = dict(session_id="s", coding=True, changed_paths=["a.py"], final_response="Done", attempt=0)
    assert r.pre_verify(**kw)["action"] == "continue"
    assert r.pre_verify(**kw) is None
    assert r.pre_verify(**dict(kw, attempt=3)) is None
    r.post_tool_call(
        session_id="s",
        turn_id="t",
        tool_name="terminal",
        args={"command": "pytest"},
        result={"exit_code": 0, "output": "passed"},
    )
    r.post_tool_call(
        session_id="s",
        turn_id="t",
        tool_name="write_file",
        args={"path": "a.py"},
        result={"success": True},
    )
    assert not r.cache.get("s", "t").evidence


def test_ambiguous_session_verify_noop():
    r, e = setup()
    start(r)
    start(r, t="other")
    assert r.pre_verify(session_id="s", coding=True, changed_paths=["a.py"], attempt=0) is None
    assert e.verify_calls == 0


def test_privacy_nested_text_unicode_and_never_log(monkeypatch, caplog):
    secret = "apikey_TEST_SECRET_VALUE_12345"
    monkeypatch.setenv("TYPESAFE_API_KEY", secret)
    s = Sanitizer(max_bytes=1500)
    data = s.clean(
        {
            "api_key": secret,
            "nested": {"Authorization": "Bearer abc", "password": "pw"},
            "text": f"hey {secret} https://a.test/?token=TOPSECRET",
            "long": "漢" * 10000,
        }
    )
    out = json.dumps(data, ensure_ascii=False)
    assert secret not in out and "TOPSECRET" not in out and "Bearer abc" not in out
    assert len(out.encode()) <= 1500
    r, e = setup()
    start(r, text=secret)
    r.pre_tool_call(
        tool_name="terminal",
        args={"command": f'curl -H "Authorization: Bearer {secret}"', "token": secret},
        session_id="s",
        turn_id="t",
    )
    assert secret not in json.dumps(e.states)
    assert secret not in caplog.text


def test_disabled_no_calls():
    r, e = setup(enabled=False)
    start(r)
    assert e.turn_calls == 0
