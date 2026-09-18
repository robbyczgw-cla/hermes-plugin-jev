"""Keep catalog capability declarations aligned with real registration."""

from pathlib import Path
from types import SimpleNamespace

import yaml

from jev_router import register


def test_manifest_matches_registered_capabilities(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    hooks, middleware, tools = [], [], []
    ctx = SimpleNamespace(
        get_config=lambda name, default=None: default,
        register_hook=lambda name, callback: hooks.append(name),
        register_middleware=lambda name, callback: middleware.append(name),
        register_tool=lambda name, **kwargs: tools.append(name),
        register_cli_command=lambda *args, **kwargs: None,
    )
    register(ctx)
    manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / "plugin.yaml").read_text())
    assert manifest.get("provides_tools") == tools
    assert sorted(manifest.get("provides_hooks", [])) == sorted(hooks)
    assert sorted(manifest.get("provides_middleware", [])) == sorted(middleware)
    assert "hooks" not in manifest
