"""Explicit opt-in only. No tools are executed by this smoke test."""

import os

import pytest


@pytest.mark.skipif(
    not (os.getenv("TYPESAFE_API_KEY") and os.getenv("RUN_JEV_LIVE") == "1"),
    reason="Set RUN_JEV_LIVE=1 and TYPESAFE_API_KEY for the optional live demo",
)
def test_live_demo():
    from jev_router.demo import main

    assert main() == 0
