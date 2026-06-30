"""Problem events: recording on trigger flips, resolution, acknowledge, and API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.models.host import Host, Item, ItemValueType
from app.core.models.problem_event import ProblemEvent
from app.core.models.trigger import Severity, Trigger, TriggerOperator
from app.core.services.problem_event_service import ProblemEventService
from app.core.services.trigger_service import TriggerService

NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


async def _host_item_trigger(session: Any, owner_id: Any) -> tuple[Host, Item, Trigger]:
    host = Host(name="web-01", owner_id=owner_id)
    session.add(host)
    await session.flush()
    item = Item(host_id=host.id, key="cpu", name="CPU", value_type=ItemValueType.FLOAT, interval=60)
    session.add(item)
    await session.flush()
    trigger = Trigger(
        item_id=item.id,
        name="hot cpu",
        operator=TriggerOperator.GT,
        threshold=80.0,
        severity=Severity.HIGH,
    )
    session.add(trigger)
    await session.commit()
    return host, item, trigger


async def test_evaluate_item_opens_then_resolves_problem(session: Any, user: Any) -> None:
    host, item, _ = await _host_item_trigger(session, user.id)
    svc = TriggerService(session)

    await svc.evaluate_item(
        item.id, item.key, item.name, host.id, host.name, 95.0, NOW, owner_id=user.id
    )
    events = list(await ProblemEventService(session).list_for_owner(user.id))
    assert len(events) == 1
    assert events[0].resolved_at is None
    assert events[0].subject == "web-01 / cpu"
    assert events[0].trigger_name == "hot cpu"
    assert events[0].severity == Severity.HIGH
    assert events[0].value == 95.0

    # Recovery resolves the open event (no duplicate row).
    await svc.evaluate_item(
        item.id,
        item.key,
        item.name,
        host.id,
        host.name,
        10.0,
        NOW + timedelta(minutes=5),
        owner_id=user.id,
    )
    events = list(await ProblemEventService(session).list_for_owner(user.id))
    assert len(events) == 1
    assert events[0].resolved_at is not None


async def test_acknowledge_problem(session: Any, user: Any) -> None:
    _, _, trigger = await _host_item_trigger(session, user.id)
    event = ProblemEvent(
        trigger_id=trigger.id,
        owner_id=user.id,
        subject="web-01 / cpu",
        trigger_name="hot cpu",
        severity=Severity.HIGH,
        value=95.0,
        started_at=NOW,
    )
    session.add(event)
    await session.commit()

    svc = ProblemEventService(session)
    acked = await svc.acknowledge(event.id, user.id, user.id, NOW + timedelta(minutes=1))
    assert acked is not None
    assert acked.acknowledged_at is not None
    assert acked.acknowledged_by_id == user.id
    # Acknowledging a foreign id does nothing.
    assert await svc.acknowledge(uuid.uuid4(), user.id, user.id, NOW) is None


async def test_problems_api_list_and_ack(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any, user: Any
) -> None:
    _, _, trigger = await _host_item_trigger(session, user.id)
    event = ProblemEvent(
        trigger_id=trigger.id,
        owner_id=user.id,
        subject="web-01 / cpu",
        trigger_name="hot cpu",
        severity=Severity.HIGH,
        value=95.0,
        started_at=NOW,
    )
    session.add(event)
    await session.commit()

    listed = await client.get("/api/problems", headers=auth_headers)
    assert listed.status_code == 200
    body = listed.json()
    assert [e["subject"] for e in body] == ["web-01 / cpu"]
    assert body[0]["acknowledged_at"] is None

    acked = await client.post(f"/api/problems/{event.id}/ack", headers=auth_headers)
    assert acked.status_code == 200
    assert acked.json()["acknowledged_at"] is not None

    missing = await client.post(f"/api/problems/{uuid.uuid4()}/ack", headers=auth_headers)
    assert missing.status_code == 404
