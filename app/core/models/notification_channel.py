from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Column, Enum, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import Timestamped, UUIDPrimaryKey
from app.core.models.trigger import Severity

if TYPE_CHECKING:
    from app.core.models.monitor import Monitor
    from app.core.models.user import User


class ChannelType(enum.StrEnum):
    EMAIL = "email"
    WEBHOOK = "webhook"


monitor_channels = Table(
    "monitor_channels",
    Base.metadata,
    Column(
        "monitor_id",
        UUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "channel_id",
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class NotificationChannel(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "notification_channels"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_channels_owner_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, name="channel_type"), nullable=False
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Only alerts at or above this severity are delivered through this channel.
    # Default INFO keeps existing channels receiving everything.
    min_severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="alert_severity"),
        nullable=False,
        default=Severity.INFO,
        # Native enums store the member *name*; server_default must match (INFO, not info).
        server_default="INFO",
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    owner: Mapped[User] = relationship(back_populates="channels", lazy="joined")
    monitors: Mapped[list[Monitor]] = relationship(
        secondary=monitor_channels,
        back_populates="channels",
        lazy="noload",
    )
