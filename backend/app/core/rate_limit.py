"""In-memory, per-process rate limiting.

Rules.md 3.5 forbids Redis/Celery/a queue in v1 — this is a single
fixed-window counter per key, held in a plain dict behind a lock. That's
enough for a single-instance deployment (Architecture.md 10: one uvicorn
process) and needs no new dependency. If the app ever runs multiple
worker processes, this stops being correct (each process would keep its
own counters) and would need to move to a shared store — not needed for
v1's deployment topology.

Pure and framework-agnostic on purpose (no FastAPI imports), matching
core/security.py's shape: callers in dependencies.py decide what to do
with a rejected check.
"""
import threading
import time
from dataclasses import dataclass


@dataclass
class _Window:
    started_at: float
    count: int


class FixedWindowRateLimiter:
    """Allows at most `max_requests` calls to `check()` for a given key per
    `window_seconds`. A key with no activity for a full window resets to a
    fresh window on its next call, rather than requiring a background
    sweep — the dict only ever holds one entry per key that has been seen
    at all, which is bounded by the number of distinct users, not by
    request volume.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, _Window] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds). A rejected call does not
        increment the counter, so a caller hammering the endpoint past
        their limit doesn't push their own reset time further out.
        """
        now = time.monotonic()
        with self._lock:
            window = self._windows.get(key)
            if window is None or now - window.started_at >= self.window_seconds:
                self._windows[key] = _Window(started_at=now, count=1)
                return True, 0
            if window.count < self.max_requests:
                window.count += 1
                return True, 0
            retry_after = max(1, int(self.window_seconds - (now - window.started_at)) + 1)
            return False, retry_after

    def reset(self) -> None:
        """Test-only: clears all counters so tests don't leak state into
        each other via this module-level singleton.
        """
        with self._lock:
            self._windows.clear()
