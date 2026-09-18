"""Behavioral guarantees through the real Hermes dispatcher; fake Jev only."""

from dataclasses import replace

import pytest
from test_hermes_contract import SOURCE, loaded  # noqa: F401
from test_input_safety import request

# Imported pytest fixture.
# ruff: noqa: F811
pytestmark = pytest.mark.skipif(not SOURCE, reason="set HERMES_SOURCE for Hermes contracts")


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
@pytest.mark.parametrize("position", ["before", "after"])
def test_blocking_hooks_keep_precedence(loaded, mode, position):
    from hermes_cli.middleware import apply_tool_request_middleware
    from hermes_cli.plugins import get_pre_tool_call_directive

    manager, runtime = loaded
    runtime.config = replace(runtime.config, mode=mode)
    runtime.approval_available = lambda: True

    def block(**kw):
        return {"action": "block", "message": "existing deterministic block"}

    if position == "before":
        manager._hooks["pre_tool_call"].insert(0, block)
    else:
        manager._hooks["pre_tool_call"].append(block)
    ids = dict(session_id="s", turn_id="t", tool_call_id="c")
    args = {"command": "delete build"}
    apply_tool_request_middleware("terminal", args, skip_relay=True, **ids)
    assert get_pre_tool_call_directive("terminal", args, **ids) == (
        "block",
        "existing deterministic block",
    )


def test_shadow_real_host_has_no_behavioral_directives(loaded):
    from hermes_cli.middleware import apply_llm_request_middleware, apply_tool_request_middleware
    from hermes_cli.plugins import get_pre_tool_call_directive, get_pre_verify_continue_message

    manager, runtime = loaded
    runtime.config = replace(runtime.config, mode="shadow")
    runtime.approval_available = lambda: True
    ids = dict(session_id="s", turn_id="t")
    original = request()
    assert not apply_llm_request_middleware(original, api_call_count=1, **ids).changed
    args = {"command": "delete build"}
    assert not apply_tool_request_middleware(
        "terminal", args, tool_call_id="c", skip_relay=True, **ids
    ).changed
    assert get_pre_tool_call_directive("terminal", args, tool_call_id="c", **ids) == (None, None)
    assert (
        get_pre_verify_continue_message(
            changed_paths=["source.py"], final_response="complete", attempt=0, session_id="s"
        )
        is None
    )
    assert not runtime.prepared.items


@pytest.mark.parametrize("message", ["yes, do it", "continue", "fix that", "run the tests too"])
def test_real_host_retains_tools_for_followup(loaded, message):
    from hermes_cli.middleware import apply_llm_request_middleware

    manager, runtime = loaded
    manager.invoke_hook("pre_llm_call", session_id="s", turn_id="next", user_message=message)
    result = apply_llm_request_middleware(
        request(message), session_id="s", turn_id="next", api_call_count=1
    )
    assert not result.changed
