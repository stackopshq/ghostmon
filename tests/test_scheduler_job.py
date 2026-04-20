"""Integration tests for the scheduler's probe job.

Runs `_run_probe_job` against a monitor that points at a TCP server we spin
up in-process. Verifies that a MonitorResult row is inserted and the
monitor's status is flipped to UP.

Also covers retry semantics by monkey-patching `run_probe` in the scheduler
module to return scripted outcomes.
"""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.models.monitor import Monitor, MonitorStatus, MonitorType
from app.core.models.monitor_result import MonitorResult, ProbeStatus
from app.tasks.probes import ProbeOutcome
from app.tasks.scheduler import _run_probe_job


async def test_probe_job_records_up_status_for_reachable_tcp(session: Any, user: Any) -> None:
    async def _accept(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    server = await asyncio.start_server(_accept, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    async with server:
        monitor = Monitor(
            id=uuid.uuid4(),
            name="tcp-target",
            type=MonitorType.TCP,
            url=f"{host}:{port}",
            interval=60,
            retries=0,
            retry_interval=5,
            status=MonitorStatus.PENDING,
            owner_id=user.id,
        )
        session.add(monitor)
        await session.commit()

        await _run_probe_job(monitor_id=monitor.id)

    await session.refresh(monitor)
    assert monitor.status == MonitorStatus.UP

    results = (
        (await session.execute(select(MonitorResult).where(MonitorResult.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert len(results) == 1
    assert results[0].latency_ms is not None
    assert results[0].error is None


async def test_probe_job_flips_to_down_on_unreachable(session: Any, user: Any) -> None:
    monitor = Monitor(
        id=uuid.uuid4(),
        name="tcp-dead",
        type=MonitorType.TCP,
        url="127.0.0.1:1",
        interval=60,
        retries=0,
        retry_interval=5,
        status=MonitorStatus.PENDING,
        owner_id=user.id,
    )
    session.add(monitor)
    await session.commit()

    await _run_probe_job(monitor_id=monitor.id)

    await session.refresh(monitor)
    assert monitor.status == MonitorStatus.DOWN

    results = (
        (await session.execute(select(MonitorResult).where(MonitorResult.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert len(results) == 1
    assert results[0].error is not None


@pytest.fixture
def _silence_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Capture AlertEvents instead of firing real deliveries."""
    events: list[Any] = []
    monkeypatch.setattr(
        "app.tasks.scheduler.schedule_dispatch",
        lambda event: events.append(event),
    )
    return events


def _script_probe(monkeypatch: pytest.MonkeyPatch, outcomes: list[ProbeOutcome]) -> None:
    """Make run_probe (as seen by the scheduler) yield a scripted sequence."""
    queue = list(outcomes)

    async def _fake(_: Monitor) -> ProbeOutcome:
        return queue.pop(0) if queue else outcomes[-1]

    monkeypatch.setattr("app.tasks.scheduler.run_probe", _fake)


async def test_retries_recover_on_second_probe_no_alert(
    session: Any,
    user: Any,
    monkeypatch: pytest.MonkeyPatch,
    _silence_dispatch: list[Any],
) -> None:
    monitor = Monitor(
        id=uuid.uuid4(),
        name="flap",
        type=MonitorType.HTTP,
        url="https://example.com",
        interval=60,
        retries=2,
        retry_interval=0,
        status=MonitorStatus.UP,
        owner_id=user.id,
    )
    session.add(monitor)
    await session.commit()

    _script_probe(
        monkeypatch,
        [
            ProbeOutcome(ProbeStatus.DOWN, None, "transient"),
            ProbeOutcome(ProbeStatus.UP, 42, None),
        ],
    )
    await _run_probe_job(monitor_id=monitor.id)

    await session.refresh(monitor)
    assert monitor.status == MonitorStatus.UP, "recovered within retry budget, stays UP"
    assert _silence_dispatch == [], "no alert fires when retries save the day"

    results = (
        (await session.execute(select(MonitorResult).where(MonitorResult.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert len(results) == 2, "both attempts recorded as heartbeats"


async def test_retries_exhausted_fires_alert_and_flips_down(
    session: Any,
    user: Any,
    monkeypatch: pytest.MonkeyPatch,
    _silence_dispatch: list[Any],
) -> None:
    monitor = Monitor(
        id=uuid.uuid4(),
        name="sinking",
        type=MonitorType.HTTP,
        url="https://example.com",
        interval=60,
        retries=2,
        retry_interval=0,
        status=MonitorStatus.UP,
        owner_id=user.id,
    )
    session.add(monitor)
    await session.commit()

    _script_probe(
        monkeypatch,
        [
            ProbeOutcome(ProbeStatus.DOWN, None, "attempt 1"),
            ProbeOutcome(ProbeStatus.DOWN, None, "attempt 2"),
            ProbeOutcome(ProbeStatus.DOWN, None, "attempt 3"),
        ],
    )
    await _run_probe_job(monitor_id=monitor.id)

    await session.refresh(monitor)
    assert monitor.status == MonitorStatus.DOWN
    assert len(_silence_dispatch) == 1, "one alert for UP->DOWN"
    event = _silence_dispatch[0]
    assert event.previous_status == MonitorStatus.UP
    assert event.new_status == MonitorStatus.DOWN
    assert event.error == "attempt 3", "last outcome's error is surfaced"

    results = (
        (await session.execute(select(MonitorResult).where(MonitorResult.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert len(results) == 3, "first probe + 2 retries = 3 heartbeats"


async def test_retries_zero_flips_immediately(
    session: Any,
    user: Any,
    monkeypatch: pytest.MonkeyPatch,
    _silence_dispatch: list[Any],
) -> None:
    monitor = Monitor(
        id=uuid.uuid4(),
        name="strict",
        type=MonitorType.HTTP,
        url="https://example.com",
        interval=60,
        retries=0,
        retry_interval=5,
        status=MonitorStatus.UP,
        owner_id=user.id,
    )
    session.add(monitor)
    await session.commit()

    _script_probe(monkeypatch, [ProbeOutcome(ProbeStatus.DOWN, None, "boom")])
    await _run_probe_job(monitor_id=monitor.id)

    await session.refresh(monitor)
    assert monitor.status == MonitorStatus.DOWN
    assert len(_silence_dispatch) == 1

    results = (
        (await session.execute(select(MonitorResult).where(MonitorResult.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert len(results) == 1, "retries=0 disables the retry loop"


async def test_recovery_is_immediate_no_retry(
    session: Any,
    user: Any,
    monkeypatch: pytest.MonkeyPatch,
    _silence_dispatch: list[Any],
) -> None:
    monitor = Monitor(
        id=uuid.uuid4(),
        name="healing",
        type=MonitorType.HTTP,
        url="https://example.com",
        interval=60,
        retries=5,
        retry_interval=60,
        status=MonitorStatus.DOWN,
        owner_id=user.id,
    )
    session.add(monitor)
    await session.commit()

    _script_probe(monkeypatch, [ProbeOutcome(ProbeStatus.UP, 12, None)])
    await _run_probe_job(monitor_id=monitor.id)

    await session.refresh(monitor)
    assert monitor.status == MonitorStatus.UP
    assert len(_silence_dispatch) == 1
    assert _silence_dispatch[0].previous_status == MonitorStatus.DOWN
    assert _silence_dispatch[0].new_status == MonitorStatus.UP

    results = (
        (await session.execute(select(MonitorResult).where(MonitorResult.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert len(results) == 1, "recovery does not trigger retries"
