"""Best-effort secret minimization BEFORE truncation. Not a DLP boundary."""

import json
import os
import re
from itertools import islice

SECRET_FIELD = re.compile(
    r"api.?key|token|password|passwd|secret|authorization|cookie|credential|private.?key", re.I
)
KEY_TOKEN = re.compile(
    r"\b(?:apikey_[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]+)\b"
)
BEARER = re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9+/_.=:-]+")
ASSIGNMENT = re.compile(
    r"(?i)((?:[\w-]*(?:api[_-]?key|token|password|passwd|secret|authorization|cookie|credential)[\w-]*)[\"']?\s*[:=]\s*[\"']?)([^\s&\"'<>;,}]+)"
)
URL_AUTH = re.compile(r"(https?://)[^/@\s]+:[^/@\s]+@", re.I)
PEM = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)", re.S)


class Sanitizer:
    def __init__(self, max_bytes=8000, extra_secrets=()):
        self.max_bytes = max_bytes
        self.secrets = tuple(
            v for k, v in os.environ.items() if SECRET_FIELD.search(k) and len(v) >= 6
        ) + tuple(v for v in extra_secrets if isinstance(v, str) and v)

    def _known_secrets(self):
        # Refresh without retaining an unbounded history of rotated values.
        current = (
            v for k, v in os.environ.copy().items() if SECRET_FIELD.search(k) and len(v) >= 6
        )
        return tuple(sorted(set(self.secrets).union(current), key=len, reverse=True))

    def text(self, text, limit=1800, *, _secrets=None):
        if not isinstance(text, str):
            return "[unsupported]"
        # Reject oversized fields rather than clipping through an unredacted secret.
        if len(text) > 65536:
            return "[oversized field omitted]"
        for secret in self._known_secrets() if _secrets is None else _secrets:
            text = text.replace(secret, "[REDACTED]")
        text = PEM.sub("[PRIVATE KEY REDACTED]", text)
        text = KEY_TOKEN.sub("[REDACTED]", text)
        text = BEARER.sub("[AUTH REDACTED]", text)
        text = ASSIGNMENT.sub(r"\1[REDACTED]", text)
        text = URL_AUTH.sub(r"\1[REDACTED]@", text)
        return text[:limit]

    def prepare(self, value, *, text_limit=1800):
        """Bound decision data and expose information loss, including prior passes.

        Paths use fixed schema names or numeric positions, never arbitrary user
        keys. Metadata is inside the byte budget and cannot be cleared by another
        sanitization pass. Callers still use clean() for non-decision summaries.
        """
        meta = {
            "input_complete": True,
            "truncated": False,
            "redacted": False,
            "truncated_fields": [],
            "field_lengths": [],
        }
        secrets = self._known_secrets()
        schema = {
            "user_message",
            "platform",
            "model",
            "tool_name",
            "arguments",
            "turn_intent",
            "changed_paths",
            "final_response",
            "verification_evidence",
            "conversation",
            "evidence_freshness",
            "input_metadata",
        }

        def lost(path, original=None, processed=None, *, redacted=False):
            meta["input_complete"] = False
            meta["redacted" if redacted else "truncated"] = True
            if not redacted and path not in meta["truncated_fields"]:
                if len(meta["truncated_fields"]) < 8:
                    meta["truncated_fields"].append(path)
            if original is not None and len(meta["field_lengths"]) < 8:
                meta["field_lengths"].append(
                    {"field": path, "original_chars": original, "processed_chars": processed}
                )

        def walk(item, path="state", depth=0):
            if depth > 5:
                lost(path)
                return "[depth limit]"
            if isinstance(item, str):
                if len(item) > 65536:
                    lost(path, len(item), 0)
                    return "[oversized field omitted]"
                safe = self.text(item, 1_000_000, _secrets=secrets)
                if safe != item:
                    lost(path, redacted=True)
                if len(safe) > text_limit:
                    lost(path, len(item), min(len(safe), text_limit))
                return safe[:text_limit]
            if item is None or type(item) in (bool, int):
                return item
            if type(item) is float:
                import math

                if math.isfinite(item):
                    return item
                lost(path)
                return None
            if type(item) is dict:
                if len(item) > 32:
                    lost(path)
                out = {}
                for i, (key, val) in enumerate(islice(item.items(), 32)):
                    child = key if depth == 0 and key in schema else f"{path}.field[{i}]"
                    if not isinstance(key, str):
                        lost(child)
                        continue
                    clean_key = self.text(key, 80, _secrets=secrets)
                    if clean_key != key or clean_key in out:
                        lost(child)
                    if SECRET_FIELD.search(key):
                        lost(child, redacted=True)
                        out[clean_key] = "[REDACTED]"
                    else:
                        out[clean_key] = walk(val, child, depth + 1)
                return out
            if type(item) in (list, tuple):
                if len(item) > 16:
                    lost(path)
                return [walk(v, f"{path}[{i}]", depth + 1) for i, v in enumerate(item[:16])]
            lost(path)
            return "[unsupported]"

        data = walk(value)
        if not isinstance(data, dict):
            data = {"value": data}
        previous = data.pop("input_metadata", None)
        if isinstance(previous, dict) and previous.get("input_complete") is not True:
            # Keep first-pass details when possible; never restore completeness.
            if meta["input_complete"]:
                meta = previous
            else:
                meta["truncated"] |= previous.get("truncated") is True
                meta["redacted"] |= previous.get("redacted") is True
            meta["input_complete"] = False

        def size(item):
            return len(json.dumps(item, ensure_ascii=False).encode())

        while size(dict(data, input_metadata=meta)) > self.max_bytes:
            # Compact metadata first; always keep the completeness flags.
            meta = {
                "input_complete": False,
                "truncated": True,
                "redacted": meta.get("redacted", False),
                "truncated_fields": ["state"],
                "field_lengths": [],
            }
            if size(dict(data, input_metadata=meta)) <= self.max_bytes:
                break
            if not data:
                raise ValueError("Metadata exceeds state budget")
            biggest = max(data, key=lambda k: size(data[k]))
            if data[biggest] == "[size limit]":
                data.pop(biggest)
            else:
                data[biggest] = "[size limit]"
        return dict(data, input_metadata=meta)

    def clean(self, value):
        secrets = self._known_secrets()

        def walk(item, depth=0):
            if depth > 5:
                return "[depth limit]"
            if isinstance(item, str):
                return self.text(item, _secrets=secrets)
            if item is None or type(item) in (bool, int):
                return item
            if type(item) is float:
                import math

                return item if math.isfinite(item) else None
            if type(item) is dict:
                out = {}
                for key, val in islice(item.items(), 32):
                    if not isinstance(key, str):
                        continue
                    out[self.text(key, 80, _secrets=secrets)] = (
                        "[REDACTED]" if SECRET_FIELD.search(key) else walk(val, depth + 1)
                    )
                return out
            if type(item) in (list, tuple):
                return [walk(v, depth + 1) for v in item[:16]]
            return "[unsupported]"

        result = walk(value)
        # Preserve valid JSON and semantic field boundaries. Omit, don't cut JSON.
        while len(json.dumps(result, ensure_ascii=False).encode()) > self.max_bytes:
            if isinstance(result, dict) and result:
                biggest = max(
                    result, key=lambda k: len(json.dumps(result[k], ensure_ascii=False).encode())
                )
                if result[biggest] == "[size limit]":
                    result.pop(biggest)
                else:
                    result[biggest] = "[size limit]"
            else:
                return {"omitted": "state exceeded byte limit"}
        return result
