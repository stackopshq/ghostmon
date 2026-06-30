from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.ingestion_token import IngestionToken
from app.core.models.user import User

_TOKEN_PREFIX = "gmi_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class IngestionTokenService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_owner(self, owner_id: uuid.UUID) -> Sequence[IngestionToken]:
        stmt = (
            select(IngestionToken)
            .where(IngestionToken.owner_id == owner_id)
            .order_by(IngestionToken.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, token_id: uuid.UUID, owner_id: uuid.UUID) -> IngestionToken | None:
        stmt = select(IngestionToken).where(
            IngestionToken.id == token_id, IngestionToken.owner_id == owner_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, owner_id: uuid.UUID, name: str) -> tuple[IngestionToken, str]:
        """Create a token and return it with its plaintext secret (shown once)."""
        plaintext = _TOKEN_PREFIX + secrets.token_urlsafe(24)
        token = IngestionToken(owner_id=owner_id, name=name, token_hash=_hash(plaintext))
        self._session.add(token)
        await self._session.commit()
        await self._session.refresh(token)
        return token, plaintext

    async def delete(self, token: IngestionToken) -> None:
        await self._session.delete(token)
        await self._session.commit()

    async def authenticate(self, presented: str) -> User | None:
        """Resolve the owning user from a presented token, stamping last_used_at.
        Returns None if the token is unknown."""
        stmt = select(IngestionToken).where(IngestionToken.token_hash == _hash(presented))
        token = (await self._session.execute(stmt)).scalar_one_or_none()
        if token is None:
            return None
        token.last_used_at = datetime.now(UTC)
        owner = token.owner
        await self._session.commit()
        return owner
