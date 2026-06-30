"""Host dashboard: a grid of item cards with mini-charts and trigger status."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.models.host import Host, Item, ItemValueType
from app.core.models.metric_value import MetricValue
from app.core.models.trigger import Severity, Trigger, TriggerOperator, TriggerState

BASE = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


async def test_host_dashboard_renders_cards(
    web_client: httpx.AsyncClient, session: Any, user: Any
) -> None:
    host = Host(name="dash-host", owner_id=user.id)
    session.add(host)
    await session.flush()
    cpu = Item(
        host_id=host.id,
        key="cpu",
        name="CPU",
        value_type=ItemValueType.FLOAT,
        units="%",
        interval=60,
    )
    secret = Item(
        host_id=host.id,
        key="sec",
        name="Secret",
        value_type=ItemValueType.TEXT,
        is_private=True,
        interval=60,
    )
    session.add_all([cpu, secret])
    await session.flush()
    for i, v in enumerate([10.0, 20.0, 30.0, 25.0]):
        session.add(
            MetricValue(item_id=cpu.id, value_num=v, collected_at=BASE + timedelta(minutes=10 * i))
        )
    # A firing trigger on CPU → the card shows a 'problem' pill.
    session.add(
        Trigger(
            item_id=cpu.id,
            name="hot",
            operator=TriggerOperator.GT,
            threshold=5.0,
            severity=Severity.HIGH,
            state=TriggerState.PROBLEM,
        )
    )
    await session.commit()

    page = await web_client.get(f"/hosts/{host.id}/dashboard")
    assert page.status_code == 200
    assert "dash-card" in page.text
    assert "CPU" in page.text and "Secret" in page.text
    assert "tstate-problem" in page.text  # CPU's firing trigger
    assert 'class="dash-spark"' in page.text  # CPU mini-chart
    assert "🔒" in page.text  # the private item is not charted


async def test_host_dashboard_404_for_unknown_host(
    web_client: httpx.AsyncClient, user: Any
) -> None:
    resp = await web_client.get(f"/hosts/{uuid.uuid4()}/dashboard")
    assert resp.status_code == 404
