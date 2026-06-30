import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.user import AuthProvider, User
from app.core.schemas.user import UserCreate
from app.core.security.passwords import dummy_verify, hash_password, verify_password


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_local(self, data: UserCreate) -> User:
        user = User(
            email=data.email.lower(),
            full_name=data.full_name,
            auth_provider=AuthProvider.LOCAL,
            password_hash=hash_password(data.password),
        )
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def authenticate_local(self, email: str, password: str) -> User | None:
        user = await self.get_by_email(email)
        if user is not None and user.auth_provider == AuthProvider.LOCAL and user.password_hash:
            valid = verify_password(password, user.password_hash)
        else:
            # No such local account: still spend the hashing time so the response
            # latency doesn't reveal whether the email exists.
            dummy_verify(password)
            valid = False
        if user is None or not valid or not user.is_active:
            return None
        return user

    async def upsert_oidc(self, subject: str, email: str, full_name: str | None) -> User:
        stmt = select(User).where(User.oidc_subject == subject)
        result = await self._session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                email=email.lower(),
                full_name=full_name,
                auth_provider=AuthProvider.OIDC,
                oidc_subject=subject,
            )
            self._session.add(user)
        else:
            user.email = email.lower()
            user.full_name = full_name
        await self._session.commit()
        await self._session.refresh(user)
        return user
