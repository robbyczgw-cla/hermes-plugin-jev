"""Only synthetic credentials; late-bound secrets must not leave the process."""

import json

from test_sdk import engine_and_wire

from jev_router.privacy import Sanitizer


def test_environment_secret_added_after_sanitizer_creation(monkeypatch):
    sanitizer = Sanitizer()
    secret = "synthetic-late-bound-value-7654321"
    monkeypatch.setenv("SERVICE_API_KEY", secret)
    assert secret not in sanitizer.text("message " + secret)
    assert secret not in json.dumps(sanitizer.clean({"message": secret}))


def test_rotated_and_original_secret_are_both_redacted(monkeypatch):
    old, new = "synthetic-original-value-123456", "synthetic-rotated-value-654321"
    monkeypatch.setenv("SERVICE_TOKEN", old)
    sanitizer = Sanitizer()
    monkeypatch.setenv("SERVICE_TOKEN", new)
    text = sanitizer.text(old + " " + new)
    assert old not in text and new not in text


def test_longest_known_secret_is_removed_before_its_prefix():
    sanitizer = Sanitizer(
        extra_secrets=("synthetic-shared-prefix", "synthetic-shared-prefix-sensitive-tail")
    )
    assert "sensitive-tail" not in sanitizer.text("synthetic-shared-prefix-sensitive-tail")


def test_sdk_wire_redacts_secret_exported_after_engine_creation(monkeypatch):
    engine, requests, _ = engine_and_wire(monkeypatch)
    secret = "synthetic-late-wire-value-87654321"
    monkeypatch.setenv("SERVICE_PASSWORD", secret)
    engine.classify_turn({"user_message": "free text " + secret})
    assert secret not in json.dumps(requests)
