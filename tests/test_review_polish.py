"""Approval identifiers must not carry terminal control text or raw tool names."""

from test_review_regressions import call, prepare, risky


def test_rule_key_is_bounded_ascii_and_does_not_include_raw_tool_name():
    r, _ = risky()
    name = "unsafe\n\x1b[2J" + "private-tool-name" * 20
    kw = call() | {"tool_name": name}
    prepare(r, **kw)
    directive = r.pre_tool_call(**kw)
    assert directive is not None
    key = directive["rule_key"]
    assert len(key) <= 256
    assert key.isascii() and all(c.isalnum() or c in ":+-_" for c in key)
    assert "private-tool-name" not in key


def test_standalone_demo_labels_unattended_abstention(monkeypatch, capsys):
    import json

    from test_runtime import Engine

    from jev_router import demo

    engine = Engine()
    monkeypatch.setenv("TYPESAFE_API_KEY", "demo-test-key")
    monkeypatch.setattr("jev_router.client.TypeSafeEngine", lambda *a, **k: engine)
    monkeypatch.setattr("jev_router.hooks.human_approval_available", lambda: False)
    assert demo.main() == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    dry = next(row for row in rows if "dry_run_risk_directive" in row)
    assert dry["dry_run_risk_directive"] is None
    assert dry["approval_context"] == "unattended: no human approval surface"
    # One explicit synthetic risk example, no hidden policy-hook request.
    assert engine.risk_calls == 1
