"""Sliding-window failure counter for login/signup throttling (PLR-9a, plan §3).

In-memory and per process (one uvicorn process on purpose). A window that simply
slides forward means no key is ever locked out indefinitely.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class FailureLimiter:
    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        events = self._events[key]
        while events and events[0] <= now - self._window:
            events.popleft()
        if not events:
            self._events.pop(key, None)
        return events

    def retry_after(self, *keys: str) -> float:
        """Seconds until the longest-blocked key frees up; 0 when none is over budget."""
        with self._lock:
            now = self._clock()
            wait = 0.0
            for key in keys:
                events = self._prune(key, now)
                if len(events) >= self._limit:
                    wait = max(wait, events[0] + self._window - now)
            return wait

    def record(self, *keys: str) -> None:
        with self._lock:
            now = self._clock()
            for key in keys:
                self._prune(key, now)
                self._events[key].append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
