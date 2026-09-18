"""Regressions for the independent review's P0/P1 findings."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_runtime import setup, start

from jev_router.decisions import CompletionDecision, RiskDecision


def risky():
    r, e = setup()
    r.approval_available = lambda: True
    start(r)
    e.risk = RiskDecision(0.99, 0.99, 0.99, 0.99, 0.01, 0.99)
    return r, e


def call(**overrides):
    return dict(
        session_id="s",
        turn_id="t",
        tool_call_id="call-1",
        tool_name="terminal",
        args={"command": "remove build output"},
        **overrides,
    )


def prepare(r, **kw):
    # Before the fix there is no middleware; the assertions still exercise the bug.
    middleware = getattr(r, "tool_request", lambda **kwargs: None)
    assert middleware(**kw) is None


def test_policy_hook_never_calls_engine_on_cache_miss():
    r, e = risky()
    assert r.pre_tool_call(**call()) is None
    assert e.risk_calls == 0


def test_risk_prepared_outside_policy_then_consumed_once():
    r, e = risky()
    prepare(r, **call())
    assert e.risk_calls == 1
    assert r.pre_tool_call(**call())["action"] == "approve"
    assert r.pre_tool_call(**call()) is None
    assert e.risk_calls == 1


def test_approval_requires_human_path_and_records_abstention():
    r, e = risky()
    r.approval_available = lambda: False
    prepare(r, **call())
    assert r.pre_tool_call(**call()) is None
    assert any(x.get("risk") == "unattended" for x in r.telemetry.snapshot()["recent"])


def test_prepared_result_cannot_cross_action_call_turn_or_session():
    r, e = risky()
    kw = call()
    prepare(r, **kw)
    for changes in (
        {"args": {"command": "delete other data"}},
        {"tool_call_id": "other"},
        {"turn_id": "other"},
        {"session_id": "other"},
    ):
        assert r.pre_tool_call(**(kw | changes)) is None
    # Preparing a fresh exact call is sufficient; mismatches never authorize it.
    prepare(r, **kw)
    assert r.pre_tool_call(**kw)["action"] == "approve"


def test_missing_call_identity_abstains():
    r, e = risky()
    kw = call() | {"tool_call_id": ""}
    prepare(r, **kw)
    assert r.pre_tool_call(**kw) is None
    assert e.risk_calls == 0


def test_late_risk_result_cannot_be_applied_after_timeout():
    r, e = setup(timeout_seconds=0.02)
    r.approval_available = lambda: True
    start(r)
    e.delay = 0.06
    e.risk = RiskDecision(0.99, 1, 1, 1, 0, 1)
    prepare(r, **call())
    assert r.pre_tool_call(**call()) is None
    assert e.risk_calls == 1


def test_slow_risk_does_not_hold_policy_callback():
    r, e = risky()
    entered, release = threading.Event(), threading.Event()

    def slow(state):
        entered.set()
        assert release.wait(2)
        return e.risk

    e.assess_tool_risk = slow
    with ThreadPoolExecutor() as pool:
        future = pool.submit(prepare, r, **call())
        try:
            assert entered.wait(0.5), "risk must run in the request middleware"
            assert r.pre_tool_call(**call()) is None
        finally:
            release.set()
        future.result()
    assert r.pre_tool_call(**call())["action"] == "approve"


def test_approval_rule_and_message_identify_trigger_and_action():
    r, e = risky()
    kw = call()
    prepare(r, **kw)
    first = r.pre_tool_call(**kw)
    e.risk = RiskDecision(0.99, 0.01, 0.01, 0.01, 0.99, 0.01)
    prepare(r, **kw)
    second = r.pre_tool_call(**kw)
    assert first.get("rule_key") and first["rule_key"] != second.get("rule_key")
    assert "destructive" in first["message"]
    assert "exposes_secrets" in second["message"]
    assert "remove build output" in first["message"]
    prepare(r, **(kw | {"args": {"command": "different target"}}))
    third = r.pre_tool_call(**(kw | {"args": {"command": "different target"}}))
    assert third["rule_key"] != second["rule_key"]


def test_missing_mutation_observer_cannot_prove_evidence_fresh():
    r, e = risky()
    e.completion = CompletionDecision(0.99, 0.01, 0.99, 0.99)
    r.post_tool_call(
        session_id="s",
        turn_id="t",
        tool_name="terminal",
        args={"command": "pytest"},
        result={"exit_code": 0, "output": "passed"},
    )
    # A later edit happened, but Hermes skipped its post_tool_call observer.
    result = r.pre_verify(session_id="s", changed_paths=["changed.py"], final_response="Done")
    assert result and result["action"] == "continue"
    state = e.states[-1]
    assert state["evidence_freshness"] == "unverified"
    assert all(x["success"] is not True for x in state["verification_evidence"])


@pytest.mark.parametrize("missing", ["approval_order_safe", "approval_available"])
def test_unavailable_compatibility_check_abstains(missing):
    r, e = risky()

    def broken():
        raise RuntimeError("incompatible host")

    setattr(r, missing, broken)
    prepare(r, **call())
    assert r.pre_tool_call(**call()) is None
