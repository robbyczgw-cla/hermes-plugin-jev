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
# Match a key header once, then inspect its name. A greedy prefix searching
# for a secret keyword at every character causes quadratic time on long words.
ASSIGNMENT = re.compile(r"(?<![\w-])([\w-]+)[\"']?\s*[:=]\s*[\"']?")
ASSIGNMENT_VALUE = re.compile(r"[^\s&\"'<>;,}]+")
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
        parts = []
        end = 0
        for header in ASSIGNMENT.finditer(text):
            if header.start() < end or not SECRET_FIELD.search(header.group(1)):
                continue
            value = ASSIGNMENT_VALUE.match(text, header.end())
            if value:
                parts.extend((text[end : header.end()], "[REDACTED]"))
                end = value.end()
        parts.append(text[end:])
        text = "".join(parts)
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

        # Bound aggregate preprocessing, not merely depth and each container.
        # Keys count too: nested 32-way input otherwise multiplies the work.
        budget = {"nodes": 512, "chars": 131072}

        def consume(path, chars=0):
            if budget["nodes"] <= 0 or chars > budget["chars"]:
                lost(path)
                return False
            budget["nodes"] -= 1
            budget["chars"] -= chars
            return True

        def walk(item, path="state", depth=0):
            if not consume(path, len(item) if isinstance(item, str) else 0):
                return "[work limit]"
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
                    if not consume(child, len(key)):
                        break
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
        """Summary-only view of the same bounded sanitizer, without metadata."""
        data = self.prepare(value)
        data.pop("input_metadata", None)
        return (
            data
            if isinstance(value, dict)
            else data.get("value", {"omitted": "state exceeded byte limit"})
        )
