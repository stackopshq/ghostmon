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
from app.core.config import get_settings
from app.core.models.user import User
from app.core.security.field_crypto import decrypt_secret
from app.core.security.tokens import TokenError, decode_token
from app.core.services.user_service import UserService
from app.web.i18n import context as i18n_context

SESSION_COOKIE = "ghostmon_session"

_ROOT = Path(__file__).resolve().parents[4]
# `context_processors` plutôt qu'un ajout au contexte de chaque route : il y a
# une trentaine de rendus, et celui qu'on oublierait afficherait ses clés brutes
# au lieu de son texte — un oubli visible, mais seulement par qui ouvre la page.
templates = Jinja2Templates(
    directory=str(_ROOT / "templates"),
    context_processors=[i18n_context],
)


def _asset_hash() -> str:
    static_dir = _ROOT / "static"
    h = hashlib.md5()
    for f in sorted(static_dir.rglob("*")):
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()[:8]


templates.env.globals["v"] = _asset_hash()
templates.env.globals["version"] = __version__
# Origine publique du service, pour les seules balises qui ne tolèrent pas une
# URL relative : un aperçu de partage est fabriqué par un robot qui n'a pas
# chargé la page et ne sait donc pas la résoudre. Le slash final est retiré
# ici plutôt que dans le gabarit, où l'oubli ne se verrait qu'à l'affichage
# d'une vignette manquante.
templates.env.globals["base_url"] = get_settings().public_base_url.rstrip("/")
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
    user = await UserService(session).get_by_id(user_id)
    # Mirror the API check: a deactivated account must lose access immediately,
    # not linger until the cookie's JWT expires.
    if user is None or not user.is_active:
        return None
    return user


def login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
