from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.api.deps.db import DBSession
from app.core.models.user import User
from app.core.services.ingestion_token_service import IngestionTokenService


async def get_ingest_owner(
    session: DBSession,
    x_ingest_token: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the owning user from an `X-Ingest-Token` header. Used by the
    agent-facing ingestion endpoint instead of a user login."""
    if not x_ingest_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Ingest-Token header",
            headers={"WWW-Authenticate": "X-Ingest-Token"},
        )
    owner = await IngestionTokenService(session).authenticate(x_ingest_token)
    if owner is None or not owner.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid ingestion token",
            headers={"WWW-Authenticate": "X-Ingest-Token"},
        )
    return owner


IngestOwner = Annotated[User, Depends(get_ingest_owner)]
