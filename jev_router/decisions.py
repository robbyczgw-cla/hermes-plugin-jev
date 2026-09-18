"""Immutable decisions; probabilities are semantic estimates, not permissions."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class TurnDecision:
    intent: str
    complexity: str
    needs_web: float
    needs_browser: float
    needs_terminal: float
    needs_files: float
    should_delegate: float
    side_effect_likelihood: str
    confidence: float
    model: str = ""


@dataclass(frozen=True)
class RiskDecision:
    action_requested: float
    external_side_effect: float
    destructive: float
    irreversible: float
    exposes_secrets: float
    confirmation_expected: float

    @property
    def confidence(self):
        return min(
            max(p, 1 - p)
            for p in (
                self.action_requested,
                self.external_side_effect,
                self.destructive,
                self.irreversible,
                self.exposes_secrets,
                self.confirmation_expected,
            )
        )


@dataclass(frozen=True)
class CompletionDecision:
    claims_complete: float
    verification_evidence_present: float
    inconsistent: float
    needs_iteration: float

    @property
    def confidence(self):
        return min(
            max(p, 1 - p)
            for p in (
                self.claims_complete,
                self.verification_evidence_present,
                self.inconsistent,
                self.needs_iteration,
            )
        )


class DecisionEngine(Protocol):
    def classify_turn(self, state: dict[str, Any]) -> TurnDecision: ...
    def assess_tool_risk(self, state: dict[str, Any]) -> RiskDecision: ...
    def assess_completion(self, state: dict[str, Any]) -> CompletionDecision: ...
