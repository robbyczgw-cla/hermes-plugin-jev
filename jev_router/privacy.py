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

    def text(self, text, limit=1800):
        if not isinstance(text, str):
            return "[unsupported]"
        # Reject oversized fields rather than clipping through an unredacted secret.
        if len(text) > 65536:
            return "[oversized field omitted]"
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        text = PEM.sub("[PRIVATE KEY REDACTED]", text)
        text = KEY_TOKEN.sub("[REDACTED]", text)
        text = BEARER.sub("[AUTH REDACTED]", text)
        text = ASSIGNMENT.sub(r"\1[REDACTED]", text)
        text = URL_AUTH.sub(r"\1[REDACTED]@", text)
        return text[:limit]

    def clean(self, value):
        def walk(item, depth=0):
            if depth > 5:
                return "[depth limit]"
            if isinstance(item, str):
                return self.text(item)
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
                    out[self.text(key, 80)] = (
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
