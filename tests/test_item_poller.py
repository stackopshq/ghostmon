"""Server-side item poller: due detection, value coercion, and SNMP polling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.core.models.host import Host, Item, ItemSource, ItemValueType
from app.core.models.metric_value import MetricValue
from app.tasks import item_poller
from app.tasks.item_poller import _coerce, _due_snmp_targets, poll_due_items


def test_coerce_numeric_and_text() -> None:
    assert _coerce(ItemValueType.FLOAT, "12345") == (12345.0, None)
    assert _coerce(ItemValueType.UNSIGNED, "7") == (7.0, None)
    # numeric item, non-numeric response → dropped
    assert _coerce(ItemValueType.FLOAT, "Timeticks: 1") == (None, None)
    assert _coerce(ItemValueType.TEXT, "running") == (None, "running")


async def _snmp_host_with_item(
    session: Any, owner_id: Any, *, address: str | None = "10.0.0.1", oid: str = "1.3.6.1.2.1.1.3.0"
) -> Item:
    host = Host(name="router", address=address, owner_id=owner_id)
    session.add(host)
    await session.flush()
    item = Item(
        host_id=host.id,
        key="if.in",
        name="Inbound",
        value_type=ItemValueType.FLOAT,
        interval=60,
        source=ItemSource.SNMP,
        config={"oid": oid, "community": "public"},
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def test_due_detection(session: Any, user: Any) -> None:
    item = await _snmp_host_with_item(session, user.id)
    now = datetime.now(UTC)

    # No sample yet → due.
    due = await _due_snmp_targets(session, now)
    assert [t.item_id for t in due] == [item.id]

    # A fresh sample → not due.
    session.add(MetricValue(item_id=item.id, value_num=1.0, collected_at=now))
    await session.commit()
    assert await _due_snmp_targets(session, now) == []

    # A sample older than the interval → due again.
    assert [t.item_id for t in await _due_snmp_targets(session, now + timedelta(seconds=120))] == [
        item.id
    ]


async def test_trapper_items_and_addressless_hosts_are_not_polled(session: Any, user: Any) -> None:
    # Trapper item (default source) is never polled.
    host = Host(name="h", address="10.0.0.9", owner_id=user.id)
    session.add(host)
    await session.flush()
    session.add(
        Item(host_id=host.id, key="k", name="K", value_type=ItemValueType.FLOAT, interval=60)
    )
    # SNMP item on a host with no address is skipped.
    await _snmp_host_with_item(session, user.id, address=None)
    await session.commit()

    assert await _due_snmp_targets(session, datetime.now(UTC)) == []


async def test_poll_records_history(
    session: Any, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = await _snmp_host_with_item(session, user.id)

    async def _fake_get(host: str, port: int, community: str, oid: str) -> str:
        assert host == "10.0.0.1"
        return "4242"

    monkeypatch.setattr(item_poller, "_snmp_get", _fake_get)
    await poll_due_items()

    values = (
        (await session.execute(select(MetricValue).where(MetricValue.item_id == item.id)))
        .scalars()
        .all()
    )
    assert [v.value_num for v in values] == [4242.0]
