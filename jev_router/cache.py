"""Bounded turn cache. Lock is never held across network calls."""

import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Turn:
    session_id: str
    turn_id: str
    state: dict
    created: float
    decision: Any = None
    ready: threading.Event = field(default_factory=threading.Event)
    evidence: deque = field(default_factory=lambda: deque(maxlen=8))
    tools_started: bool = False
    verify_attempts: set = field(default_factory=set)
    completed: bool = False
    generation: int = 0
    lock: Any = field(default_factory=threading.RLock, repr=False)


class TurnCache:
    def __init__(self, size=256, ttl=1800):
        self.size = size
        self.ttl = ttl
        self._items = OrderedDict()
        self.lock = threading.RLock()

    def _prune(self):
        now = time.monotonic()
        for k, v in list(self._items.items()):
            if now - v.created > self.ttl:
                del self._items[k]

    def reserve(self, session, turn, state):
        with self.lock:
            self._prune()
            key = (session, turn)
            if key in self._items:
                return self._items[key], False
            # Do not evict active/in-flight turns to make room: avoid duplicate calls.
            prior = [v for v in self._items.values() if v.session_id == session]
            if len(self._items) >= self.size:
                finished = next(
                    (k for k, v in self._items.items() if v.completed and v.ready.is_set()), None
                )
                if finished is None:
                    return None, False
                del self._items[finished]
            state = dict(
                state,
                conversation={
                    "prior_turn_seen": bool(prior) or state.get("host_first_turn") is False,
                    "unresolved_task": any(not v.completed for v in prior),
                    "ongoing_tool_workflow": any(v.tools_started for v in prior),
                },
            )
            entry = Turn(session, turn, state, time.monotonic())
            self._items[key] = entry
            return entry, True

    def get(self, session, turn=None):
        if not session:
            return None
        with self.lock:
            self._prune()
            if turn:
                return self._items.get((session, turn))
            choices = [
                v for v in self._items.values() if v.session_id == session and not v.completed
            ]
            return choices[0] if len(choices) == 1 else None

    def end(self, session, turn=None):
        with self.lock:
            for key in list(self._items):
                if key[0] == session and (not turn or key[1] == turn):
                    del self._items[key]

    def __len__(self):
        with self.lock:
            self._prune()
            return len(self._items)
