from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import __version__
from app.api.deps.db import DBSession
from app.core.config import get_settings
from app.core.models.user import User
from app.core.security.tokens import TokenError, decode_token
from app.core.services.monitor_service import MonitorService
from app.core.services.user_service import UserService

router = APIRouter(tags=["web"], include_in_schema=False)

_ROOT = Path(__file__).resolve().parents[3]
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


SESSION_COOKIE = "ghostmon_session"


async def _resolve_current_user(request: Request, session) -> User | None:
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


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: DBSession) -> HTMLResponse:
    user = await _resolve_current_user(request, session)
    monitors: list = []
    if user is not None:
        monitors = list(await MonitorService(session).list_for_owner(user.id))
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context={"current_user": user, "monitors": monitors},
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "login.html",
        context={"current_user": None, "oidc_enabled": settings.oidc_enabled},
    )


@router.post("/login", response_model=None)
async def login_submit(
    request: Request,
    session: DBSession,
    email: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    from app.core.security.tokens import create_access_token

    user = await UserService(session).authenticate_local(email, password)
    if user is None:
        settings = get_settings()
        return templates.TemplateResponse(
            request,
            "login.html",
            context={
                "current_user": None,
                "oidc_enabled": settings.oidc_enabled,
                "error": "Invalid email or password.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    token = create_access_token(user.id)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=get_settings().jwt_access_ttl_minutes * 60,
        path="/",
    )
    return response


@router.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
