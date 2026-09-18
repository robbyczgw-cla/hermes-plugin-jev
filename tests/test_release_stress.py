"""Bounded adversarial release probes. All engines and actions are synthetic."""

import copy
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_input_safety import request
from test_runtime import Engine, setup, start

from jev_router.decisions import CompletionDecision, RiskDecision
from jev_router.privacy import Sanitizer
from jev_router.runner import BoundedRunner, CapacityExceeded, DecisionTimeout


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_seeded_multiturn_session_isolation(mode):
    r, e = setup(mode=mode, cache_size=16)
    rng = random.Random(731)
    followups = ["yes, do it", "continue", "fix that", "ja weiter", "run the tests too", "hello"]
    for i in range(100):
        sid = f"synthetic-{i}"
        start(r, s=sid, t="first", text="Implement parser and run checks")
        r.post_llm_call(session_id=sid, turn_id="first")
        message = rng.choice(followups)
        start(r, s=sid, t="second", text=message)
        original = request(message)
        before = copy.deepcopy(original)
        assert (
            r.llm_request(request=original, session_id=sid, turn_id="second", api_call_count=1)
            is None
        )
        assert original == before
        r.on_session_end(session_id=sid)
        assert len(r.cache) == 0
    assert e.turn_calls == 200


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_parallel_risk_proposals_are_exact_and_single_use(mode):
    r, e = setup(mode=mode, max_workers=16, cache_size=128)
    e.risk = RiskDecision(0.99, 0.99, 0.99, 0.99, 0.01, 0.99)
    start(r, text="Delete synthetic build outputs")

    def exercise(i):
        kw = dict(
            session_id="s",
            turn_id="t",
            tool_call_id=f"call-{i}",
            tool_name="terminal",
            args={"command": f"remove synthetic-output-{i}"},
        )
        r.tool_request(**kw)
        first = r.pre_tool_call(**kw)
        assert (first is not None) == (mode == "enforce")
        if first:
            assert first["action"] == "approve"
            assert f"synthetic-output-{i}" in first["message"]
        assert r.pre_tool_call(**kw) is None

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(exercise, range(128)))
    assert e.risk_calls == 128
    assert not r.prepared.items


def test_worker_saturation_and_recovery_have_no_queue():
    runner = BoundedRunner(2)
    release = threading.Event()
    entered = threading.Barrier(3)

    def work():
        entered.wait(timeout=2)
        release.wait(timeout=2)
        return "late"

    def caller():
        with pytest.raises(DecisionTimeout):
            runner.run(work, 0.01)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(caller) for _ in range(2)]
        entered.wait(timeout=2)
        for future in futures:
            future.result()
        try:
            for _ in range(100):
                with pytest.raises(CapacityExceeded):
                    runner.run(lambda: pytest.fail("must not be queued"), 0.01)
        finally:
            release.set()
    # Acquire both released slots to synchronize, without timing-dependent sleeps.
    assert runner.slots.acquire(timeout=2)
    assert runner.slots.acquire(timeout=2)
    runner.slots.release()
    runner.slots.release()
    assert runner.run(lambda: "recovered", 1) == "recovered"


@pytest.mark.parametrize("fault", [ValueError, TimeoutError, ConnectionError])
@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_backend_faults_never_remove_tools_or_grant_execution(fault, mode, caplog):
    e = Engine()

    def broken(state):
        raise fault("SYNTHETIC_PRIVATE_ERROR")

    e.classify_turn = e.assess_tool_risk = e.assess_completion = broken
    r, _ = setup(e, mode=mode)
    start(r, text="continue")
    assert (
        r.llm_request(request=request("continue"), session_id="s", turn_id="t", api_call_count=1)
        is None
    )
    kw = dict(
        session_id="s",
        turn_id="t",
        tool_call_id="call",
        tool_name="terminal",
        args={"command": "remove synthetic build"},
    )
    r.tool_request(**kw)
    directive = r.pre_tool_call(**kw)
    assert directive is None if mode == "shadow" else directive["action"] == "approve"
    assert (
        r.pre_verify(
            session_id="s", turn_id="t", changed_paths=["parser.py"], final_response="done"
        )
        is None
    )
    assert "SYNTHETIC_PRIVATE_ERROR" not in caplog.text
    assert "SYNTHETIC_PRIVATE_ERROR" not in json.dumps(r.status())


@pytest.mark.parametrize("seed", range(8))
def test_seeded_privacy_budget_and_monotonic_incompleteness(seed, monkeypatch):
    rng = random.Random(seed)
    secret = f"synthetic-only-secret-{seed}-987654321"
    monkeypatch.setenv("TEST_SERVICE_TOKEN", secret)
    for _ in range(64):
        sanitizer = Sanitizer(rng.choice([512, 800, 2000, 8000]))
        text = rng.choice(["漢", "🙂", "x", " "]) * rng.randrange(0, 2400)
        value = {
            "user_message": text,
            "arguments": {"command": "echo " + secret, "nested": list(range(rng.randrange(0, 35)))},
        }
        output = sanitizer.prepare(value)
        for _ in range(3):
            encoded = json.dumps(output, ensure_ascii=False).encode()
            assert len(encoded) <= sanitizer.max_bytes
            assert secret.encode() not in encoded
            assert output["input_metadata"]["input_complete"] is False
            output = sanitizer.prepare(output)


def test_sanitizer_has_global_work_budget(monkeypatch):
    sanitizer = Sanitizer()
    text = sanitizer.text
    calls = []

    def counted(value, *args, **kwargs):
        calls.append(1)
        return text(value, *args, **kwargs)

    monkeypatch.setattr(sanitizer, "text", counted)
    branch = {f"field-{i}": "harmless" * 20 for i in range(16)}
    tree = {f"group-{i}": {f"part-{j}": branch for j in range(16)} for i in range(16)}
    output = sanitizer.prepare({"arguments": tree})
    assert len(calls) <= 1024, "per-container limits do not bound total preprocessing work"
    assert output["input_metadata"]["input_complete"] is False


@pytest.mark.parametrize("ended", ["turn", "session"])
def test_inflight_verify_cannot_nudge_after_lifecycle_end(ended):
    r, e = setup()
    start(r, text="Implement parser")

    def finish_during_decision(state):
        if ended == "turn":
            r.post_llm_call(session_id="s", turn_id="t")
        else:
            r.on_session_end(session_id="s")
        return CompletionDecision(0.99, 0.01, 0.99, 0.99)

    e.assess_completion = finish_during_decision
    assert (
        r.pre_verify(
            session_id="s", turn_id="t", changed_paths=["parser.py"], final_response="done"
        )
        is None
    )
