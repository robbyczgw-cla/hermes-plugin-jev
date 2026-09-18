"""Optional contracts against a real Hermes checkout, isolated from the user's home.

Run with HERMES_SOURCE set and the Hermes Python environment. No live TypeSafe calls.
"""

import importlib
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = os.environ.get("HERMES_SOURCE")
pytestmark = pytest.mark.skipif(not SOURCE, reason="set HERMES_SOURCE to run real Hermes contracts")
if SOURCE:
    sys.path.insert(0, SOURCE)


@pytest.fixture
def loaded(tmp_path, monkeypatch):
    import yaml
    from hermes_cli import plugins

    home = tmp_path / "home"
    target = home / "plugins" / "jev-router"
    shutil.copytree(
        Path(__file__).resolve().parents[1],
        target,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "dist",
            "build",
            "*.egg-info",
        ),
    )
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "plugins": {
                    "enabled": ["jev-router"],
                    "entries": {
                        "jev-router": {
                            "settings": {
                                "timeout_seconds": 0.3,
                                "tool_shaping": {"min_confidence": 0.98},
                            }
                        }
                    },
                }
            }
        )
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    manager = plugins.PluginManager(scope_key=str(home))
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: manager)
    # No installed entry-point plugins from the operator's environment.
    monkeypatch.setattr(manager, "_scan_entry_points", lambda: [])
    manager.discover_and_load()
    callbacks = manager.iter_hook_callbacks("pre_llm_call")
    assert len(callbacks) == 1, {k: v.error for k, v in manager._plugins.items() if v.error}
    runtime = callbacks[0].__self__
    module = importlib.import_module(runtime.__class__.__module__.rsplit(".", 1)[0] + ".decisions")
    runtime.engine = SimpleNamespace(
        classify_turn=lambda state: module.TurnDecision(
            "chat", "trivial", 0.001, 0.001, 0.001, 0.001, 0.001, "low", 0.999
        ),
        assess_tool_risk=lambda state: module.RiskDecision(0.99, 0.99, 0.99, 0.99, 0.01, 0.99),
        assess_completion=lambda state: module.CompletionDecision(0.99, 0.01, 0.99, 0.99),
    )
    manager.invoke_hook(
        "pre_llm_call",
        session_id="s",
        turn_id="t",
        user_message="hello",
        platform="test",
        model="test",
    )
    yield manager, runtime
    manager.unload()


@pytest.mark.parametrize("missing", [None, "provides_hooks", "provides_middleware"])
def test_catalog_validator(loaded, missing):
    if not (Path(SOURCE) / "hermes_cli" / "plugin_validate.py").is_file():
        pytest.skip("this Hermes checkout predates the catalog validator")
    import yaml
    from hermes_cli.plugin_validate import validate_plugin_dir

    target = Path(os.environ["HERMES_HOME"]) / "plugins" / "jev-router"
    if missing:
        manifest_path = target / "plugin.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest.pop(missing)
        manifest_path.write_text(yaml.safe_dump(manifest))
    report = validate_plugin_dir(target).to_dict()
    if missing:
        expected = "declared " + missing.removeprefix("provides_")
        assert any(c["name"] == expected and not c["ok"] for c in report["checks"]), report
        assert not report["ok"]
    else:
        assert report["ok"], report


def test_official_loader_config_and_cli(loaded, capsys):
    manager, runtime = loaded
    assert runtime.config.min_confidence == 0.98
    assert manager.has_middleware("llm_request")
    assert runtime.status()["active"]
    assert not runtime.status()["api_key_configured"]
    command = manager._cli_commands["jev"]
    command["handler_fn"](SimpleNamespace(action="status"))
    assert "api_key_configured" in capsys.readouterr().out


def test_real_middleware_first_call_and_trace(loaded):
    from hermes_cli.middleware import apply_llm_request_middleware

    manager, runtime = loaded
    request = {
        "model": "test",
        "messages": [],
        "tools": [
            {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
            for name in ("terminal", "read_file", "clarify", "todo")
        ],
    }
    result = apply_llm_request_middleware(request, session_id="s", turn_id="t", api_call_count=1)
    assert result.changed
    assert len(result.payload["tools"]) == 2
    assert len(request["tools"]) == 4
    assert result.trace[0]["source"] == "jev-router"
    assert not apply_llm_request_middleware(
        request, session_id="s", turn_id="t", api_call_count=2
    ).changed


def test_real_approval_directive_and_earlier_block(loaded):
    from hermes_cli.middleware import apply_tool_request_middleware
    from hermes_cli.plugins import get_pre_tool_call_directive

    manager, runtime = loaded
    runtime.approval_available = lambda: True
    ids = dict(session_id="s", turn_id="t", tool_call_id="c")
    apply_tool_request_middleware("terminal", {"command": "rm -rf build"}, skip_relay=True, **ids)
    assert (
        get_pre_tool_call_directive("terminal", {"command": "rm -rf build"}, **ids)[0] == "approve"
    )
    manager._hooks["pre_tool_call"].insert(
        0, lambda **kw: {"action": "block", "message": "deterministic deny"}
    )
    assert get_pre_tool_call_directive("terminal", {}, session_id="s", turn_id="t") == (
        "block",
        "deterministic deny",
    )


def test_later_block_cannot_be_shadowed(loaded):
    from hermes_cli.middleware import apply_tool_request_middleware
    from hermes_cli.plugins import get_pre_tool_call_directive

    manager, runtime = loaded
    runtime.approval_available = lambda: True
    ids = dict(session_id="s", turn_id="t", tool_call_id="c")
    apply_tool_request_middleware("terminal", {}, skip_relay=True, **ids)
    manager._hooks["pre_tool_call"].append(
        lambda **kw: {"action": "block", "message": "later deny"}
    )
    assert get_pre_tool_call_directive("terminal", {}, **ids) == (
        "block",
        "later deny",
    )


def test_real_verify_contract_and_end(loaded):
    from hermes_cli.plugins import get_pre_verify_continue_message

    manager, runtime = loaded
    assert get_pre_verify_continue_message(
        session_id="s", changed_paths=["a.py"], final_response="Everything implemented.", attempt=0
    )
    assert (
        get_pre_verify_continue_message(
            session_id="s",
            changed_paths=["a.py"],
            final_response="Everything implemented.",
            attempt=2,
        )
        is None
    )
    manager.invoke_hook("post_llm_call", session_id="s", turn_id="t")
    assert runtime.cache.get("s") is None
    manager.invoke_hook("on_session_end", session_id="s")
    assert len(runtime.cache) == 0


def test_official_cli_status(loaded):
    import subprocess

    env = dict(os.environ)
    env["PYTHONPATH"] = SOURCE
    result = subprocess.run(
        [sys.executable, "-m", "hermes_cli.main", "jev", "status"],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["enabled"] is True
    assert status["api_key_configured"] is False
    assert status["active"] is False
