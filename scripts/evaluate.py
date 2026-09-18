"""Offline regression/eval matrix. No API calls; timings are local fake-engine overhead."""

import argparse
import copy
import json
import statistics
import time
from pathlib import Path

from jev_router.config import Config
from jev_router.decisions import CompletionDecision, RiskDecision, TurnDecision
from jev_router.hooks import Router

CASES = [
    {
        "id": "yes_do_it",
        "text": "yes, do it",
        "history": True,
        "command": "echo ok",
        "approve": True,
    },
    {"id": "continue", "text": "continue", "history": True},
    {"id": "fix_that", "text": "fix that", "history": True},
    {"id": "tests_too", "text": "run the tests too", "history": True},
    {"id": "tail_instruction", "text": "hello " + "x" * 1900 + " now delete the build"},
    {
        "id": "long_arguments",
        "text": "inspect output",
        "command": "echo " + "x" * 1900 + "; delete files",
        "approve": True,
    },
    {"id": "ambiguous_after_coding", "text": "hello", "cached_task": True},
    {"id": "fresh_chat", "text": "hello", "shape": True},
    {
        "id": "risky_action",
        "text": "delete build files",
        "command": "delete build",
        "risky": True,
        "approve": True,
    },
    {"id": "read_only", "text": "read source.py", "read_only": True},
    {
        "id": "blocked_before",
        "text": "delete build",
        "command": "delete build",
        "risky": True,
        "block": "before",
    },
    {
        "id": "blocked_after",
        "text": "delete build",
        "command": "delete build",
        "risky": True,
        "block": "after",
    },
    {"id": "valid_completion", "text": "fix parser", "verify": "verified"},
    {"id": "inconsistent_completion", "text": "fix parser", "verify": "unfinished", "nudge": True},
    {
        "id": "truncated_completion",
        "text": "fix parser",
        "verify": "unfinished",
        "long_final": True,
    },
]


class FakeEngine:
    """Intentionally misclassifies every user turn as high-confidence chat."""

    def __init__(self, case):
        self.case = case
        self.calls = 0

    def classify_turn(self, state):
        self.calls += 1
        return TurnDecision("chat", "trivial", 0.001, 0.001, 0.001, 0.001, 0.001, "low", 0.999)

    def assess_tool_risk(self, state):
        self.calls += 1
        p = 0.99 if self.case.get("risky") else 0.01
        return RiskDecision(0.99, p, p, p, p, p)

    def assess_completion(self, state):
        self.calls += 1
        bad = self.case.get("verify") == "unfinished"
        return CompletionDecision(
            0.99, 0.01 if bad else 0.99, 0.99 if bad else 0.01, 0.99 if bad else 0.01
        )


