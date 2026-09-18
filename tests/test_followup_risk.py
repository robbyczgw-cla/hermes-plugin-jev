import pytest
from test_input_safety import enforcing
from test_runtime import start


@pytest.mark.parametrize(
    "text", ["yes, do it", "continue", "fix that", "run the tests too", "ja, mach weiter"]
)
def test_incomplete_referent_cannot_become_low_risk(text):
    r = enforcing()
    start(r, text=text)
    call = dict(
        session_id="s",
        turn_id="t",
        tool_call_id="c",
        tool_name="terminal",
        args={"command": "echo ok"},
    )
    r.tool_request(**call)
    proposal = r.pre_tool_call(**call)
    assert proposal and proposal["action"] == "approve"
    assert "ambiguous_context" in proposal["message"]
    assert r.engine.states[-1]["context_ambiguous"] is True


def test_incomplete_actions_cannot_share_a_remembered_approval_rule():
    r = enforcing()
    start(r)
    rules = []
    for i, tail in enumerate(("; remove one", "; remove two")):
        call = dict(
            session_id="s",
            turn_id="t",
            tool_call_id=str(i),
            tool_name="terminal",
            args={"command": "echo " + "x" * 2000 + tail},
        )
        r.tool_request(**call)
        proposal = r.pre_tool_call(**call)
        assert proposal and proposal["action"] == "approve"
        rules.append(proposal["rule_key"])
    assert len(set(rules)) == 2


def test_followup_risk_fallback_stays_conservative():
    r = enforcing()
    start(r, text="continue")
    r.engine.error = True
    call = dict(
        session_id="s",
        turn_id="t",
        tool_call_id="c",
        tool_name="terminal",
        args={"command": "echo ok"},
    )
    r.tool_request(**call)
    proposal = r.pre_tool_call(**call)
    assert proposal and proposal["action"] == "approve"
