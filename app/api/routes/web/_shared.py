"""Shared helpers for the server-rendered web UI."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.models.user import User
from app.core.security.field_crypto import decrypt_secret
from app.core.security.tokens import TokenError, decode_token
from app.core.services.user_service import UserService

SESSION_COOKIE = "ghostmon_session"

_ROOT = Path(__file__).resolve().parents[4]
templates = Jinja2Templates(directory=str(_ROOT / "templates"))


def _asset_hash() -> str:
    static_dir = _ROOT / "static"
    h = hashlib.md5()
    for f in sorted(static_dir.rglob("*")):
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()[:8]


templates.env.globals["v"] = _asset_hash()
templates.env.globals["version"] = __version__
# Decrypt an at-rest-encrypted field (alert target) for display to its owner.
templates.env.filters["reveal"] = decrypt_secret


async def resolve_current_user(request: Request, session: AsyncSession) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        payload = decode_token(token)
    except TokenError:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        user_id = uuid.UUID(sub)
    except ValueError:
        return None
    return await UserService(session).get_by_id(user_id)


def login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
