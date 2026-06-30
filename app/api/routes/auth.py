import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, DBSession
from app.api.routes.web._shared import SESSION_COOKIE
from app.core.config import get_settings
from app.core.schemas.auth import Token
from app.core.schemas.user import UserRead
from app.core.security.oidc import OIDCNotConfiguredError, get_oidc_provider
from app.core.security.tokens import create_access_token
from app.core.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Exchange email/password for a JWT access token",
)
async def login(
    session: DBSession,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    user = await UserService(session).authenticate_local(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings = get_settings()
    token = create_access_token(user.id)
    return Token(access_token=token, expires_in=settings.jwt_access_ttl_minutes * 60)


@router.get(
    "/me",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Return the authenticated user's profile",
)
async def read_me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


def _require_oidc_enabled() -> None:
    if not get_settings().oidc_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OIDC is disabled")


@router.get(
    "/oidc/login",
    summary="Redirect to the configured OIDC provider for sign-in",
    include_in_schema=True,
)
async def oidc_login(request: Request) -> RedirectResponse:
    _require_oidc_enabled()
    settings = get_settings()
    try:
        client = get_oidc_provider().client
    except OIDCNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    redirect_uri = settings.oidc_redirect_uri or str(request.url_for("oidc_callback"))
    return await client.authorize_redirect(request, redirect_uri)  # type: ignore[no-any-return]


@router.get(
    "/oidc/callback",
    name="oidc_callback",
    summary="Handle the OIDC provider callback, set session cookie, redirect to dashboard",
    include_in_schema=True,
)
async def oidc_callback(request: Request, session: DBSession) -> RedirectResponse:
    _require_oidc_enabled()
    try:
        client = get_oidc_provider().client
    except OIDCNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    try:
        token_data: dict[str, Any] = await client.authorize_access_token(request)
    except Exception as exc:
        # Don't surface provider/library internals to the caller; log for operators.
        logger.warning("OIDC token exchange failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OIDC sign-in failed.",
        ) from exc

    userinfo = token_data.get("userinfo") or {}
    subject = userinfo.get("sub")
    email = userinfo.get("email")
    if not subject or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OIDC userinfo missing 'sub' or 'email'",
        )

    user = await UserService(session).upsert_oidc(
        subject=str(subject),
        email=str(email),
        full_name=userinfo.get("name"),
    )

    settings = get_settings()
    jwt_token = create_access_token(user.id)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=jwt_token,
        httponly=True,
        samesite="lax",
        secure=settings.app_env == "production",
        max_age=settings.jwt_access_ttl_minutes * 60,
        path="/",
    )
    return response
