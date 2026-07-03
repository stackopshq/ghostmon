"""GhostAuth access-token validation — the resource-server side of the suite.

GhostMonitor is an OIDC *client* for interactive login (see `oidc.py`). This
module is the complementary *resource-server* piece: it validates access tokens
minted by GhostAuth so the ghostboard portal can call GhostMonitor's widget
endpoints on a user's behalf, forwarding that user's `Authorization: Bearer`.

It is deliberately narrow — mounted ONLY on the portal-facing routes
(`/.well-known/ghostapp.yaml` stays public; the `data_url` widgets require a
token). The app's own UI/API keep using local sessions (`deps/auth.py`).

Validation mirrors ghostboard: signature against the IdP JWKS (RS256/ES256/
**EdDSA** — `alg:none`/HMAC rejected), plus issuer + audience claim checks.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from app.core.config import get_settings

# Asymmetric algorithms accepted for a GhostAuth token signature. GhostAuth
# signs per-realm with RS256/ES256/EdDSA; pinning the allow-list avoids
# algorithm-confusion (and joserfc rejects `alg:none` by construction).
_ACCEPTED_ALGORITHMS = ["RS256", "ES256", "EdDSA"]
_JWKS_TTL_SECONDS = 3600


class TokenValidationError(Exception):
    """The presented bearer token is not a valid GhostAuth access token."""


class ResourceServerNotConfiguredError(RuntimeError):
    """Portal token validation was requested but issuer/audience are unset."""


class GhostAuthValidator:
    """Validates GhostAuth access tokens, caching discovery + JWKS."""

    def __init__(self, *, issuer: str, audience: str) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._jwks_uri: str | None = None
        self._jwks: KeySet | None = None
        self._jwks_expiry = 0.0

    async def _load_jwks(self) -> KeySet:
        now = time.time()
        if self._jwks is not None and now < self._jwks_expiry:
            return self._jwks
        async with httpx.AsyncClient(timeout=5.0) as client:
            if self._jwks_uri is None:
                meta = await client.get(f"{self._issuer}/.well-known/openid-configuration")
                meta.raise_for_status()
                self._jwks_uri = meta.json()["jwks_uri"]
            resp = await client.get(self._jwks_uri)
            resp.raise_for_status()
            self._jwks = KeySet.import_key_set(resp.json())
            self._jwks_expiry = now + _JWKS_TTL_SECONDS
        return self._jwks

    async def verify(self, token: str) -> dict[str, Any]:
        """Return the validated claims, or raise `TokenValidationError`."""
        try:
            key_set = await self._load_jwks()
        except (httpx.HTTPError, KeyError) as exc:
            raise TokenValidationError("cannot load GhostAuth JWKS") from exc

        try:
            decoded = jwt.decode(token, key_set, algorithms=_ACCEPTED_ALGORITHMS)
        except (JoseError, ValueError) as exc:
            raise TokenValidationError(f"bad token signature: {exc}") from exc

        claims = dict(decoded.claims)
        registry = jwt.JWTClaimsRegistry(
            iss={"essential": True, "value": self._issuer},
            aud={"essential": True, "value": self._audience},
            exp={"essential": True},
        )
        try:
            registry.validate(claims)
        except JoseError as exc:
            raise TokenValidationError(f"claim validation failed: {exc}") from exc
        return claims


_validator: GhostAuthValidator | None = None


def get_ghostauth_validator() -> GhostAuthValidator:
    """Build (once) the validator from settings.

    Audience defaults to the OIDC client id — the common case where GhostAuth
    mints access tokens whose `aud` is the requesting client. Override with
    `OIDC_AUDIENCE` when the realm issues a distinct resource identifier.
    """
    global _validator
    if _validator is not None:
        return _validator
    settings = get_settings()
    audience = settings.oidc_audience or settings.oidc_client_id
    if not settings.oidc_issuer or not audience:
        raise ResourceServerNotConfiguredError(
            "portal token validation needs OIDC_ISSUER and OIDC_AUDIENCE/OIDC_CLIENT_ID"
        )
    _validator = GhostAuthValidator(issuer=settings.oidc_issuer, audience=audience)
    return _validator


def reset_validator_cache() -> None:
    """Test hook: drop the cached validator so settings changes take effect."""
    global _validator
    _validator = None
