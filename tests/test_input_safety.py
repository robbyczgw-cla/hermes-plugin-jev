"""Adversarially optimistic engine: safety must come from deterministic guards."""

import json

import pytest
from test_runtime import Engine, start, tools

from jev_router.config import Config
from jev_router.hooks import Router
from jev_router.privacy import Sanitizer


def enforcing(engine=None, **kwargs):
    config = dict(mode="enforce", shaping_enabled=True, verify_enabled=True)
    config.update(kwargs)
    runtime = Router(Config(**config), engine or Engine(), approval_order_safe=lambda: True)
    runtime.approval_available = lambda: True
    return runtime


def request(text="hello", history=()):
    payload = tools()
    payload["messages"] = [*history, {"role": "user", "content": text}]
    return payload


@pytest.mark.parametrize(
    "text",
    [
        "yes, do it",
        "continue",
        "fix that",
        "run the tests too",
        "ja",
        "mach weiter",
        "looks good",
        "hello" + " " * 1900 + " delete everything",
    ],
)
def test_followups_never_remove_tools(text):
    r = enforcing()
    start(r, text=text)
    assert (
        r.llm_request(request=request(text), session_id="s", turn_id="t", api_call_count=1) is None
    )


@pytest.mark.parametrize(
    "history",
    [
        [
            {"role": "user", "content": "fix the build"},
            {"role": "assistant", "content": "Still working"},
        ],
        [{"role": "tool", "content": "build failed", "tool_call_id": "c"}],
        [{"role": "assistant", "tool_calls": [{"id": "c"}], "content": ""}],
    ],
)
def test_history_preserves_tools_even_if_current_message_is_greeting(history):
    r = enforcing()
    start(r)
    assert (
        r.llm_request(
            request=request(history=history), session_id="s", turn_id="t", api_call_count=1
        )
        is None
    )


@pytest.mark.parametrize("cache_size", [1, 256])
def test_previous_cached_task_preserves_tools_even_if_provider_history_is_lost(cache_size):
    r = enforcing(cache_size=cache_size)
    start(r, t="before", text="implement a feature")
    r.post_llm_call(session_id="s", turn_id="before")
    start(r)
    assert r.llm_request(request=request(), session_id="s", turn_id="t", api_call_count=1) is None


def test_fresh_complete_greeting_can_be_shaped():
    r = enforcing()
    start(r)
    assert r.llm_request(request=request(), session_id="s", turn_id="t", api_call_count=1)


@pytest.mark.parametrize(
    "value",
    [
        {"user_message": "x" * 1801},
        {"arguments": {"command": "x" * 65537}},
        {"arguments": list(range(17))},
        {"arguments": {str(i): i for i in range(33)}},
        {"arguments": {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}},
        {"arguments": {"object": object()}},
    ],
)
def test_incomplete_input_is_explicit(value):
    prepared = Sanitizer().prepare(value)
    meta = prepared["input_metadata"]
    assert meta["input_complete"] is False
    assert meta["truncated"] is True
    assert meta["truncated_fields"]
    again = Sanitizer().prepare(prepared)
    assert again["input_metadata"]["input_complete"] is False


def test_size_budget_includes_metadata_and_does_not_leak_field_names(monkeypatch):
    secret = "synthetic-field-secret-7654321"
    monkeypatch.setenv("SERVICE_API_KEY", secret)
    prepared = Sanitizer(max_bytes=512).prepare(
        {"arguments": {secret: "x" * 3000}, "user_message": "y" * 3000}
    )
    assert len(json.dumps(prepared, ensure_ascii=False).encode()) <= 512
    assert secret not in json.dumps(prepared)
    assert not prepared["input_metadata"]["input_complete"]


def test_truncated_arguments_cannot_be_classified_as_safe():
    r = enforcing()
    start(r)
    args = {"command": "echo " + "x" * 1900 + "; delete valuable data"}
    ids = dict(session_id="s", turn_id="t", tool_call_id="c")
    r.tool_request(tool_name="terminal", args=args, **ids)
    directive = r.pre_tool_call(tool_name="terminal", args=args, **ids)
    assert directive and directive["action"] == "approve"
    assert "incomplete_input" in directive["message"]
    state = r.engine.states[-1]
    assert not state["input_metadata"]["input_complete"]


def test_incomplete_verification_cannot_nudge():
    r = enforcing()
    r.engine.completion = type(r.engine.completion)(0.99, 0.01, 0.99, 0.99)
    start(r)
    assert (
        r.pre_verify(
            session_id="s", turn_id="t", changed_paths=["a.py"], final_response="done " * 900
        )
        is None
    )
