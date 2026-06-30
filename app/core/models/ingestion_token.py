from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.user import User


class IngestionToken(UUIDPrimaryKey, Timestamped, Base):
    """A long-lived credential for agents/scripts to push metrics without a user
    login. Only the SHA-256 of the token is stored; the plaintext is shown once."""

    __tablename__ = "ingestion_tokens"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_ingest_tokens_owner_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner: Mapped[User] = relationship(back_populates="ingestion_tokens", lazy="joined")
