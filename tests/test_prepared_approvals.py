"""Cache and compatibility failure boundaries for semantic approval proposals."""

import pytest
from test_review_regressions import call, prepare, risky

from jev_router.approval import PreparedApprovals, action_digest, human_approval_available


def test_cache_is_bounded_single_use_and_expires(monkeypatch):
    import jev_router.approval as module

    now = [1.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    cache = PreparedApprovals(size=1, ttl=1)
    a, b = ("a", "t", "c", "terminal"), ("b", "t", "c", "terminal")
    cache.put(a, "a", {"action": "approve"})
    cache.put(b, "b", {"action": "approve"})
    assert cache.take(a, "a") is None
    assert cache.take(b, "b") == {"action": "approve"}
    assert cache.take(b, "b") is None
    cache.put(b, "b", {"action": "approve"})
    now[0] += 2
    assert cache.take(b, "b") is None


def test_contended_cache_does_not_wait():
    r, _ = risky()
    prepare(r, **call())
    with r.prepared.lock:
        # Deliberately hold a non-reentrant lock on this very thread.
        assert r.pre_tool_call(**call()) is None


def test_end_session_clears_prepared_proposals():
    r, _ = risky()
    prepare(r, **call())
    r.on_session_end(session_id="s")
    assert r.pre_tool_call(**call()) is None


def test_result_arriving_after_session_end_is_not_cached():
    r, e = risky()
    risk = e.risk

    def end_during_call(state):
        r.on_session_end(session_id="s")
        return risk

    e.assess_tool_risk = end_during_call
    prepare(r, **call())
    assert r.pre_tool_call(**call()) is None


def test_context_change_after_preparation_abstains():
    r, _ = risky()
    prepare(r, **call())
    r.approval_available = lambda: False
    assert r.pre_tool_call(**call()) is None


@pytest.mark.parametrize(
    "args", [None, [], {"x": object()}, {"x": float("nan")}, {"x": "a" * 70000}]
)
def test_invalid_or_oversize_args_have_no_digest(args):
    assert action_digest(args) is None


def test_digest_is_key_order_independent_and_value_sensitive():
    assert action_digest({"a": 1, "b": 2}) == action_digest({"b": 2, "a": 1})
    assert action_digest({"a": 1}) != action_digest({"a": 2})


def test_approval_details_do_not_expose_secret(monkeypatch):
    secret = "test-only-long-credential"
    monkeypatch.setenv("TYPESAFE_API_KEY", secret)
    r, _ = risky()
    kw = call() | {"args": {"command": "publish", "api_key": secret}}
    prepare(r, **kw)
    directive = r.pre_tool_call(**kw)
    assert directive["action"] == "approve"
    assert secret not in str(directive)


def test_missing_hermes_approval_api_abstains(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "tools.approval", None)
    monkeypatch.setitem(sys.modules, "tools", None)
    assert human_approval_available() is False
