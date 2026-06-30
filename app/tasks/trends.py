"""Trend rollups — hourly min/avg/max downsampling of numeric item history.

Raw `metric_values` are pruned aggressively by retention; trends keep a much
longer, downsampled view. A scheduler job calls `rollup_trends` hourly (before
history is pruned) and `prune_trends` to bound trend growth.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.metric_trend import MetricTrend
from app.core.models.metric_value import MetricValue

logger = logging.getLogger(__name__)


def _hour_floor(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


async def rollup_trends(session: AsyncSession, now: datetime, lookback_hours: int) -> int:
    """Aggregate numeric samples into hourly (min/avg/max/count) trend rows for
    the last `lookback_hours` *complete* hours, upserting by (item, bucket).

    Idempotent: re-running recomputes the same buckets. The current (incomplete)
    hour is excluded so a bucket is only written once the hour is over. Returns
    the number of buckets inserted or updated.
    """
    if lookback_hours <= 0:
        return 0
    current_hour = _hour_floor(now)
    window_start = current_hour - timedelta(hours=lookback_hours)

    bucket = func.date_trunc("hour", MetricValue.collected_at)
    source = (
        select(
            func.gen_random_uuid().label("id"),
            MetricValue.item_id.label("item_id"),
            bucket.label("bucket"),
            func.min(MetricValue.value_num).label("value_min"),
            func.avg(MetricValue.value_num).label("value_avg"),
            func.max(MetricValue.value_num).label("value_max"),
            func.count().label("sample_count"),
        )
        .where(
            MetricValue.value_num.is_not(None),
            MetricValue.collected_at >= window_start,
            MetricValue.collected_at < current_hour,
        )
        .group_by(MetricValue.item_id, bucket)
    )

    stmt = pg_insert(MetricTrend).from_select(
        ["id", "item_id", "bucket", "value_min", "value_avg", "value_max", "sample_count"],
        source,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_metric_trends_item_bucket",
        set_={
            "value_min": stmt.excluded.value_min,
            "value_avg": stmt.excluded.value_avg,
            "value_max": stmt.excluded.value_max,
            "sample_count": stmt.excluded.sample_count,
        },
    )
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return result.rowcount or 0


async def prune_trends(session: AsyncSession, cutoff: datetime) -> int:
    """Delete trend buckets older than `cutoff`. Returns rows removed."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(delete(MetricTrend).where(MetricTrend.bucket < cutoff)),
    )
    await session.commit()
    return result.rowcount or 0
