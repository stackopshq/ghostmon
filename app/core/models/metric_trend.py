from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.host import Item


class MetricTrend(UUIDPrimaryKey, Base):
    """Hourly min/avg/max rollup of a numeric item's history.

    Trends downsample `metric_values` so long-range data survives history
    retention (raw samples are pruned aggressively; trends are kept for much
    longer). One row per (item, hour-bucket); the rollup job upserts it.
    """

    __tablename__ = "metric_trends"
    __table_args__ = (UniqueConstraint("item_id", "bucket", name="uq_metric_trends_item_bucket"),)

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Start of the UTC hour this row aggregates.
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value_min: Mapped[float] = mapped_column(Float, nullable=False)
    value_avg: Mapped[float] = mapped_column(Float, nullable=False)
    value_max: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)

    item: Mapped[Item] = relationship(lazy="noload")
