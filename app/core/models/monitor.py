from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.maintenance import Maintenance
    from app.core.models.monitor_result import MonitorResult
    from app.core.models.notification_channel import NotificationChannel
    from app.core.models.trigger import Trigger
    from app.core.models.user import User


class MonitorType(enum.StrEnum):
    HTTP = "http"
    TCP = "tcp"
    PING = "ping"
    SSL = "ssl"
    DOCKER = "docker"


class MonitorStatus(enum.StrEnum):
    UP = "up"
    DOWN = "down"
    PENDING = "pending"
    PAUSED = "paused"


class Monitor(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "monitors"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[MonitorType] = mapped_column(
        Enum(MonitorType, name="monitor_type"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    retry_interval: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, server_default="20"
    )
    status: Mapped[MonitorStatus] = mapped_column(
        Enum(MonitorStatus, name="monitor_status"),
        nullable=False,
        default=MonitorStatus.PENDING,
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner: Mapped[User] = relationship(back_populates="monitors", lazy="joined")
    results: Mapped[list[MonitorResult]] = relationship(
        back_populates="monitor",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    channels: Mapped[list[NotificationChannel]] = relationship(
        secondary="monitor_channels",
        back_populates="monitors",
        lazy="noload",
    )
    maintenances: Mapped[list[Maintenance]] = relationship(
        secondary="maintenance_monitors",
        back_populates="monitors",
        lazy="noload",
    )
    triggers: Mapped[list[Trigger]] = relationship(
        back_populates="monitor",
        cascade="all, delete-orphan",
        lazy="noload",
    )
