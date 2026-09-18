"""Plugin-local settings; invalid configuration disables only this plugin."""

import math
from dataclasses import dataclass

READ_ONLY = frozenset(
    {
        "read_file",
        "search_files",
        "web_search",
        "web_extract",
        "web_search_plus",
        "web_extract_plus",
        "session_search",
        "skills_list",
        "skill_view",
        "tool_search",
        "tool_describe",
    }
)


@dataclass(frozen=True)
class Config:
    enabled: bool = True
    classifier_enabled: bool = True
    mode: str = "shadow"
    shaping_enabled: bool = False
    min_confidence: float = 0.95
    risk_enabled: bool = True
    block_unbindable: bool = False
    approval_threshold: float = 0.8
    verify_enabled: bool = False
    continue_threshold: float = 0.85
    max_verify_nudges: int = 2
    telemetry_enabled: bool = True
    timeout_seconds: float = 2.0
    max_workers: int = 4
    cache_size: int = 256
    cache_ttl_seconds: float = 1800.0
    state_max_bytes: int = 8000
    telemetry_size: int = 128
    read_only_tools: tuple[str, ...] = tuple(sorted(READ_ONLY))
    model: str = "jev-latest"

    def __post_init__(self):
        if self.mode not in ("shadow", "enforce"):
            raise ValueError("Expected shadow or enforce mode")
        for key in (
            "enabled",
            "classifier_enabled",
            "shaping_enabled",
            "risk_enabled",
            "block_unbindable",
            "verify_enabled",
            "telemetry_enabled",
        ):
            if type(getattr(self, key)) is not bool:
                raise ValueError("Expected boolean setting")
        ranges = {
            "min_confidence": (0.95, 1),
            "approval_threshold": (0.5, 1),
            "continue_threshold": (0.5, 1),
            "timeout_seconds": (0.01, 10),
            "cache_ttl_seconds": (0.01, 86400),
            "cache_size": (1, 4096),
            "max_workers": (1, 16),
            "state_max_bytes": (512, 16000),
            "telemetry_size": (1, 1024),
            "max_verify_nudges": (0, 3),
        }
        for key, (lo, hi) in ranges.items():
            value = getattr(self, key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not lo <= value <= hi
            ):
                raise ValueError("Out-of-range setting")
        for key in (
            "cache_size",
            "max_workers",
            "state_max_bytes",
            "telemetry_size",
            "max_verify_nudges",
        ):
            if type(getattr(self, key)) is not int:
                raise ValueError("Expected integer setting")
        if not isinstance(self.read_only_tools, (tuple, list)) or not all(
            isinstance(x, str) for x in self.read_only_tools
        ):
            raise ValueError("Invalid read-only tools")
        if not isinstance(self.model, str) or not self.model or len(self.model) > 100:
            raise ValueError("Invalid model")

    @classmethod
    def from_context(cls, ctx):
        defaults = cls()
        paths = {
            "enabled": "enabled",
            "mode": "mode",
            "classifier_enabled": "turn_classifier.enabled",
            "shaping_enabled": "tool_shaping.enabled",
            "min_confidence": "tool_shaping.min_confidence",
            "risk_enabled": "risk_gate.enabled",
            "block_unbindable": "risk_gate.block_unbindable",
            "approval_threshold": "risk_gate.approval_threshold",
            "read_only_tools": "risk_gate.read_only_tools",
            "verify_enabled": "verify.enabled",
            "continue_threshold": "verify.continue_threshold",
            "max_verify_nudges": "verify.max_nudges",
            "telemetry_enabled": "telemetry.enabled",
            "telemetry_size": "telemetry.max_events",
            "timeout_seconds": "timeout_seconds",
            "max_workers": "max_workers",
            "model": "decision_model",
            "cache_size": "cache.max_turns",
            "cache_ttl_seconds": "cache.ttl_seconds",
            "state_max_bytes": "state_max_bytes",
        }
        return cls(
            **{
                field: ctx.get_config(path, getattr(defaults, field))
                for field, path in paths.items()
            }
        )
