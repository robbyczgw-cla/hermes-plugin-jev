import json

import pytest
from test_input_safety import enforcing, request
from test_runtime import start
from test_sdk import engine_and_wire

from jev_router.decisions import CompletionDecision


@pytest.mark.parametrize("mode,expected", [("shadow", None), ("enforce", "block")])
def test_arguments_too_large_to_bind_never_get_approval(mode, expected):
    r = enforcing(mode=mode)
    start(r)
    call = dict(
        session_id="s",
        turn_id="t",
        tool_call_id="c",
        tool_name="terminal",
        args={"command": "x" * 70000},
    )
    r.tool_request(**call)
    directive = r.pre_tool_call(**call)
    assert (directive["action"] if directive else None) == expected
    assert r.engine.risk_calls == 0


def test_incomplete_risk_still_requests_confirmation_after_engine_failure():
    r = enforcing()
    start(r)
    r.engine.error = True
    call = dict(
        session_id="s",
        turn_id="t",
        tool_call_id="c",
        tool_name="terminal",
        args={"command": "x" * 2000},
    )
    r.tool_request(**call)
    assert r.pre_tool_call(**call)["action"] == "approve"


def test_truncated_evidence_cannot_trigger_verification_nudge():
    r = enforcing()
    r.engine.completion = CompletionDecision(0.99, 0.01, 0.99, 0.99)
    start(r)
    r.post_tool_call(
        session_id="s",
        turn_id="t",
        tool_name="terminal",
        args={"command": "pytest"},
        result={"exit_code": 1, "output": "x" * 1000},
    )
    assert (
        r.pre_verify(session_id="s", turn_id="t", changed_paths=["a.py"], final_response="done")
        is None
    )
    assert r.engine.states[-1]["input_metadata"]["input_complete"] is False


def test_metadata_survives_real_sdk_wire(monkeypatch):
    engine, wire, _ = engine_and_wire(monkeypatch)
    r = enforcing(engine)
    start(r, text="hello " + "x" * 2000 + " run tests")
    assert not wire[0]["state"]["input_metadata"]["input_complete"]
    assert wire[0]["state"]["input_metadata"]["truncated"]
    assert "run tests" not in json.dumps(wire[0]["state"])
    assert r.llm_request(request=request(), session_id="s", turn_id="t", api_call_count=1) is None


@pytest.mark.parametrize(
    "mutation",
    [
        {"messages": []},
        {"messages": [{"role": "user", "content": [{"type": "image"}]}]},
        {"previous_response_id": "previous"},
        {"conversation": "remote-history"},
        {"input": "hello"},
    ],
)
def test_unknown_provider_context_never_removes_tools(mutation):
    r = enforcing()
    start(r)
    payload = request()
    payload.update(mutation)
    assert r.llm_request(request=payload, session_id="s", turn_id="t", api_call_count=1) is None
