import copy

from test_input_safety import enforcing, request
from test_runtime import Engine, start

from jev_router.config import Config
from jev_router.decisions import CompletionDecision, RiskDecision
from jev_router.hooks import Router


def test_safe_defaults():
    config = Config()
    assert config.mode == "shadow"
    assert not config.shaping_enabled
    assert not config.verify_enabled
    assert config.risk_enabled


def test_shadow_computes_but_cannot_change_behavior():
    e = Engine()
    e.risk = RiskDecision(0.99, 0.99, 0.99, 0.99, 0.99, 0.99)
    e.completion = CompletionDecision(0.99, 0.01, 0.99, 0.99)
    r = enforcing(e, mode="shadow")
    start(r)
    payload = request()
    original = copy.deepcopy(payload)
    ids = dict(session_id="s", turn_id="t")
    assert r.llm_request(request=payload, api_call_count=1, **ids) is None
    assert payload == original
    args = {"command": "delete something"}
    r.tool_request(tool_name="terminal", args=args, tool_call_id="c", **ids)
    assert r.pre_tool_call(tool_name="terminal", args=args, tool_call_id="c", **ids) is None
    assert not r.prepared.items
    assert r.pre_verify(changed_paths=["a.py"], final_response="done", **ids) is None
    assert (e.turn_calls, e.risk_calls, e.verify_calls) == (1, 1, 1)
    events = r.telemetry.snapshot()["recent"]
    assert any(x.get("would_shape") and not x.get("shaped") for x in events)
    assert any(x.get("would_approve") and not x.get("approval") for x in events)
    assert any(x.get("would_nudge") and not x.get("nudge") for x in events)


def test_disabled_has_no_decisions_or_effects():
    e = Engine()
    r = Router(Config(enabled=False), e)
    start(r)
    assert r.llm_request(request=request(), session_id="s", turn_id="t", api_call_count=1) is None
    assert not e.states
