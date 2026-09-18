import subprocess
import sys

import pytest

from jev_router.privacy import Sanitizer


def test_large_inputs_have_bounded_sanitization_cost():
    code = "from jev_router.privacy import Sanitizer; s=Sanitizer(); s.prepare({'arguments': 'x'*65536}); s.prepare({'arguments': 'secret'*10000})"
    subprocess.run([sys.executable, "-c", code], check=True, timeout=3)


@pytest.mark.parametrize(
    "text",
    [
        "API_KEY=private-value",
        "https://example.test/?password=private-value&public=yes",
        "outer=inner_token=private-value",
        'prefix_password="private-value"',
    ],
)
def test_assignment_redaction_preserves_embedded_credentials(text):
    assert "private-value" not in Sanitizer().text(text)
