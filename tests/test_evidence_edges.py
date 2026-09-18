"""Commands that must not count as positive post-edit test evidence."""

import pytest
from test_runtime import setup, start


@pytest.mark.parametrize(
    "command",
    [
        "pytest & true",
        "pytest --collect-only",
        "pytest --version",
        "pytest --help",
        "ruff check --fix .",
        "npm test -- --updateSnapshot",
    ],
)
def test_non_verification_or_mutating_commands_invalidate_success(command):
    router, engine = setup()
    start(router)
    router.post_tool_call(
        session_id="s",
        turn_id="t",
        tool_name="terminal",
        args={"command": "pytest"},
        result={"exit_code": 0, "output": "passed"},
    )
    router.post_tool_call(
        session_id="s",
        turn_id="t",
        tool_name="terminal",
        args={"command": command},
        result={"exit_code": 0, "output": "done"},
    )
    assert not any(e["success"] is True for e in router.cache.get("s", "t").evidence)


@pytest.mark.parametrize(
    "result,status",
    [
        ({"exit_code": 0, "error": "transport broke"}, "error"),
        ({"exit_code": 0, "session_id": "async-process"}, "ok"),
    ],
)
def test_error_or_background_handles_are_not_completed_tests(result, status):
    router, engine = setup()
    start(router)
    router.post_tool_call(
        session_id="s",
        turn_id="t",
        tool_name="terminal",
        args={"command": "pytest"},
        result=result,
        status=status,
    )
    assert not any(e["success"] is True for e in router.cache.get("s", "t").evidence)
