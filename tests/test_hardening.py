"""Failure, capacity, schema and privacy regressions."""

import copy
import json

import pytest
from test_runtime import chat, risk_call, setup, start, tools

from jev_router import register
from jev_router.cache import TurnCache
from jev_router.middleware import shape_tools
from jev_router.privacy import Sanitizer
from jev_router.telemetry import Telemetry


def test_capacity_does_not_evict_active_turn_or_reclassify():
    r, e = setup(cache_size=1)
    start(r)
    start(r, t="other")
    start(r)
    assert e.turn_calls == 1
    r.post_llm_call(session_id="s", turn_id="t")
    start(r, t="other")
    assert e.turn_calls == 2
    assert len(r.cache) == 1


def test_cache_ttl_and_session_isolation(monkeypatch):
    import jev_router.cache as cache

    now = [0.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: now[0])
    c = TurnCache(3, 10)
    first, _ = c.reserve("one", "t", {})
    c.reserve("two", "t", {})
    assert c.get("one", "t") is first
    c.end("two")
    assert c.get("one", "t") is first
    assert c.get("two", "t") is None
    now[0] = 11
    assert len(c) == 0


def test_overlapping_turns_abstain_from_session_only_verify():
    r, e = setup()
    start(r, t="a")
    start(r, t="b")
    assert (
        r.pre_verify(session_id="s", changed_paths=["a.py"], coding=True, final_response="Done")
        is None
    )
    assert e.verify_calls == 0
    r.post_llm_call(session_id="s", turn_id="a")
    r.pre_verify(session_id="s", changed_paths=["a.py"], coding=True, final_response="Done")
    assert e.verify_calls == 1


def test_missing_turn_id_gets_local_identity_not_cross_session():
    r, e = setup()
    r.pre_llm_call(session_id="s", user_message="hello")
    assert e.turn_calls == 1 and r.cache.get("s") is not None
    assert r.cache.get("different") is None
    r.post_llm_call(session_id="s")
    r.pre_llm_call(session_id="s", user_message="different request")
    assert e.turn_calls == 2
    assert r.cache.get("s").state["user_message"] == "different request"


@pytest.mark.parametrize(
    "result", [{}, {"exit_code": None}, {"exit_code": True}, {"session_id": "background"}]
)
def test_no_explicit_integer_exit_is_not_verified(result):
    r, e = setup()
    start(r)
    r.post_tool_call(
        session_id="s", turn_id="t", tool_name="terminal", args={"command": "pytest"}, result=result
    )
    assert not any(x["success"] is True for x in r.cache.get("s", "t").evidence)


def test_compound_test_command_cannot_fake_success():
    r, e = setup()
    start(r)
    r.post_tool_call(
        session_id="s",
        turn_id="t",
        tool_name="terminal",
        args={"command": "pytest; true"},
        result={"exit_code": 0},
    )
    assert not r.cache.get("s", "t").evidence


def test_responses_schema_and_mixed_unknown_schema():
    payload = {
        "tools": [{"type": "function", "name": n, "parameters": {}} for n in ["terminal", "todo"]]
    }
    before = copy.deepcopy(payload)
    assert len(shape_tools(payload, chat())["tools"]) == 1
    assert payload == before
    payload["tools"][1] = {"type": "function", "function": {"name": "todo", "parameters": {}}}
    assert shape_tools(payload, chat()) is None


@pytest.mark.parametrize("probability", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_bad_probabilities_do_not_shape(probability):
    assert shape_tools(tools(), chat(confidence=probability)) is None


def test_bounded_unicode_state_and_secret_redaction():
    sanitizer = Sanitizer(512)
    state = sanitizer.clean(
        {
            "text": "日" * 10000,
            "api_key": "fake-only",
            "headers": {"Authorization": "Bearer fake-secret"},
        }
    )
    assert len(json.dumps(state, ensure_ascii=False).encode()) <= 512
    assert "fake-only" not in json.dumps(state)
    assert "fake-secret" not in json.dumps(state)


def test_bounded_telemetry_drops_unknown_payload_fields():
    t = Telemetry(size=2)
    for _ in range(10):
        t.record("turn", latency_ms=1, state="PRIVATE", arguments="PRIVATE")
    snap = t.snapshot()
    assert len(snap["recent"]) == 2 and snap["counts"]["turn"] == 10
    assert "PRIVATE" not in json.dumps(snap)


class Context:
    def __init__(self, settings=None):
        self.settings = settings or {}
        self.hooks = {}
        self.middleware = {}
        self.commands = {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_middleware(self, name, fn):
        self.middleware[name] = fn

    def register_cli_command(self, name, help, setup, handler):
        self.commands[name] = handler


def test_missing_key_noop_and_status(monkeypatch, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    ctx = Context()
    runtime = register(ctx)
    assert not runtime.active
    assert runtime.pre_llm_call(session_id="s", turn_id="t", user_message="hello") is None
    ctx.commands["jev"](None)
    status = json.loads(capsys.readouterr().out)
    assert status["api_key_configured"] is False


@pytest.mark.parametrize(
    "settings",
    [
        {"enabled": "true"},
        {"tool_shaping.min_confidence": 0.5},
        {"cache.max_turns": float("inf")},
        {"max_workers": 2.5},
    ],
)
def test_invalid_settings_disable_plugin(monkeypatch, settings):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert not register(Context(settings)).config.enabled


def test_classifier_disabled_still_assesses_risk():
    r, e = setup(classifier_enabled=False)
    start(r)
    assert e.turn_calls == 0
    risk_call(r, session_id="s", turn_id="t", tool_name="terminal", args={"command": "pwd"})
    assert e.risk_calls == 1


def test_sdk_does_not_disable_other_sdk_users_logs(monkeypatch, caplog):
    import logging

    from test_sdk import engine_and_wire

    engine, _, _ = engine_and_wire(monkeypatch)
    engine.assess_tool_risk({"task": "test"})
    with caplog.at_level(logging.WARNING, logger="typesafe_sdk"):
        logging.getLogger("typesafe_sdk").warning("ordinary unrelated SDK log")
    assert "ordinary unrelated SDK log" in caplog.text
