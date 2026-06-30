"""Triggers attached to items: CRUD, evaluation, and alerting via host channels."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.models.host import Host, Item, ItemValueType
from app.core.models.notification_channel import ChannelType, NotificationChannel
from app.core.models.trigger import Severity, Trigger, TriggerOperator, TriggerState
from app.tasks.notifications import dispatcher
from app.tasks.notifications.events import ItemTriggerAlertEvent


async def _host_with_item(session: Any, owner_id: Any) -> tuple[Host, Item]:
    host = Host(name="srv-1", owner_id=owner_id)
    session.add(host)
    await session.flush()
    item = Item(host_id=host.id, key="cpu", name="CPU", value_type=ItemValueType.FLOAT, interval=60)
    session.add(item)
    await session.commit()
    await session.refresh(host)
    await session.refresh(item)
    return host, item


async def test_evaluate_item_fires_and_recovers(session: Any, user: Any) -> None:
    from app.core.services.trigger_service import TriggerService

    host, item = await _host_with_item(session, user.id)
    trigger = Trigger(
        item_id=item.id,
        name="hot cpu",
        operator=TriggerOperator.GT,
        threshold=80.0,
        severity=Severity.HIGH,
    )
    session.add(trigger)
    await session.commit()

    svc = TriggerService(session)
    now = datetime.now(UTC)

    fired = await svc.evaluate_item(item.id, item.key, item.name, host.id, host.name, 95.0, now)
    assert [f.new_state for f in fired] == [TriggerState.PROBLEM]
    assert fired[0].host_name == "srv-1"
    assert fired[0].item_key == "cpu"

    assert (
        await svc.evaluate_item(item.id, item.key, item.name, host.id, host.name, 96.0, now) == []
    )

    recovered = await svc.evaluate_item(item.id, item.key, item.name, host.id, host.name, 5.0, now)
    assert [f.new_state for f in recovered] == [TriggerState.OK]

    # No-data (e.g. private/text item → value_num None) leaves state untouched.
    assert (
        await svc.evaluate_item(item.id, item.key, item.name, host.id, host.name, None, now) == []
    )


async def test_item_trigger_crud_via_api(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any, user: Any
) -> None:
    host, item = await _host_with_item(session, user.id)
    base = f"/api/hosts/{host.id}/items/{item.id}/triggers"

    created = await client.post(
        base,
        headers=auth_headers,
        json={"name": "hot", "operator": "gt", "threshold": 80, "severity": "high"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["item_id"] == str(item.id)
    assert body["monitor_id"] is None
    assert body["metric"] is None
    trigger_id = body["id"]

    listed = await client.get(base, headers=auth_headers)
    assert [t["id"] for t in listed.json()] == [trigger_id]

    patched = await client.patch(
        f"{base}/{trigger_id}", headers=auth_headers, json={"threshold": 120}
    )
    assert patched.status_code == 200
    assert patched.json()["threshold"] == 120

    deleted = await client.delete(f"{base}/{trigger_id}", headers=auth_headers)
    assert deleted.status_code == 204


async def test_item_trigger_alert_routes_to_host_channel(
    session: Any, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    host, _ = await _host_with_item(session, user.id)
    channel = NotificationChannel(
        name="ops",
        type=ChannelType.WEBHOOK,
        config={"url": "https://hook.invalid/x"},
        owner_id=user.id,
        min_severity=Severity.INFO,
    )
    session.add(channel)
    await session.flush()
    host.channels.append(channel)
    await session.commit()

    delivered: list[str] = []

    async def _record(event: Any, ch: NotificationChannel) -> None:
        delivered.append(ch.name)

    monkeypatch.setattr(dispatcher, "_deliver", _record)
    event = ItemTriggerAlertEvent(
        host_id=host.id,
        host_name=host.name,
        item_key="cpu",
        item_name="CPU",
        trigger_name="hot",
        severity=Severity.HIGH,
        operator=TriggerOperator.GT,
        threshold=80.0,
        value=95.0,
        new_state=TriggerState.PROBLEM,
        timestamp=datetime.now(UTC),
    )
    await dispatcher.dispatch_alert(event)
    assert delivered == ["ops"]
