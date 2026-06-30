"""History retention — prune time-series rows older than the configured window.

Probes append a `metric_values` row (and a `monitor_results` row) every interval,
so without pruning both tables grow without bound. A scheduler job calls
`prune_history` hourly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.metric_value import MetricValue
from app.core.models.monitor_result import MonitorResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PruneResult:
    metric_values: int
    monitor_results: int


async def prune_history(session: AsyncSession, cutoff: datetime) -> PruneResult:
    """Delete metric samples and probe results recorded before `cutoff`."""
    mv = cast(
        "CursorResult[Any]",
        await session.execute(delete(MetricValue).where(MetricValue.collected_at < cutoff)),
    )
    mr = cast(
        "CursorResult[Any]",
        await session.execute(delete(MonitorResult).where(MonitorResult.checked_at < cutoff)),
    )
    await session.commit()
    return PruneResult(metric_values=mv.rowcount or 0, monitor_results=mr.rowcount or 0)
