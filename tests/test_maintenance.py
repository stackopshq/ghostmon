from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.core.models.maintenance import Maintenance, MaintenanceStrategy
from app.core.models.monitor import Monitor, MonitorStatus, MonitorType
from app.core.services.maintenance_service import (
    MaintenanceService,
    is_maintenance_active,
)


def _once_window(start: datetime, end: datetime, *, is_active: bool = True) -> Maintenance:
    return Maintenance(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        title="deploy",
        description=None,
        is_active=is_active,
        strategy=MaintenanceStrategy.ONCE,
        start_at=start,
        end_at=end,
        cron=None,
        duration_minutes=None,
        timezone="UTC",
    )


def _cron_window(
    cron: str, duration_minutes: int, *, is_active: bool = True, tz: str = "UTC"
) -> Maintenance:
    return Maintenance(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        title="weekly",
        description=None,
        is_active=is_active,
        strategy=MaintenanceStrategy.CRON,
        start_at=None,
        end_at=None,
        cron=cron,
        duration_minutes=duration_minutes,
        timezone=tz,
    )


def test_once_window_inside() -> None:
    now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    w = _once_window(now - timedelta(hours=1), now + timedelta(hours=1))
    assert is_maintenance_active(w, now) is True


def test_once_window_outside() -> None:
    now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    past = _once_window(now - timedelta(hours=3), now - timedelta(hours=2))
    future = _once_window(now + timedelta(hours=1), now + timedelta(hours=2))
    assert is_maintenance_active(past, now) is False
    assert is_maintenance_active(future, now) is False


def test_once_window_inactive_flag_disables() -> None:
    now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    w = _once_window(now - timedelta(hours=1), now + timedelta(hours=1), is_active=False)
    assert is_maintenance_active(w, now) is False


def test_cron_window_inside() -> None:
    # Every day at 02:00 UTC, 60 minutes duration.
    w = _cron_window("0 2 * * *", 60)
    inside = datetime(2026, 5, 1, 2, 30, tzinfo=UTC)
    assert is_maintenance_active(w, inside) is True


def test_cron_window_outside() -> None:
    w = _cron_window("0 2 * * *", 60)
    outside = datetime(2026, 5, 1, 5, 0, tzinfo=UTC)
    assert is_maintenance_active(w, outside) is False


async def test_service_is_under_maintenance_with_attached_monitor(session: Any, user: Any) -> None:
    now = datetime.now(UTC)
    monitor = Monitor(
        name="mon",
        type=MonitorType.HTTP,
        url="https://example.com",
        interval=60,
        status=MonitorStatus.UP,
        owner_id=user.id,
    )
    session.add(monitor)

    maintenance = Maintenance(
        title="deploy",
        is_active=True,
        strategy=MaintenanceStrategy.ONCE,
        start_at=now - timedelta(hours=1),
        end_at=now + timedelta(hours=1),
        owner_id=user.id,
    )
    session.add(maintenance)
    await session.commit()

    svc = MaintenanceService(session)
    await svc.attach_monitor(maintenance.id, monitor.id)

    assert await svc.is_monitor_under_maintenance(monitor.id) is True


async def test_service_no_false_positive_without_attachment(session: Any, user: Any) -> None:
    now = datetime.now(UTC)
    monitor = Monitor(
        name="mon",
        type=MonitorType.HTTP,
        url="https://example.com",
        interval=60,
        owner_id=user.id,
    )
    session.add(monitor)

    other_monitor = Monitor(
        name="other",
        type=MonitorType.HTTP,
        url="https://example.org",
        interval=60,
        owner_id=user.id,
    )
    session.add(other_monitor)

    maintenance = Maintenance(
        title="deploy",
        is_active=True,
        strategy=MaintenanceStrategy.ONCE,
        start_at=now - timedelta(hours=1),
        end_at=now + timedelta(hours=1),
        owner_id=user.id,
    )
    session.add(maintenance)
    await session.commit()

    svc = MaintenanceService(session)
    await svc.attach_monitor(maintenance.id, other_monitor.id)

    assert await svc.is_monitor_under_maintenance(monitor.id) is False


