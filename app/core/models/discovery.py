from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.session import Base
from app.core.models.mixins import Timestamped, UUIDPrimaryKey


class DiscoveryMethod(enum.StrEnum):
    PING = "ping"
    TCP = "tcp"


class DiscoveryRule(UUIDPrimaryKey, Timestamped, Base):
    """A network range scanned on a schedule: responsive addresses that are not yet
    a host are provisioned as hosts, optionally with a template's items applied."""

    __tablename__ = "discovery_rules"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    method: Mapped[DiscoveryMethod] = mapped_column(
        Enum(DiscoveryMethod, name="discovery_method"), nullable=False
    )
    # TCP port to probe when method is TCP (ignored for PING).
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Template whose items are applied to each newly discovered host (optional).
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
