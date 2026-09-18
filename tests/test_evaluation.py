from scripts.evaluate import CASES, evaluate


def test_deterministic_eval_matrix():
    report = evaluate()
    assert report["case_count"] == len(CASES)
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert report["run_count"] == len(CASES) * 4
    for profile, result in report["summary"].items():
        for metric in (
            "false_tool_removals",
            "unnecessary_approvals",
            "missed_approvals",
            "incorrect_verification_nudges",
            "missed_verification_nudges",
            "lost_blocks",
        ):
            assert result[metric] == 0, (profile, metric, report)
    assert report["summary"]["shadow"]["behavior_differences_vs_disabled"] == 0
    assert report["summary"]["disabled"]["engine_calls"] == 0
    assert report["summary"]["enforce"]["behavior_differences_vs_disabled"] > 0
    assert any(
        r["case"] == "fresh_chat" and r["profile"] == "enforce" and r["removed_tools"] > 0
        for r in report["rows"]
    )
