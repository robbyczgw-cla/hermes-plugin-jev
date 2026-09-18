"""Review regressions through the real Hermes loader and policy dispatcher."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_hermes_contract import SOURCE, loaded  # noqa: F401

# Pytest fixtures are imported for collection and requested by parameter name.
# ruff: noqa: F811

pytestmark = pytest.mark.skipif(not SOURCE, reason="set HERMES_SOURCE for Hermes contracts")


def prepare_call(runtime, tool="terminal", args=None, **ids):
    from hermes_cli.middleware import apply_tool_request_middleware

    return apply_tool_request_middleware(tool, args or {}, skip_relay=True, **ids)


@pytest.mark.parametrize(
    "platform,interactive,cron,single,expected",
    [
        ("telegram", False, False, False, "approve"),
        ("", True, False, False, "approve"),
        ("", False, False, False, None),
        ("telegram", True, True, False, None),
        ("", True, False, True, None),
        ("api_server", True, False, False, None),
        ("webhook", True, False, False, None),
        ("msgraph_webhook", True, False, False, None),
    ],
)
def test_context_aware_approval(loaded, monkeypatch, platform, interactive, cron, single, expected):
    from gateway.session_context import _VAR_MAP
    from hermes_cli.plugins import _get_pre_tool_call_directive_details
    from tools import approval

    manager, runtime = loaded
    monkeypatch.setenv("HERMES_GATEWAY_SESSION", "1" if platform else "")
    # Explicit ContextVars must win over stale process environment flags.
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    tokens = [
        (var, var.set(value))
        for var, value in [
            (_VAR_MAP["HERMES_SESSION_PLATFORM"], platform),
            (_VAR_MAP["HERMES_CRON_SESSION"], "1" if cron else ""),
        ]
    ]
    monkeypatch.setenv("HERMES_SINGLE_QUERY_SESSION", "1" if single else "")
    token = approval.set_hermes_interactive_context(interactive)
    try:
        ids = dict(session_id="s", turn_id="t", tool_call_id="c")
        args = {"command": "remove build output"}
        result = prepare_call(runtime, args=args, **ids)
        assert not result.changed and result.payload == args
        details = _get_pre_tool_call_directive_details("terminal", args, **ids)
        assert details.action == expected
        if expected:
            assert details.rule_key.startswith("jev:")
        else:
            assert any(
                x.get("risk") == "unattended" for x in runtime.telemetry.snapshot()["recent"]
            )
    finally:
        approval.reset_hermes_interactive_context(token)
        for var, token in reversed(tokens):
            var.reset(token)


def test_slow_risk_request_does_not_block_other_session(loaded):
    from hermes_cli.plugins import get_pre_tool_call_directive

    manager, runtime = loaded
    runtime.approval_available = lambda: True
    entered, release = threading.Event(), threading.Event()
    risk = runtime.engine.assess_tool_risk({})

    def slow(state):
        entered.set()
        assert release.wait(2)
        return risk

    runtime.engine.assess_tool_risk = slow
    ids = dict(session_id="s", turn_id="t", tool_call_id="c")
    args = {"command": "remove build output"}

    def first():
        prepare_call(runtime, args=args, **ids)
        return get_pre_tool_call_directive("terminal", args, **ids)

    with ThreadPoolExecutor() as pool:
        future = pool.submit(first)
        try:
            assert entered.wait(0.5)
            # A second session reaches policy while the first is waiting on Jev.
            other = get_pre_tool_call_directive(
                "read_file", {}, session_id="other", turn_id="t", tool_call_id="other"
            )
            assert other == (None, None)
        finally:
            release.set()
        assert future.result()[0] == "approve"


def test_unattended_keeps_deterministic_block(loaded):
    from hermes_cli.plugins import get_pre_tool_call_directive

    manager, runtime = loaded
    runtime.approval_available = lambda: False
    manager._hooks["pre_tool_call"].insert(0, lambda **kw: {"action": "block", "message": "policy"})
    ids = dict(session_id="s", turn_id="t", tool_call_id="c")
    prepare_call(runtime, **ids)
    assert get_pre_tool_call_directive("terminal", {}, **ids) == ("block", "policy")
