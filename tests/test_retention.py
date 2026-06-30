"""History retention: prune_history drops rows older than the cutoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.models.host import Host, Item, ItemValueType
from app.core.models.metric_value import MetricValue
from app.core.models.monitor import Monitor, MonitorType
from app.core.models.monitor_result import MonitorResult, ProbeStatus
from app.tasks.retention import prune_history


async def test_prune_history_drops_old_keeps_recent(session: Any, user: Any) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(days=40)

    host = Host(name="h", owner_id=user.id)
    session.add(host)
    await session.flush()
    item = Item(host_id=host.id, key="k", name="K", value_type=ItemValueType.FLOAT, interval=60)
    session.add(item)
    await session.flush()
    session.add_all(
        [
            MetricValue(item_id=item.id, value_num=1.0, collected_at=old),
            MetricValue(item_id=item.id, value_num=2.0, collected_at=now),
        ]
    )

    monitor = Monitor(
        name="m", type=MonitorType.HTTP, url="https://x", interval=60, owner_id=user.id
    )
    session.add(monitor)
    await session.flush()
    session.add_all(
        [
            MonitorResult(
                monitor_id=monitor.id, status=ProbeStatus.UP, latency_ms=5, checked_at=old
            ),
            MonitorResult(
                monitor_id=monitor.id, status=ProbeStatus.UP, latency_ms=6, checked_at=now
            ),
        ]
    )
    await session.commit()

    result = await prune_history(session, cutoff=now - timedelta(days=30))
    assert result.metric_values == 1
    assert result.monitor_results == 1

    remaining_values = (
        (await session.execute(select(MetricValue).where(MetricValue.item_id == item.id)))
        .scalars()
        .all()
    )
    assert [v.value_num for v in remaining_values] == [2.0]

    remaining_results = (
        (await session.execute(select(MonitorResult).where(MonitorResult.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert len(remaining_results) == 1
