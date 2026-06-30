from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.metric_value import MetricValue
    from app.core.models.user import User


class ItemValueType(enum.StrEnum):
    """Storage class of an item's collected values."""

    FLOAT = "float"
    UNSIGNED = "unsigned"
    TEXT = "text"

    @property
    def is_numeric(self) -> bool:
        return self in (ItemValueType.FLOAT, ItemValueType.UNSIGNED)


class Host(UUIDPrimaryKey, Timestamped, Base):
    """A monitored entity (server, device, service). Owns items."""

    __tablename__ = "hosts"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_hosts_owner_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    owner: Mapped[User] = relationship(back_populates="hosts", lazy="joined")
    items: Mapped[list[Item]] = relationship(
        back_populates="host",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class Item(UUIDPrimaryKey, Timestamped, Base):
    """A single metric collected from a host on a schedule, addressed by `key`."""

    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("host_id", "key", name="uq_items_host_key"),)

    host_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hosts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value_type: Mapped[ItemValueType] = mapped_column(
        Enum(ItemValueType, name="item_value_type"), nullable=False
    )
    units: Mapped[str | None] = mapped_column(String(32), nullable=True)
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    host: Mapped[Host] = relationship(back_populates="items", lazy="noload")
    values: Mapped[list[MetricValue]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        lazy="noload",
    )
