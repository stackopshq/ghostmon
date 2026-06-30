"""Per-IP rate limiting on abuse-prone endpoints."""

from __future__ import annotations

import httpx

from app.api.ratelimit import RateLimiter


def test_rate_limiter_sliding_window() -> None:
    limiter = RateLimiter()
    assert all(limiter.allow("k", limit=3, window=60) for _ in range(3))
    assert limiter.allow("k", limit=3, window=60) is False  # 4th over the limit
    assert limiter.allow("other", limit=3, window=60) is True  # independent key


async def test_login_is_rate_limited(client: httpx.AsyncClient) -> None:
    # Default login limit is 10/min; the 11th attempt from the same IP is blocked.
    last = None
    for _ in range(11):
        last = await client.post(
            "/api/auth/login",
            data={"username": "nobody@example.com", "password": "wrong-pass-12"},
        )
    assert last is not None
    assert last.status_code == 429
    assert last.headers.get("retry-after") == "60"
