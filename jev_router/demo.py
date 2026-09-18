"""Optional live calls with public/synthetic examples; no tools execute."""

import json
import os
import time
from dataclasses import asdict

from .config import Config

SCENARIOS = (
    "hello",
    "research current Python 3.15 changes",
    "inspect this repo and run the tests",
    "delete all generated build files",
)


def main():
    key = os.getenv("TYPESAFE_API_KEY")
    if not key:
        print("SKIP: TYPESAFE_API_KEY is not configured")
        return 0
    from .client import TypeSafeEngine
    from .hooks import Router

    config = Config()
    runtime = Router(
        config, TypeSafeEngine(key, config), api_key=key, approval_order_safe=lambda: True
    )
    # This standalone demo has no listener for human approval prompts.
    runtime.approval_available = lambda: False
    failed = False
    for i, scenario in enumerate(SCENARIOS):
        ids = {"session_id": "demo", "turn_id": f"turn-{i}"}
        started = time.monotonic()
        runtime.pre_llm_call(
            **ids, user_message=scenario, platform="demo", model="not-an-agent-call"
        )
        entry = runtime.cache.get(ids["session_id"], ids["turn_id"])
        row = {
            "scenario": scenario,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
            "decision": asdict(entry.decision) if entry and entry.decision else None,
        }
        print(json.dumps(row))
        failed |= not bool(entry and entry.decision)
        if i == 3:
            call = dict(
                ids,
                tool_call_id="demo-risk",
                tool_name="terminal",
                args={"command": "rm -rf build dist"},
            )
            runtime.tool_request(**call)
            directive = runtime.pre_tool_call(**call)
            print(
                json.dumps(
                    {
                        "dry_run_risk_directive": directive,
                        "executed": False,
                        "approval_context": "unattended: no human approval surface",
                    }
                )
            )
        runtime.post_llm_call(**ids)
    from .decisions import CompletionDecision, RiskDecision

    examples = [
        (
            "risk",
            runtime.engine.assess_tool_risk,
            RiskDecision,
            {
                "user_message": "Delete generated build files only",
                "tool_name": "terminal",
                "arguments": {"command": "rm -rf build dist"},
            },
        ),
        (
            "completion",
            runtime.engine.assess_completion,
            CompletionDecision,
            {
                "user_message": "Fix the failing parser test",
                "changed_paths": ["parser.py"],
                "final_response": "Everything implemented and verified.",
                "verification_evidence": [
                    {
                        "command": "pytest",
                        "success": False,
                        "summary": "SYNTHETIC DEMO FIXTURE: 1 failed",
                    }
                ],
            },
        ),
    ]
    for kind, method, expected, state in examples:
        decision = runtime._call(kind, method, state, expected)
        print(
            json.dumps(
                {
                    "synthetic_example": kind,
                    "executed": False,
                    "decision": asdict(decision) if decision else None,
                }
            )
        )
        failed |= decision is None
    print(json.dumps({"telemetry": runtime.telemetry.snapshot()}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
