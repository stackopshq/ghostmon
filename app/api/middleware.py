from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

# Swagger/ReDoc need a CDN + inline scripts; don't impose the app CSP on them.
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_cross_origin(request: Request) -> bool:
    """A browser-issued state-changing request whose Origin doesn't match the host.
    Defends cookie-authenticated forms against CSRF (alongside SameSite=lax). Non-
    browser clients (the agent, curl) omit Origin and are unaffected; the Bearer API
    carries no ambient cookie, so it isn't CSRF-able anyway."""
    origin = request.headers.get("origin")
    if not origin:
        return False
    return urlparse(origin).netloc != request.headers.get("host", "")


def _content_security_policy(nonce: str) -> str:
    # Strict by default. `wasm-unsafe-eval` lets the vendored hash-wasm Argon2 module
    # run (zero-knowledge passphrase mode); the per-request nonce admits only our one
    # inline (theme) script. Inline styles are pervasive and low-risk, so style keeps
    # 'unsafe-inline'. No third-party origins — consistent with the no-telemetry stance.
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}' 'wasm-unsafe-eval'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "connect-src 'self'",
            "font-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        )
    )


def add_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def _security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in _UNSAFE_METHODS and _is_cross_origin(request):
            return JSONResponse({"detail": "cross-origin request blocked"}, status_code=403)
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        response = await call_next(request)
        if not request.url.path.startswith(_CSP_EXEMPT_PREFIXES):
            response.headers.setdefault("Content-Security-Policy", _content_security_policy(nonce))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response
