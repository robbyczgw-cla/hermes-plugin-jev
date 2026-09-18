"""Run the pinned Hermes contracts and reject a green-but-skipped report."""

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERMES_REVISION = "77ecc72bcdd5da0163cca21c8af0e95b26ba3426"


def check_report(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError("Hermes integration collected no test cases")
    for case in cases:
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error")):
            raise ValueError("Hermes integration contains skipped or failed tests")
    return len(cases)


def main():
    source = os.environ.get("HERMES_SOURCE")
    if not source or not (Path(source) / "hermes_cli" / "plugins.py").is_file():
        raise ValueError("HERMES_SOURCE must point to the pinned Hermes checkout")
    revision = subprocess.check_output(
        ["git", "-C", source, "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != HERMES_REVISION:
        raise ValueError("Unexpected Hermes revision; review and update the CI pin explicitly")
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / "tests").glob("test_hermes*.py"))
    if not files:
        raise ValueError("Hermes integration test files are missing")
    env = dict(os.environ)
    env.pop("TYPESAFE_API_KEY", None)
    env.pop("RUN_JEV_LIVE", None)
    env["HERMES_SOURCE"] = str(Path(source).resolve())
    with tempfile.TemporaryDirectory(prefix="jev-integration-") as temp:
        report = Path(temp) / "junit.xml"
        env["HERMES_HOME"] = str(Path(temp) / "home")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                *map(str, files),
                "-q",
                "-W",
                "error",
                f"--junitxml={report}",
            ],
            cwd=root,
            env=env,
            check=True,
        )
        count = check_report(report)
        print(f"Pinned Hermes integration: {count} passed, zero skipped ({revision})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
