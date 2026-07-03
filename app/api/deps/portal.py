"""Portal-facing auth: validate a GhostAuth bearer + resolve the local user.

Used only by the ghostboard-facing widget endpoints. The token is a GhostAuth
access token forwarded by the portal on the user's behalf; we verify it, require
the `ghostsuite:ghostmon` entitlement (carried either as an OAuth scope or in the
groups claim — same union ghostboard applies), and map the token subject to the
local GhostMonitor user via `oidc_subject`.

A valid token whose subject has never logged into GhostMonitor resolves to
`user=None`; widget endpoints then return an empty payload and the portal tile
quietly removes itself. No just-in-time provisioning here — accounts are created
through the normal OIDC login, not by a background widget fetch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps.db import DBSession
from app.core.models.user import User
from app.core.security.resource_server import (
    ResourceServerNotConfiguredError,
    TokenValidationError,
    get_ghostauth_validator,
)

_ENTITLEMENT = "ghostsuite:ghostmon"


def _claim_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if value in (None, ""):
        return []
    return [str(value)]


@dataclass(frozen=True)
class PortalContext:
    subject: str
    user: User | None
    claims: dict[str, Any]


async def require_portal_token(request: Request, session: DBSession) -> PortalContext:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        validator = get_ghostauth_validator()
    except ResourceServerNotConfiguredError as exc:
        # OIDC isn't configured on this deployment → portal integration is off.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="portal integration not configured",
        ) from exc

    try:
        claims = await validator.verify(token)
    except TokenValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    entitlements = set(str(claims.get("scope", "")).split()) | set(
        _claim_values(claims.get("groups"))
    )
    if _ENTITLEMENT not in entitlements:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not entitled")

    subject = str(claims.get("sub", ""))
    user = (
        await session.scalar(select(User).where(User.oidc_subject == subject)) if subject else None
    )
    return PortalContext(subject=subject, user=user, claims=claims)


PortalToken = Annotated[PortalContext, Depends(require_portal_token)]
