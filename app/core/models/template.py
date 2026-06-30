from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.host import ItemValueType
from app.core.models.mixins import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.user import User


class Template(UUIDPrimaryKey, Timestamped, Base):
    """A reusable set of item definitions that can be applied to many hosts."""

    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_templates_owner_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    owner: Mapped[User] = relationship(back_populates="templates", lazy="joined")
    items: Mapped[list[TemplateItem]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class TemplateItem(UUIDPrimaryKey, Timestamped, Base):
    """An item definition within a template (no host, no history of its own)."""

    __tablename__ = "template_items"
    __table_args__ = (
        UniqueConstraint("template_id", "key", name="uq_template_items_template_key"),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="CASCADE"),
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

    template: Mapped[Template] = relationship(back_populates="items", lazy="noload")
