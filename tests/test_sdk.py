"""Use the installed official SDK and a fake HTTP transport; never a real key."""

import json
import logging

import httpx2
import pytest
import typesafe_sdk

from jev_router.client import TypeSafeEngine
from jev_router.config import Config
from jev_router.telemetry import Telemetry


def engine_and_wire(monkeypatch, *, status=200, bad=None):
    requests = []
    real = typesafe_sdk.TypeSafeClient

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        answers = {}
        for name, question in body["questions"].items():
            if question["type"] == "choice":
                choice = next(iter(question["criteria"]))
                answers[name] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.99,
                    "probabilities": {choice: 0.99},
                }
            else:
                answers[name] = {"type": "noul", "noul": 0.01}
        if bad == "missing":
            answers.pop(next(iter(answers)))
        elif bad == "probability":
            for value in answers.values():
                if value["type"] == "noul":
                    value["noul"] = 1.2
        elif bad == "choice":
            answers["intent"]["choice"] = "bogus"
        return httpx2.Response(
            status,
            json={
                "model": "jev-test",
                "usage": {"input_tokens": 80, "output_tokens": 10},
                "answers": answers,
            },
        )

    monkeypatch.setattr(
        typesafe_sdk,
        "TypeSafeClient",
        lambda **kw: real(transport=httpx2.MockTransport(handler), **kw),
    )
    telemetry = Telemetry()
    return (
        TypeSafeEngine("mock-key-not-a-credential", Config(), telemetry=telemetry),
        requests,
        telemetry,
    )


def test_official_sdk_bundles_turn_questions(monkeypatch):
    engine, requests, telemetry = engine_and_wire(monkeypatch)
    decision = engine.classify_turn({"user_message": "hello"})
    assert decision.intent == "chat"
    assert decision.needs_web == 0.01
    assert len(requests) == 1
    assert len(requests[0]["questions"]) == 8
    assert sum(q["type"] == "choice" for q in requests[0]["questions"].values()) == 3
    assert telemetry.snapshot()["recent"][0]["model"] == "jev-test"


@pytest.mark.parametrize("method,count", [("assess_tool_risk", 6), ("assess_completion", 4)])
def test_official_sdk_nouls(monkeypatch, method, count):
    engine, requests, _ = engine_and_wire(monkeypatch)
    result = getattr(engine, method)({"user_message": "hello"})
    assert result is not None
    assert len(requests) == 1
    assert len(requests[0]["questions"]) == count


@pytest.mark.parametrize("bad", ["missing", "probability", "choice"])
def test_malformed_answers_rejected(monkeypatch, bad):
    engine, _, _ = engine_and_wire(monkeypatch, bad=bad)
    with pytest.raises((ValueError, KeyError)):
        engine.classify_turn({"user_message": "hello"})


def test_no_sdk_retries(monkeypatch):
    engine, requests, _ = engine_and_wire(monkeypatch, status=429)
    with pytest.raises(Exception):
        engine.classify_turn({"user_message": "hello"})
    assert len(requests) == 1


def test_redacts_sdk_wire_and_suppresses_debug(monkeypatch, caplog):
    engine, requests, _ = engine_and_wire(monkeypatch)
    private_text = "PRIVATE_CONVERSATION_SHOULD_NOT_APPEAR_IN_LOGS"
    with caplog.at_level(logging.DEBUG):
        engine.classify_turn(
            {
                "user_message": private_text + " mock-key-not-a-credential",
                "args": {"password": "private-password"},
            }
        )
        logging.getLogger("typesafe_sdk").debug("other SDK caller remains visible")
    wire = json.dumps(requests)
    assert "mock-key-not-a-credential" not in wire
    assert "private-password" not in wire
    assert private_text not in caplog.text
    assert "other SDK caller remains visible" in caplog.text
