"""Fail-open semantic signals; never an authorization or execution layer."""

from __future__ import annotations

import functools
import json
import re
import time
from uuid import uuid4

from .cache import TurnCache
from .decisions import CompletionDecision, RiskDecision, TurnDecision
from .middleware import shape_tools
from .privacy import Sanitizer
from .runner import BoundedRunner
from .telemetry import Telemetry

VERIFY_COMMAND = re.compile(
    r"^\s*(?:(?:python[\d.]*|uv run python)\s+-m\s+pytest|pytest|npm\s+(?:test|run\s+(?:test|lint|build|typecheck))|pnpm\s+(?:test|lint|build|typecheck)|cargo\s+(?:test|check|build|clippy)|ruff\s+check|mypy|tsc|python[\d.]*\s+-m\s+(?:compileall|unittest))(?=\s|$)"
)
MUTATIONS = frozenset(
    {"write_file", "patch", "edit_file", "apply_patch", "terminal", "execute_code"}
)


def guarded(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:
            self.telemetry.record(method.__name__, fallback=True, error=type(exc).__name__)
            return None

    return wrapper


class Router:
    def __init__(self, config, engine, *, api_key="", approval_order_safe=None):
        self.config, self.engine = config, engine
        self.api_key_configured = bool(api_key)
        self.privacy = Sanitizer(max_bytes=config.state_max_bytes, extra_secrets=(api_key,))
        self.cache = TurnCache(config.cache_size, config.cache_ttl_seconds)
        self.telemetry = Telemetry(config.telemetry_enabled, config.telemetry_size)
        if engine is not None and hasattr(engine, "telemetry"):
            engine.telemetry = self.telemetry
        self.runner = BoundedRunner(config.max_workers)
        self.approval_order_safe = approval_order_safe or (lambda: False)

    @property
    def active(self):
        return self.config.enabled and self.engine is not None

    def _call(self, kind, method, state, expected):
        started = time.monotonic()
        try:
            value = self.runner.run(
                lambda: method(self.privacy.clean(state)), self.config.timeout_seconds
            )
            if not isinstance(value, expected):
                raise ValueError("Unexpected decision type")
            from .client import _prob

            for name in expected.__dataclass_fields__:
                item = getattr(value, name)
                if isinstance(item, (float, int)):
                    _prob(item)
            self.telemetry.record(
                kind,
                latency_ms=round((time.monotonic() - started) * 1000, 2),
                confidence=value.confidence,
                **({"intent": value.intent} if isinstance(value, TurnDecision) else {}),
            )
            return value
        except Exception as exc:
            self.telemetry.record(
                kind,
                latency_ms=round((time.monotonic() - started) * 1000, 2),
                fallback=True,
                error=type(exc).__name__,
            )
            return None

    @guarded
    def pre_llm_call(
        self,
        *,
        session_id=None,
        turn_id=None,
        task_id=None,
        user_message="",
        platform="",
        model="",
        **kwargs,
    ):
        if not self.active or not isinstance(session_id, str) or not session_id:
            return
        # Modern Hermes supplies turn_id. Legacy hooks run once per turn: create
        # a turn-local ID, never key decisions only by text or session ID.
        turn_id = turn_id if isinstance(turn_id, str) and turn_id else "local-" + uuid4().hex
        user = self.privacy.text(user_message, 4000)
        entry, owner = self.cache.reserve(
            session_id,
            turn_id,
            {
                "user_message": user,
                "platform": self.privacy.text(platform, 80),
                "model": self.privacy.text(model, 120),
            },
        )
        if entry is None:
            return
        if not owner:
            entry.ready.wait(self.config.timeout_seconds)
            return
        try:
            if self.config.classifier_enabled:
                entry.decision = self._call(
                    "turn",
                    self.engine.classify_turn,
                    {
                        "user_message": user,
                        "platform": entry.state["platform"],
                        "model": entry.state["model"],
                    },
                    TurnDecision,
                )
        finally:
            entry.ready.set()

    @guarded
    def llm_request(
        self, *, request=None, session_id=None, turn_id=None, api_call_count=None, **kwargs
    ):
        if not self.active or not self.config.shaping_enabled or api_call_count != 1:
            return None
        with self.cache.lock:
            entry = self.cache.get(session_id, turn_id)
            decision = (
                entry.decision
                if entry and entry.ready.is_set() and not entry.tools_started
                else None
            )
        changed = shape_tools(request, decision, self.config.min_confidence)
        if changed is not None:
            self.telemetry.record(
                "shaping",
                shaped=True,
                tools_before=len(request["tools"]),
                tools_after=len(changed["tools"]),
            )
            return {
                "request": changed,
                "source": "jev-router",
                "reason": "high-confidence simple chat; first provider request only",
            }
        self.telemetry.record("shaping", shaped=False)
        return None

    @guarded
    def pre_tool_call(
        self, *, tool_name="", args=None, session_id=None, turn_id=None, platform="", **kwargs
    ):
        if not self.active:
            return None
        entry = self.cache.get(session_id, turn_id)
        if not entry:
            return None
        with self.cache.lock:
            entry.tools_started = True
        if not self.config.risk_enabled or tool_name in self.config.read_only_tools:
            return None
        state = {
            "user_message": entry.state["user_message"],
            "tool_name": tool_name,
            "arguments": args,
            "platform": entry.state["platform"],
            "turn_intent": entry.decision.intent if entry.decision else "unknown",
        }
        risk = self._call("risk", self.engine.assess_tool_risk, state, RiskDecision)
        if risk is None:
            return None
        threshold = self.config.approval_threshold
        meaningful = (
            max(
                risk.external_side_effect,
                risk.destructive,
                risk.irreversible,
                risk.exposes_secrets,
                risk.confirmation_expected,
            )
            >= threshold
        )
        uncertain = risk.confidence < 0.65 or risk.action_requested < 1 - threshold
        needs_approval = meaningful or uncertain
        # Hermes resolves FIRST block/approve. Only append semantic approval at
        # the end of the current public registry, preserving earlier policies.
        safe = bool(self.approval_order_safe()) if needs_approval else True
        self.telemetry.record(
            "risk_result",
            risk="approval" if needs_approval else "low",
            approval=needs_approval and safe,
            fallback=needs_approval and not safe,
        )
        if needs_approval and safe:
            return {
                "action": "approve",
                "message": "TypeSafe semantic signal: this action may need human confirmation. Existing Hermes policies still apply.",
            }
        return None

    @guarded
    def post_tool_call(
        self,
        *,
        tool_name="",
        args=None,
        result=None,
        session_id=None,
        turn_id=None,
        status=None,
        **kwargs,
    ):
        if not self.active or not self.config.verify_enabled:
            return None
        entry = self.cache.get(session_id, turn_id)
        if not entry:
            return None
        args = args if isinstance(args, dict) else {}
        command = args.get("command", "")
        if isinstance(result, str):
            try:
                result = json.loads(result) if len(result) <= 100_000 else None
            except (ValueError, TypeError):
                result = None
        result = result if isinstance(result, dict) else {}
        is_verify = (
            tool_name == "terminal"
            and isinstance(command, str)
            and len(command) < 4000
            and VERIFY_COMMAND.match(command)
        )
        # Shell control operators can hide the real test exit status (pytest;
        # true), so such commands are not accepted as positive test evidence.
        if is_verify and any(token in command for token in (";", "||", "&&", "|", "`", "$(", "\n")):
            is_verify = False
        with self.cache.lock:
            entry.tools_started = True
            if is_verify:
                exit_code = result.get("exit_code")
                success = exit_code == 0 if type(exit_code) is int else None
                entry.evidence.append(
                    {
                        "tool": "terminal",
                        "command": self.privacy.text(command, 240),
                        "success": success,
                        "summary": self.privacy.text(result.get("output", ""), 400),
                        "generation": entry.generation,
                    }
                )
            elif tool_name in MUTATIONS or tool_name not in self.config.read_only_tools:
                entry.generation += 1
                entry.evidence.clear()
        return None

    @guarded
    def pre_verify(
        self,
        *,
        session_id=None,
        turn_id=None,
        coding=False,
        changed_paths=None,
        final_response="",
        attempt=0,
        **kwargs,
    ):
        if not self.active or not self.config.verify_enabled or not changed_paths:
            return None
        if type(attempt) is not int or attempt < 0 or attempt >= self.config.max_verify_nudges:
            return None
        entry = self.cache.get(session_id, turn_id)
        if not entry:
            return None
        with self.cache.lock:
            if attempt in entry.verify_attempts:
                return None
            entry.verify_attempts.add(attempt)
            evidence = [dict(e) for e in entry.evidence if e["generation"] == entry.generation]
        state = {
            "user_message": entry.state["user_message"],
            "turn_intent": entry.decision.intent if entry.decision else "unknown",
            "changed_paths": changed_paths,
            "final_response": final_response,
            "verification_evidence": evidence,
        }
        decision = self._call(
            "completion", self.engine.assess_completion, state, CompletionDecision
        )
        if decision is None:
            return None
        threshold = self.config.continue_threshold
        has_success = any(e["success"] is True for e in evidence)
        has_failure = any(e["success"] is False for e in evidence)
        observed_problem = has_failure or not has_success
        nudge = (
            observed_problem
            and decision.confidence >= threshold
            and decision.claims_complete >= threshold
            and decision.inconsistent >= threshold
            and decision.needs_iteration >= threshold
        )
        self.telemetry.record("verification", nudge=nudge)
        if nudge:
            return {
                "action": "continue",
                "message": "Review the completion claim against the changed files and current verification evidence. Run relevant checks or report the remaining blocker honestly; do not claim success without evidence.",
            }
        return None

    @guarded
    def post_llm_call(self, *, session_id=None, turn_id=None, **kwargs):
        with self.cache.lock:
            entry = self.cache.get(session_id, turn_id)
            if entry:
                entry.completed = True

    @guarded
    def on_session_end(self, *, session_id=None, **kwargs):
        self.cache.end(session_id)

    def status(self):
        return {
            "enabled": self.config.enabled,
            "active": self.active,
            "api_key_configured": self.api_key_configured,
            "turn_classifier": self.config.classifier_enabled,
            "tool_shaping": self.config.shaping_enabled,
            "risk_gate": self.config.risk_enabled,
            "verify": self.config.verify_enabled,
            "model": self.config.model,
            "telemetry_scope": "current process only",
            "telemetry": self.telemetry.snapshot(),
        }
