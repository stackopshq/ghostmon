from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

# Swagger/ReDoc need a CDN + inline scripts; don't impose the app CSP on them.
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")


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
