from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.host import Item


class MetricValue(UUIDPrimaryKey, Base):
    """One time-series sample of an item. Append-only history.

    Numeric items use `value_num`; text items use `value_text`. The composite
    index supports the dominant access pattern: latest-first range scans per item.
    """

    __tablename__ = "metric_values"
    __table_args__ = (Index("ix_metric_values_item_collected", "item_id", "collected_at"),)

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
    )
    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    item: Mapped[Item] = relationship(back_populates="values", lazy="noload")
