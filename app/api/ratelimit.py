"""In-memory sliding-window rate limiting for abuse-prone endpoints (login,
ingest). Per-process — fine for a single self-hosted instance; a multi-instance
deployment would need a shared store (Redis), out of scope here. 0 disables a limit.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_settings

_LOGIN_PATHS = frozenset({"/api/auth/login", "/login"})
_INGEST_PATH = "/api/ingest"
_WINDOW_SECONDS = 60.0


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._calls = 0

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        cutoff = now - window
        bucket = self._hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        # Opportunistically drop drained buckets so the map can't grow unbounded.
        self._calls += 1
        if self._calls % 1024 == 0:
            for k in [k for k, b in self._hits.items() if not b]:
                del self._hits[k]
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def _limit_for(request: Request) -> int:
    if request.method != "POST":
        return 0
    settings = get_settings()
    if request.url.path in _LOGIN_PATHS:
        return settings.rate_limit_login_per_minute
    if request.url.path == _INGEST_PATH:
        return settings.rate_limit_ingest_per_minute
    return 0


def add_rate_limit(app: FastAPI) -> None:
    limiter = RateLimiter()

    @app.middleware("http")
    async def _rate_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        limit = _limit_for(request)
        if limit > 0:
            client = request.client.host if request.client else "unknown"
            if not limiter.allow(f"{request.url.path}:{client}", limit, _WINDOW_SECONDS):
                return JSONResponse(
                    {"detail": "rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(int(_WINDOW_SECONDS))},
                )
        return await call_next(request)
