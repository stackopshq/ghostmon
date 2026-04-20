from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.monitor import Monitor
    from app.core.models.user import User


class MaintenanceStrategy(enum.StrEnum):
    ONCE = "once"
    CRON = "cron"


maintenance_monitors = Table(
    "maintenance_monitors",
    Base.metadata,
    Column(
        "maintenance_id",
        UUID(as_uuid=True),
        ForeignKey("maintenances.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "monitor_id",
        UUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Maintenance(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "maintenances"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    strategy: Mapped[MaintenanceStrategy] = mapped_column(
        Enum(MaintenanceStrategy, name="maintenance_strategy"), nullable=False
    )

    # ONCE strategy fields
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # CRON strategy fields
    cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    owner: Mapped[User] = relationship(back_populates="maintenances", lazy="joined")
    monitors: Mapped[list[Monitor]] = relationship(
        secondary=maintenance_monitors,
        back_populates="maintenances",
        lazy="noload",
    )
