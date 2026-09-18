"""Hermes approval context and bounded, single-use semantic proposals."""

import hashlib
import json
import threading
import time
from collections import OrderedDict


def human_approval_available():
    """Use Hermes's context-local routing; unknown host APIs mean abstention."""
    try:
        from tools import approval

        if (
            approval._is_cron_approval_context()
            or approval._is_single_query_approval_context()
            or approval._is_unattended_platform_approval_context()
        ):
            return False
        return approval._is_interactive_cli() or approval._is_gateway_approval_context()
    except Exception:
        return False


def action_digest(args):
    """Bound hashing work and reject non-JSON arguments; never retain raw args."""
    if not isinstance(args, dict):
        return None
    # iterencode avoids allocating an unbounded serialized payload. The input
    # already exists in Hermes; the plugin retains only this digest.
    size = 0
    digest = hashlib.sha256()
    try:
        for chunk in json.JSONEncoder(sort_keys=True, allow_nan=False).iterencode(args):
            size += len(chunk)
            if size > 65536:
                return None
            digest.update(chunk.encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        return None
    return digest.hexdigest()


class PreparedApprovals:
    """No waits in the policy hook; a contended lock is a cache miss."""

    def __init__(self, size=256, ttl=10):
        self.size, self.ttl = size, ttl
        self.items = OrderedDict()
        self.lock = threading.Lock()

    @staticmethod
    def key(session, turn, call, tool):
        values = (session, turn, call, tool)
        return values if all(isinstance(v, str) and 0 < len(v) <= 512 for v in values) else None

    def discard(self, key):
        with self.lock:
            self.items.pop(key, None)

    def put(self, key, digest, directive):
        with self.lock:
            self.items[key] = (time.monotonic(), digest, directive)
            self.items.move_to_end(key)
            while len(self.items) > self.size:
                self.items.popitem(last=False)

    def take(self, key, digest):
        if not self.lock.acquire(blocking=False):
            return None
        try:
            item = self.items.pop(key, None)
        finally:
            self.lock.release()
        if item and time.monotonic() - item[0] <= self.ttl and item[1] == digest:
            return dict(item[2])
        return None

    def end(self, session):
        with self.lock:
            for key in list(self.items):
                if key[0] == session:
                    del self.items[key]