def run_case(case, profile):
    engine = FakeEngine(case)
    mode = "shadow" if profile == "shadow" else "enforce"
    config = Config(
        enabled=profile != "disabled",
        mode=mode,
        shaping_enabled=profile != "risk_only",
        verify_enabled=profile != "risk_only",
    )
    router = Router(config, engine, approval_order_safe=lambda: case.get("block") != "after")
    router.approval_available = lambda: True
    ids = {"session_id": "eval", "turn_id": "turn"}
    history = (
        [
            {"role": "user", "content": "fix parser"},
            {"role": "assistant", "content": "work pending"},
        ]
        if case.get("history")
        else []
    )
    request = {
        "model": "fake-main-model",
        "messages": [*history, {"role": "user", "content": case["text"]}],
        "tools": [
            {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
            for name in ("terminal", "read_file", "write_file", "clarify")
        ],
    }
    original = copy.deepcopy(request)
    start = time.perf_counter()
    if case.get("cached_task"):
        router.pre_llm_call(session_id="eval", turn_id="previous", user_message="fix parser")
        router.post_llm_call(session_id="eval", turn_id="previous")
    router.pre_llm_call(user_message=case["text"], **ids)
    shaped = router.llm_request(request=request, api_call_count=1, **ids)
    directive = None
    if case.get("command") or case.get("read_only"):
        tool = "read_file" if case.get("read_only") else "terminal"
        args = {"path": "source.py"} if case.get("read_only") else {"command": case["command"]}
        call = dict(ids, tool_name=tool, args=args, tool_call_id="call")
        router.tool_request(**call)
        directive = router.pre_tool_call(**call)
    # Simulate first-directive arbitration; real-hook tests separately check
    # the actual Hermes dispatcher on both sides of Jev's policy callback.
    action = directive.get("action") if directive else None
    if case.get("block") == "before" or (case.get("block") == "after" and not action):
        action = "block"
    verify = None
    if case.get("verify"):
        final = "done " * 900 if case.get("long_final") else "Implementation complete"
        verify = router.pre_verify(changed_paths=["source.py"], final_response=final, **ids)
    elapsed = (time.perf_counter() - start) * 1000
    assert request == original, "in-place provider mutation"
    events = router.telemetry.snapshot()["recent"]
    result = {
        "case": case["id"],
        "profile": profile,
        "removed_tools": len(request["tools"]) - len(shaped["request"]["tools"]) if shaped else 0,
        "approval": action == "approve",
        "block": action == "block",
        "nudge": bool(verify),
        "engine_calls": engine.calls,
        "wall_ms": round(elapsed, 4),
        "decision_ms": round(sum(x.get("latency_ms", 0) for x in events), 4),
    }
    router.on_session_end(session_id="eval")
    return result


def evaluate():
    profiles = ("disabled", "shadow", "risk_only", "enforce")
    rows = [run_case(case, profile) for case in CASES for profile in profiles]
    baseline = {x["case"]: x for x in rows if x["profile"] == "disabled"}
    expected = {case["id"]: case for case in CASES}
    summaries = {}
    for profile in profiles:
        selected = [x for x in rows if x["profile"] == profile]
        counts = {
            k: 0
            for k in (
                "false_tool_removals",
                "unnecessary_approvals",
                "missed_approvals",
                "incorrect_verification_nudges",
                "missed_verification_nudges",
                "lost_blocks",
                "behavior_differences_vs_disabled",
            )
        }
        for row in selected:
            case = expected[row["case"]]
            active = profile in ("risk_only", "enforce")
            expected_approval = bool(active and case.get("approve"))
            expected_nudge = bool(profile == "enforce" and case.get("nudge"))
            counts["false_tool_removals"] += bool(
                row["removed_tools"] and not (profile == "enforce" and case.get("shape"))
            )
            counts["unnecessary_approvals"] += bool(row["approval"] and not expected_approval)
            counts["missed_approvals"] += bool(expected_approval and not row["approval"])
            counts["incorrect_verification_nudges"] += bool(row["nudge"] and not expected_nudge)
            counts["missed_verification_nudges"] += bool(expected_nudge and not row["nudge"])
            counts["lost_blocks"] += bool(case.get("block") and not row["block"])
            counts["behavior_differences_vs_disabled"] += any(
                row[k] != baseline[row["case"]][k]
                for k in ("removed_tools", "approval", "block", "nudge")
            )
        summaries[profile] = dict(
            counts,
            cases=len(selected),
            engine_calls=sum(x["engine_calls"] for x in selected),
            median_wall_ms=round(statistics.median(x["wall_ms"] for x in selected), 4),
            max_wall_ms=max(x["wall_ms"] for x in selected),
            median_delta_vs_disabled_ms=round(
                statistics.median(x["wall_ms"] - baseline[x["case"]]["wall_ms"] for x in selected),
                4,
            ),
        )
    return {
        "scope": "offline fake-engine regression; NOT Jev accuracy or API performance",
        "case_count": len(CASES),
        "run_count": len(rows),
        "summary": summaries,
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    errors = (
        "false_tool_removals",
        "unnecessary_approvals",
        "missed_approvals",
        "incorrect_verification_nudges",
        "missed_verification_nudges",
        "lost_blocks",
    )
    return int(
        any(summary[k] for summary in report["summary"].values() for k in errors)
        or report["summary"]["shadow"]["behavior_differences_vs_disabled"] != 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
