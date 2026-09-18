"""Reproductions from the independent release review, plus host lifecycle gaps."""

import pytest
from test_input_safety import request
from test_runtime import setup, start


@pytest.mark.parametrize(
    "text", ["Refactor this module", "Please fix that bug", "Add a test for it"]
)
@pytest.mark.parametrize("outage", [False, True])
def test_normal_imperatives_do_not_force_approval_without_risk(text, outage):
    r, e = setup()
    start(r, text=text)
    e.error = outage
    kw = dict(
        session_id="s",
        turn_id="t",
        tool_call_id="c",
        tool_name="terminal",
        args={"command": "pytest tests/test_parser.py"},
    )
    r.tool_request(**kw)
    assert r.pre_tool_call(**kw) is None


def test_default_risk_gate_does_not_veto_large_native_write():
    r, _ = setup()
    start(r, text="Write the generated sample file")
    kw = dict(
        session_id="s",
        turn_id="t",
        tool_call_id="c",
        tool_name="write_file",
        args={"path": "sample.py", "content": "x" * 70000},
    )
    r.tool_request(**kw)
    assert r.pre_tool_call(**kw) is None


def test_explicit_host_resume_signal_preserves_tools_without_cached_history():
    r, _ = setup()
    r.pre_llm_call(session_id="resumed", turn_id="new", user_message="hello", is_first_turn=False)
    assert (
        r.llm_request(request=request(), session_id="resumed", turn_id="new", api_call_count=1)
        is None
    )


def test_normal_sized_failure_output_remains_usable_evidence():
    r, e = setup()
    start(r, text="Implement parser")
    r.post_tool_call(
        session_id="s",
        turn_id="t",
        tool_name="terminal",
        args={"command": "pytest"},
        result={"exit_code": 1, "output": "F " * 300},
    )
    r.pre_verify(
        session_id="s",
        turn_id="t",
        changed_paths=["parser.py"],
        final_response="Everything implemented",
    )
    state = e.states[-1]
    assert state["input_metadata"]["input_complete"] is True
    assert state["verification_evidence"][0]["success"] is False


def test_unbindable_config_is_opt_in_and_strictly_boolean():
    from test_hardening import Context

    from jev_router.config import Config

    assert Config().block_unbindable is False
    assert (
        Config.from_context(Context({"risk_gate.block_unbindable": True})).block_unbindable is True
    )
    with pytest.raises(ValueError):
        Config(block_unbindable="true")
