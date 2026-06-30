"""Triggers: evaluation state machine, CRUD API, and severity-based routing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.core.models.metric_value import MetricValue
from app.core.models.monitor import Monitor, MonitorType
from app.core.models.notification_channel import ChannelType, NotificationChannel
from app.core.models.trigger import (
    Severity,
    Trigger,
    TriggerAggregation,
    TriggerMetric,
    TriggerOperator,
    TriggerState,
)
from app.core.services.monitor_host_bridge import ensure_backing_latency_item
from app.core.services.trigger_service import TriggerService
from app.tasks.notifications import dispatcher
from app.tasks.notifications.events import TriggerAlertEvent


async def _make_monitor(session: Any, owner_id: Any, name: str = "api") -> Monitor:
    monitor = Monitor(
        name=name,
        type=MonitorType.HTTP,
        url="https://example.com",
        interval=60,
        owner_id=owner_id,
    )
    session.add(monitor)
    await session.commit()
    await session.refresh(monitor)
    return monitor


async def _make_trigger(
    session: Any,
    monitor_id: Any,
    *,
    operator: TriggerOperator = TriggerOperator.GT,
    threshold: float = 100.0,
    severity: Severity = Severity.WARNING,
    is_enabled: bool = True,
) -> Trigger:
    trigger = Trigger(
        monitor_id=monitor_id,
        name="latency rule",
        metric=TriggerMetric.LATENCY_MS,
        operator=operator,
        threshold=threshold,
        severity=severity,
        is_enabled=is_enabled,
    )
    session.add(trigger)
    await session.commit()
    await session.refresh(trigger)
    return trigger


# ── Evaluation state machine ────────────────────────────────────────────────


async def test_evaluate_transitions_ok_problem_recovery(session: Any, user: Any) -> None:
    monitor = await _make_monitor(session, user.id)
    trigger = await _make_trigger(session, monitor.id, threshold=100.0)
    svc = TriggerService(session)
    now = datetime.now(UTC)

    # Breach -> PROBLEM (fires once).
    fired = await svc.evaluate(monitor.id, {TriggerMetric.LATENCY_MS: 250.0}, now)
    assert [f.new_state for f in fired] == [TriggerState.PROBLEM]
    await session.refresh(trigger)
    assert trigger.state == TriggerState.PROBLEM
    assert trigger.state_changed_at is not None

    # Still breaching -> no new fire.
    assert await svc.evaluate(monitor.id, {TriggerMetric.LATENCY_MS: 300.0}, now) == []

    # Back under threshold -> recovery fires.
    recovered = await svc.evaluate(monitor.id, {TriggerMetric.LATENCY_MS: 50.0}, now)
    assert [f.new_state for f in recovered] == [TriggerState.OK]


async def test_evaluate_no_data_leaves_state_untouched(session: Any, user: Any) -> None:
    monitor = await _make_monitor(session, user.id)
    trigger = await _make_trigger(session, monitor.id)
    fired = await TriggerService(session).evaluate(
        monitor.id, {TriggerMetric.LATENCY_MS: None}, datetime.now(UTC)
    )
    assert fired == []
    await session.refresh(trigger)
    assert trigger.state == TriggerState.OK


async def test_evaluate_skips_disabled_triggers(session: Any, user: Any) -> None:
    monitor = await _make_monitor(session, user.id)
    await _make_trigger(session, monitor.id, is_enabled=False)
    fired = await TriggerService(session).evaluate(
        monitor.id, {TriggerMetric.LATENCY_MS: 9999.0}, datetime.now(UTC)
    )
    assert fired == []


async def test_evaluate_less_than_operator(session: Any, user: Any) -> None:
    monitor = await _make_monitor(session, user.id)
    await _make_trigger(session, monitor.id, operator=TriggerOperator.LT, threshold=10.0)
    fired = await TriggerService(session).evaluate(
        monitor.id, {TriggerMetric.LATENCY_MS: 5.0}, datetime.now(UTC)
    )
    assert [f.new_state for f in fired] == [TriggerState.PROBLEM]


async def test_windowed_avg_trigger_uses_history_not_last_value(session: Any, user: Any) -> None:
    monitor = await _make_monitor(session, user.id)
    item = await ensure_backing_latency_item(session, monitor)
    now = datetime.now(UTC)
    session.add_all(
        [
            MetricValue(item_id=item.id, value_num=100.0, collected_at=now - timedelta(seconds=10)),
            MetricValue(item_id=item.id, value_num=300.0, collected_at=now - timedelta(seconds=20)),
            # Outside the 60s window — must not affect the average.
            MetricValue(
                item_id=item.id, value_num=9999.0, collected_at=now - timedelta(seconds=600)
            ),
        ]
    )
    trigger = Trigger(
        monitor_id=monitor.id,
        name="avg latency",
        metric=TriggerMetric.LATENCY_MS,
        operator=TriggerOperator.GT,
        threshold=150.0,
        severity=Severity.WARNING,
        aggregation=TriggerAggregation.AVG,
        window_seconds=60,
    )
    session.add(trigger)
    await session.commit()

    # The inline last value (50) would NOT breach GT 150; the 60s average (200) does.
    fired = await TriggerService(session).evaluate(
        monitor.id, {TriggerMetric.LATENCY_MS: 50.0}, now
    )
    assert [f.new_state for f in fired] == [TriggerState.PROBLEM]
    assert fired[0].value == 200.0


async def test_windowed_trigger_with_no_history_does_not_fire(session: Any, user: Any) -> None:
    monitor = await _make_monitor(session, user.id)
    await ensure_backing_latency_item(session, monitor)
    trigger = Trigger(
        monitor_id=monitor.id,
        name="max latency",
        metric=TriggerMetric.LATENCY_MS,
        operator=TriggerOperator.GT,
        threshold=1.0,
        severity=Severity.HIGH,
        aggregation=TriggerAggregation.MAX,
        window_seconds=300,
    )
    session.add(trigger)
    await session.commit()
    # No samples in the window → no-data → no fire (even though inline value breaches).
    fired = await TriggerService(session).evaluate(
        monitor.id, {TriggerMetric.LATENCY_MS: 999.0}, datetime.now(UTC)
    )
    assert fired == []


# ── CRUD API ────────────────────────────────────────────────────────────────


async def _create_monitor_via_api(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/monitors",
        headers=headers,
        json={"name": "web", "type": "http", "url": "https://example.com", "interval": 60},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_trigger_crud_via_api(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    monitor_id = await _create_monitor_via_api(client, auth_headers)

    create = await client.post(
        f"/api/monitors/{monitor_id}/triggers",
        headers=auth_headers,
        json={
            "name": "slow responses",
            "operator": "gt",
            "threshold": 500,
            "severity": "high",
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["severity"] == "high"
    assert body["state"] == "ok"
    trigger_id = body["id"]

    listed = await client.get(f"/api/monitors/{monitor_id}/triggers", headers=auth_headers)
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()] == [trigger_id]

    patched = await client.patch(
        f"/api/monitors/{monitor_id}/triggers/{trigger_id}",
        headers=auth_headers,
        json={"threshold": 800, "severity": "disaster"},
    )
    assert patched.status_code == 200
    assert patched.json()["threshold"] == 800
    assert patched.json()["severity"] == "disaster"

    deleted = await client.delete(
        f"/api/monitors/{monitor_id}/triggers/{trigger_id}", headers=auth_headers
    )
    assert deleted.status_code == 204
    gone = await client.get(
        f"/api/monitors/{monitor_id}/triggers/{trigger_id}", headers=auth_headers
    )
    assert gone.status_code == 404


async def test_trigger_on_unowned_monitor_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any
) -> None:
    from app.core.schemas.user import UserCreate
    from app.core.services.user_service import UserService

    other = await UserService(session).create_local(
        UserCreate(email="bob@example.com", password="bob-secret-password", full_name="Bob")
    )
    others_monitor = await _make_monitor(session, other.id, name="bob-mon")

    resp = await client.get(f"/api/monitors/{others_monitor.id}/triggers", headers=auth_headers)
    assert resp.status_code == 404


# ── Severity routing ────────────────────────────────────────────────────────


async def test_dispatch_routes_by_channel_min_severity(
    session: Any, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = await _make_monitor(session, user.id)
    low = NotificationChannel(
        name="all",
        type=ChannelType.WEBHOOK,
        config={"url": "https://hook.invalid/a"},
        owner_id=user.id,
        min_severity=Severity.INFO,
    )
    high = NotificationChannel(
        name="critical-only",
        type=ChannelType.WEBHOOK,
        config={"url": "https://hook.invalid/b"},
        owner_id=user.id,
        min_severity=Severity.HIGH,
    )
    session.add_all([low, high])
    await session.commit()
    monitor.channels.append(low)
    monitor.channels.append(high)
    await session.commit()

    delivered: list[tuple[str, Severity]] = []

    async def _record(event: Any, channel: NotificationChannel) -> None:
        delivered.append((channel.name, channel.min_severity))

    monkeypatch.setattr(dispatcher, "_deliver", _record)

    def _event(severity: Severity) -> TriggerAlertEvent:
        return TriggerAlertEvent(
            monitor_id=monitor.id,
            monitor_name=monitor.name,
            monitor_type=monitor.type,
            monitor_url=monitor.url,
            trigger_name="latency rule",
            severity=severity,
            metric=TriggerMetric.LATENCY_MS,
            operator=TriggerOperator.GT,
            threshold=100.0,
            value=999.0,
            new_state=TriggerState.PROBLEM,
            timestamp=datetime.now(UTC),
        )

    # A WARNING alert reaches only the INFO-threshold channel.
    await dispatcher.dispatch_alert(_event(Severity.WARNING))
    assert {name for name, _ in delivered} == {"all"}

    delivered.clear()
    # A DISASTER alert reaches both.
    await dispatcher.dispatch_alert(_event(Severity.DISASTER))
    assert {name for name, _ in delivered} == {"all", "critical-only"}


# ── Web UI ──────────────────────────────────────────────────────────────────


async def test_trigger_web_ui_create_and_delete(
    web_client: httpx.AsyncClient, user: Any, session: Any
) -> None:
    monitor = await _make_monitor(session, user.id, name="web-mon")

    detail = await web_client.get(f"/monitors/{monitor.id}")
    assert detail.status_code == 200
    assert "Triggers" in detail.text

    created = await web_client.post(
        f"/monitors/{monitor.id}/triggers/new",
        data={
            "name": "slow page",
            "metric": "latency_ms",
            "operator": "gt",
            "threshold": "500",
            "severity": "high",
        },
    )
    assert created.status_code in (200, 303), created.text

    triggers = list(await TriggerService(session).list_for_monitor(monitor.id))
    assert len(triggers) == 1
    assert triggers[0].name == "slow page"

    detail = await web_client.get(f"/monitors/{monitor.id}")
    assert "slow page" in detail.text
    assert "sev-high" in detail.text

    deleted = await web_client.post(f"/monitors/{monitor.id}/triggers/{triggers[0].id}/delete")
    assert deleted.status_code in (200, 303)
    assert list(await TriggerService(session).list_for_monitor(monitor.id)) == []
