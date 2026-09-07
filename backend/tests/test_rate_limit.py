"""Unit tests for the standalone rate-limiting primitive (Phase 15).
Endpoint-level behavior (per-user isolation through the real dependency,
the 429 envelope, GET being unaffected) is covered in test_interview.py
alongside the rest of that endpoint's tests; this file covers the
FixedWindowRateLimiter class itself in isolation.
"""
from app.core.rate_limit import FixedWindowRateLimiter


def test_allows_up_to_max_requests_then_rejects():
    limiter = FixedWindowRateLimiter(max_requests=3, window_seconds=60)

    for _ in range(3):
        allowed, retry_after = limiter.check("user-1")
        assert allowed is True
        assert retry_after == 0

    allowed, retry_after = limiter.check("user-1")
    assert allowed is False
    assert retry_after > 0


def test_rejected_check_does_not_increment_the_counter():
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=60)
    limiter.check("user-1")

    first_rejection = limiter.check("user-1")
    second_rejection = limiter.check("user-1")

    assert first_rejection[0] is False
    assert second_rejection[0] is False
    # retry_after shouldn't grow across rejections within the same window —
    # a rejected call must not push the caller's own reset time further out.
    assert second_rejection[1] <= first_rejection[1]


def test_keys_are_independent():
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=60)

    assert limiter.check("user-1")[0] is True
    assert limiter.check("user-1")[0] is False
    # A different key has never been seen before — its own fresh window.
    assert limiter.check("user-2")[0] is True


def test_window_resets_after_window_seconds_elapse(monkeypatch):
    import app.core.rate_limit as rate_limit_module

    fake_now = {"t": 1000.0}
    monkeypatch.setattr(rate_limit_module.time, "monotonic", lambda: fake_now["t"])

    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=10)
    assert limiter.check("user-1")[0] is True
    assert limiter.check("user-1")[0] is False

    fake_now["t"] += 10.0  # exactly one window later
    assert limiter.check("user-1")[0] is True


def test_reset_clears_all_keys():
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=60)
    limiter.check("user-1")
    assert limiter.check("user-1")[0] is False

    limiter.reset()

    assert limiter.check("user-1")[0] is True
