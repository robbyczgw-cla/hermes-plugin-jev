"""Executable checks for the documented quickstart and shipped reference."""

import ast
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import pytest
import yaml

from jev_router.config import Config

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "docs" / "reference.md"]
LINK_DOCS = [*DOCS, ROOT / "docs" / "shadow-trial.md"]


def flatten(values, prefix=""):
    result = {}
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten(value, path))
        else:
            result[path] = value
    return result


@pytest.mark.parametrize("path", DOCS, ids=["readme", "reference"])
def test_documented_configs_load_with_shadow_defaults(path):
    text = path.read_text()
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.S)
    assert blocks, "Keep a copyable configuration example"
    config_tree = ast.parse((ROOT / "jev_router" / "config.py").read_text())
    allowed = next(
        set(ast.literal_eval(node.value).values())
        for node in ast.walk(config_tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "paths" for target in node.targets)
    )
    for block in blocks:
        values = yaml.safe_load(block)
        settings = flatten(values["plugins"]["entries"]["jev-router"]["settings"])
        assert set(settings) <= allowed
        config = Config.from_context(
            SimpleNamespace(get_config=lambda key, default: settings.get(key, default))
        )
        assert config.mode == "shadow"
        assert config.risk_enabled is True
        assert config.shaping_enabled is False
        assert config.verify_enabled is False
        assert config.block_unbindable is False


@pytest.mark.parametrize("path", LINK_DOCS, ids=["readme", "reference", "shadow-trial"])
def test_documentation_local_links_and_anchors_resolve(path):
    text = path.read_text()
    links = re.findall(r"\[[^\]]*\]\(([^)]+)\)", text)
    assert links
    for link in links:
        parts = urlsplit(link)
        if parts.scheme or parts.netloc:
            continue
        target = (path.parent / unquote(parts.path)).resolve() if parts.path else path
        assert target.is_relative_to(ROOT), link
        assert target.is_file(), link
        if parts.fragment:
            headers = re.findall(r"^#{1,6}\s+(.+)$", target.read_text(), re.M)
            anchors = {
                re.sub(r"[^\w\- ]", "", header.lower()).replace(" ", "-") for header in headers
            }
            assert unquote(parts.fragment) in anchors, link


def test_reference_in_source_and_wheel_manifest():
    assert "recursive-include docs *.md" in (ROOT / "MANIFEST.in").read_text()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    data = project["tool"]["setuptools"]["data-files"]
    assert "docs/reference.md" in data["share/doc/hermes-plugin-jev/docs"]
    assert "docs/shadow-trial.md" in data["share/doc/hermes-plugin-jev/docs"]


def test_preview_install_is_pinned_and_never_enables_implicitly():
    text = (ROOT / "README.md").read_text()
    commands = re.findall(r"```(?:bash|sh)\n(.*?)```", text, re.S)
    installs = [
        block.replace("\\\n", " ") for block in commands if "hermes plugins install" in block
    ]
    assert installs
    for command in installs:
        assert re.search(r"--ref\s+[0-9a-f]{40}\b", command)
        assert "--no-enable" in command
    assert "hermes jev status" in text
    assert "jev-router status" not in text


def test_preview_identity_and_default_branch_guidance_match_metadata():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text())
    assert project["project"]["version"] == manifest["version"]
    text = (ROOT / "README.md").read_text()
    assert f"**{manifest['version']} preview/beta" in text
    assert "not `main`" not in text
    assert "older default branch" not in text
    assert "docs/shadow-trial.md" in text
