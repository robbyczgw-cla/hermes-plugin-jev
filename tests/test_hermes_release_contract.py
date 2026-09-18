"""Pinned host turn-context helper, not just invented hook keyword arguments."""

from types import SimpleNamespace

import pytest
from test_hermes_contract import SOURCE, loaded  # noqa: F401
from test_input_safety import request

# ruff: noqa: F811
pytestmark = pytest.mark.skipif(not SOURCE, reason="set HERMES_SOURCE for host contracts")


@pytest.mark.parametrize("first", [True, False])
@pytest.mark.parametrize("injected", [True, False])
def test_host_turn_context_and_provider_message_guard(loaded, first, injected):
    from agent.turn_context import _collect_pre_llm_call_context
    from hermes_cli.middleware import apply_llm_request_middleware

    manager, runtime = loaded
    agent = SimpleNamespace(session_id="host-turn", model="synthetic", platform="test")
    messages = [{"role": "user", "content": "hello"}]
    if injected:
        manager._hooks["pre_llm_call"].append(lambda **kw: {"context": "Synthetic plugin context"})
    context = _collect_pre_llm_call_context(
        agent,
        effective_task_id="task",
        turn_id="new",
        original_user_message="hello",
        messages=messages,
        conversation_history=None if first else [{"role": "assistant", "content": "Prior task"}],
    )
    state = runtime.cache.get("host-turn", "new").state
    assert state["conversation"]["prior_turn_seen"] is not first
    payload = request("hello" + ("\n\n" + context if context else ""))
    result = apply_llm_request_middleware(
        payload, session_id="host-turn", turn_id="new", api_call_count=1
    )
    assert result.changed is (first and not injected)
