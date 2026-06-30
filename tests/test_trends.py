"""Hourly trend rollups: aggregation, idempotency, retention, and the read API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from app.core.models.host import Host, Item, ItemValueType
from app.core.models.metric_trend import MetricTrend
from app.core.models.metric_value import MetricValue
from app.tasks.trends import prune_trends, rollup_trends

# A fixed "now" so the rollup window is deterministic. current_hour = 12:00 UTC.
NOW = datetime(2026, 6, 30, 12, 30, tzinfo=UTC)


async def _item(
    session: Any, owner_id: Any, value_type: ItemValueType = ItemValueType.FLOAT
) -> Item:
    host = Host(name="srv", owner_id=owner_id)
    session.add(host)
    await session.flush()
    item = Item(host_id=host.id, key="cpu", name="CPU", value_type=value_type, interval=60)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def _sample(session: Any, item_id: Any, value: float | None, when: datetime) -> None:
    session.add(MetricValue(item_id=item_id, value_num=value, collected_at=when))


async def _trends(session: Any, item_id: Any) -> list[MetricTrend]:
    stmt = select(MetricTrend).where(MetricTrend.item_id == item_id).order_by(MetricTrend.bucket)
    return list((await session.execute(stmt)).scalars().all())


async def test_rollup_aggregates_complete_hours_and_is_idempotent(session: Any, user: Any) -> None:
    item = await _item(session, user.id)
    h10 = NOW.replace(hour=10, minute=0)
    h11 = NOW.replace(hour=11, minute=0)
    await _sample(session, item.id, 10.0, h10 + timedelta(minutes=5))
    await _sample(session, item.id, 20.0, h10 + timedelta(minutes=30))
    await _sample(session, item.id, 30.0, h10 + timedelta(minutes=55))
    await _sample(session, item.id, 40.0, h11 + timedelta(minutes=15))
    await session.commit()

    assert await rollup_trends(session, NOW, lookback_hours=6) == 2
    rows = await _trends(session, item.id)
    assert [r.bucket for r in rows] == [h10, h11]
    assert (rows[0].value_min, rows[0].value_avg, rows[0].value_max, rows[0].sample_count) == (
        10.0,
        20.0,
        30.0,
        3,
    )
    assert (rows[1].value_min, rows[1].value_max, rows[1].sample_count) == (40.0, 40.0, 1)

    # Re-running recomputes the same buckets (upsert), not duplicates.
    await rollup_trends(session, NOW, lookback_hours=6)
    assert len(await _trends(session, item.id)) == 2


async def test_rollup_excludes_current_incomplete_hour(session: Any, user: Any) -> None:
    item = await _item(session, user.id)
    await _sample(session, item.id, 99.0, NOW)  # 12:30, current hour — not complete
    await session.commit()
    assert await rollup_trends(session, NOW, lookback_hours=6) == 0
    assert await _trends(session, item.id) == []


async def test_rollup_ignores_non_numeric_samples(session: Any, user: Any) -> None:
    item = await _item(session, user.id, value_type=ItemValueType.TEXT)
    await _sample(session, item.id, None, NOW.replace(hour=10, minute=10))
    await session.commit()
    assert await rollup_trends(session, NOW, lookback_hours=6) == 0
    assert await _trends(session, item.id) == []


async def test_prune_trends_removes_old_buckets(session: Any, user: Any) -> None:
    item = await _item(session, user.id)
    old = MetricTrend(
        item_id=item.id,
        bucket=NOW - timedelta(days=400),
        value_min=1.0,
        value_avg=1.0,
        value_max=1.0,
        sample_count=1,
    )
    recent = MetricTrend(
        item_id=item.id,
        bucket=NOW - timedelta(days=1),
        value_min=2.0,
        value_avg=2.0,
        value_max=2.0,
        sample_count=1,
    )
    session.add_all([old, recent])
    await session.commit()

    removed = await prune_trends(session, NOW - timedelta(days=365))
    assert removed == 1
    assert [r.bucket for r in await _trends(session, item.id)] == [recent.bucket]


async def test_trends_read_api(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any, user: Any
) -> None:
    item = await _item(session, user.id)
    await _sample(session, item.id, 50.0, NOW.replace(hour=9, minute=20))
    await _sample(session, item.id, 70.0, NOW.replace(hour=9, minute=40))
    await session.commit()
    await rollup_trends(session, NOW, lookback_hours=6)

    resp = await client.get(
        f"/api/hosts/{item.host_id}/items/{item.id}/trends", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["value_min"] == 50.0
    assert body[0]["value_avg"] == 60.0
    assert body[0]["value_max"] == 70.0
    assert body[0]["sample_count"] == 2


async def test_item_detail_page_shows_trends(
    web_client: httpx.AsyncClient, session: Any, user: Any
) -> None:
    item = await _item(session, user.id)
    session.add(
        MetricTrend(
            item_id=item.id,
            bucket=NOW.replace(hour=9, minute=0),
            value_min=50.0,
            value_avg=60.0,
            value_max=70.0,
            sample_count=2,
        )
    )
    await session.commit()
    page = await web_client.get(f"/hosts/{item.host_id}/items/{item.id}")
    assert page.status_code == 200
    assert "Hourly trends" in page.text


async def test_item_detail_shows_long_range_trend_chart(
    web_client: httpx.AsyncClient, session: Any, user: Any
) -> None:
    item = await _item(session, user.id)
    for i in range(5):
        session.add(
            MetricTrend(
                item_id=item.id,
                bucket=NOW.replace(hour=8 + i, minute=0),
                value_min=float(10 + i),
                value_avg=float(20 + i),
                value_max=float(30 + i),
                sample_count=3,
            )
        )
    await session.commit()
    page = await web_client.get(f"/hosts/{item.host_id}/items/{item.id}")
    assert page.status_code == 200
    assert "Trends (long-range)" in page.text
    assert "chart-band" in page.text
