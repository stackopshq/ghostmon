import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.api.deps.db import DBSession
from app.core.models.user import User
from app.core.security.tokens import TokenError, decode_token
from app.core.services.user_service import UserService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=True)


async def get_current_user(
    session: DBSession,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
    except TokenError as exc:
        raise credentials_exc from exc

    sub = payload.get("sub")
    if not sub:
        raise credentials_exc
    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise credentials_exc from exc

    user = await UserService(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise credentials_exc
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
