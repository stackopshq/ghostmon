from __future__ import annotations

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps.db import DBSession
from app.api.routes.web._shared import SESSION_COOKIE, templates
from app.core.config import get_settings
from app.core.security.tokens import create_access_token
from app.core.services.user_service import UserService

router = APIRouter()


@router.get("/login", response_class=HTMLResponse, response_model=None)
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
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.jwt_access_ttl_minutes * 60,
        path="/",
    )
    return response


@router.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
