from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.monitor import Monitor


class ProbeStatus(enum.StrEnum):
    UP = "up"
    DOWN = "down"


class MonitorResult(UUIDPrimaryKey, Base):
    __tablename__ = "monitor_results"

    monitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[ProbeStatus] = mapped_column(
        Enum(ProbeStatus, name="probe_status"),
        nullable=False,
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    monitor: Mapped[Monitor] = relationship(back_populates="results")