async def test_scheduler_skips_probe_during_maintenance(
    session: Any, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from app.core.models.monitor_result import MonitorResult
    from app.tasks.scheduler import _run_probe_job

    probe_calls = 0

    async def _fake_probe(_: Any) -> Any:
        nonlocal probe_calls
        probe_calls += 1
        raise AssertionError("probe must not run during maintenance")

    monkeypatch.setattr("app.tasks.scheduler.run_probe", _fake_probe)

    dispatched: list[Any] = []
    monkeypatch.setattr(
        "app.tasks.scheduler.schedule_dispatch",
        lambda event: dispatched.append(event),
    )

    now = datetime.now(UTC)
    monitor = Monitor(
        name="mon",
        type=MonitorType.HTTP,
        url="https://example.com",
        interval=60,
        retries=0,
        retry_interval=5,
        status=MonitorStatus.UP,
        owner_id=user.id,
    )
    session.add(monitor)
    maintenance = Maintenance(
        title="deploy",
        is_active=True,
        strategy=MaintenanceStrategy.ONCE,
        start_at=now - timedelta(hours=1),
        end_at=now + timedelta(hours=1),
        owner_id=user.id,
    )
    session.add(maintenance)
    await session.commit()

    await MaintenanceService(session).attach_monitor(maintenance.id, monitor.id)

    await _run_probe_job(monitor_id=monitor.id)

    assert probe_calls == 0
    assert dispatched == []
    rows = (
        (await session.execute(select(MonitorResult).where(MonitorResult.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_api_create_once_and_attach(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    mon = await client.post(
        "/api/monitors",
        headers=auth_headers,
        json={
            "name": "m",
            "type": "http",
            "url": "https://example.com",
            "interval": 60,
        },
    )
    monitor_id = mon.json()["id"]

    now = datetime.now(UTC)
    start = (now - timedelta(hours=1)).isoformat()
    end = (now + timedelta(hours=1)).isoformat()

    create = await client.post(
        "/api/maintenances",
        headers=auth_headers,
        json={
            "title": "deploy",
            "strategy": "once",
            "start_at": start,
            "end_at": end,
        },
    )
    assert create.status_code == 201, create.text
    maint_id = create.json()["id"]

    attach = await client.post(
        f"/api/maintenances/{maint_id}/monitors",
        headers=auth_headers,
        json={"monitor_id": monitor_id},
    )
    assert attach.status_code == 204

    # Monitor list should flag it as under maintenance.
    listed = await client.get("/api/monitors", headers=auth_headers)
    assert listed.status_code == 200
    body = next(m for m in listed.json() if m["id"] == monitor_id)
    assert body["is_under_maintenance"] is True


async def test_api_create_once_rejects_missing_dates(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/maintenances",
        headers=auth_headers,
        json={"title": "bad", "strategy": "once"},
    )
    assert response.status_code == 422


async def test_api_create_cron_rejects_invalid_expression(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/maintenances",
        headers=auth_headers,
        json={
            "title": "bad",
            "strategy": "cron",
            "cron": "not a cron",
            "duration_minutes": 30,
        },
    )
    assert response.status_code == 422


async def test_api_create_once_end_before_start_is_rejected(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    now = datetime.now(UTC)
    response = await client.post(
        "/api/maintenances",
        headers=auth_headers,
        json={
            "title": "bad",
            "strategy": "once",
            "start_at": now.isoformat(),
            "end_at": (now - timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 422


async def test_api_maintenance_isolation_between_users(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any
) -> None:
    from app.core.schemas.user import UserCreate
    from app.core.services.user_service import UserService

    now = datetime.now(UTC)
    created = await client.post(
        "/api/maintenances",
        headers=auth_headers,
        json={
            "title": "alice-window",
            "strategy": "once",
            "start_at": now.isoformat(),
            "end_at": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert created.status_code == 201
    maint_id = created.json()["id"]

    await UserService(session).create_local(
        UserCreate(email="eve@example.com", password="eve-password-value")
    )
    login = await client.post(
        "/api/auth/login",
        data={"username": "eve@example.com", "password": "eve-password-value"},
    )
    eve_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/api/maintenances", headers=eve_headers)).json() == []
    assert (
        await client.get(f"/api/maintenances/{maint_id}", headers=eve_headers)
    ).status_code == 404


async def test_api_detach_monitor(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    mon = await client.post(
        "/api/monitors",
        headers=auth_headers,
        json={
            "name": "m",
            "type": "http",
            "url": "https://example.com",
            "interval": 60,
        },
    )
    monitor_id = mon.json()["id"]

    now = datetime.now(UTC)
    create = await client.post(
        "/api/maintenances",
        headers=auth_headers,
        json={
            "title": "deploy",
            "strategy": "once",
            "start_at": (now - timedelta(hours=1)).isoformat(),
            "end_at": (now + timedelta(hours=1)).isoformat(),
        },
    )
    maint_id = create.json()["id"]

    await client.post(
        f"/api/maintenances/{maint_id}/monitors",
        headers=auth_headers,
        json={"monitor_id": monitor_id},
    )

    detach = await client.delete(
        f"/api/maintenances/{maint_id}/monitors/{monitor_id}",
        headers=auth_headers,
    )
    assert detach.status_code == 204

    body = (await client.get(f"/api/monitors/{monitor_id}", headers=auth_headers)).json()
    assert body["is_under_maintenance"] is False
