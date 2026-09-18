"""Metadata-only bounded telemetry. No request/result/error text is retained."""

import logging
import threading
from collections import Counter, deque

log = logging.getLogger("hermes.plugins.jev_router")
ALLOWED = frozenset(
    {
        "kind",
        "latency_ms",
        "confidence",
        "intent",
        "tools_before",
        "tools_after",
        "approval",
        "nudge",
        "fallback",
        "error",
        "shaped",
        "risk",
        "error_type",
        "model",
        "input_tokens",
        "output_tokens",
    }
)


class Telemetry:
    def __init__(self, enabled=True, size=128):
        self.enabled = enabled
        self.events = deque(maxlen=size)
        self.counts = Counter()
        self.lock = threading.Lock()

    def record(self, kind="unknown", **fields):
        fields["kind"] = kind
        if not self.enabled:
            return
        event = {
            k: v
            for k, v in fields.items()
            if k in ALLOWED and type(v) in (str, int, float, bool, type(None))
        }
        with self.lock:
            self.events.append(event)
            self.counts[event.get("kind", "unknown")] += 1
        log.info("jev_decision %s", event)

    def snapshot(self):
        with self.lock:
            return {"counts": dict(self.counts), "recent": list(self.events)}
