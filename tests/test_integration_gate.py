import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "integration_gate", Path(__file__).resolve().parents[1] / "scripts/run_hermes_integration.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.mark.parametrize(
    "xml",
    [
        "<testsuites/>",
        "<testsuites><testsuite><testcase><skipped/></testcase></testsuite></testsuites>",
        "<testsuites><testsuite><testcase><failure/></testcase></testsuite></testsuites>",
        "<testsuites><testsuite><testcase><error/></testcase></testsuite></testsuites>",
    ],
)
def test_integration_gate_rejects_non_passes(tmp_path, xml):
    p = tmp_path / "report.xml"
    p.write_text(xml)
    with pytest.raises(ValueError):
        gate.check_report(p)


def test_integration_gate_accepts_only_actual_tests(tmp_path):
    p = tmp_path / "report.xml"
    p.write_text("<testsuites><testsuite><testcase/><testcase/></testsuite></testsuites>")
    assert gate.check_report(p) == 2


def test_missing_hermes_fails_instead_of_skipping(monkeypatch):
    monkeypatch.delenv("HERMES_SOURCE", raising=False)
    with pytest.raises(ValueError, match="HERMES_SOURCE"):
        gate.main()


def test_wrong_pin_fails(monkeypatch, tmp_path):
    (tmp_path / "hermes_cli").mkdir()
    (tmp_path / "hermes_cli/plugins.py").touch()
    monkeypatch.setenv("HERMES_SOURCE", str(tmp_path))
    monkeypatch.setattr(gate.subprocess, "check_output", lambda *a, **kw: "wrong-pin")
    with pytest.raises(ValueError, match="revision"):
        gate.main()
