from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]
from sqlalchemy import select

from app.core.db.session import SessionLocal
from app.core.models.metric_value import MetricValue
from app.core.models.monitor import Monitor, MonitorStatus
from app.core.models.monitor_result import MonitorResult, ProbeStatus
from app.core.models.trigger import TriggerMetric
from app.core.services.maintenance_service import MaintenanceService
from app.core.services.monitor_host_bridge import ensure_backing_latency_item
from app.core.services.trigger_service import TriggerService
from app.tasks.notifications.dispatcher import schedule_dispatch
from app.tasks.notifications.events import AlertEvent, TriggerAlertEvent
from app.tasks.probes import ProbeOutcome, run_probe

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 15


class ProbeScheduler:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._reconcile_job_id = "__reconcile__"

    async def start(self) -> None:
        if self._scheduler.running:
            return
        self._scheduler.start()
        self._scheduler.add_job(
            _reconcile_jobs,
            trigger=IntervalTrigger(seconds=RECONCILE_INTERVAL_SECONDS),
            id=self._reconcile_job_id,
            replace_existing=True,
            next_run_time=datetime.now(UTC),
            kwargs={"scheduler": self._scheduler},
        )
        logger.info("probe scheduler started")

    async def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("probe scheduler stopped")


async def _reconcile_jobs(scheduler: AsyncIOScheduler) -> None:
    async with SessionLocal() as session:
        stmt = select(Monitor.id, Monitor.interval, Monitor.status).where(
            Monitor.status != MonitorStatus.PAUSED
        )
        result = await session.execute(stmt)
        desired = {row.id: row.interval for row in result}

    managed_ids = {uuid.UUID(job.id) for job in scheduler.get_jobs() if job.id != "__reconcile__"}
    desired_ids = set(desired.keys())

    for stale_id in managed_ids - desired_ids:
        scheduler.remove_job(str(stale_id))
        logger.info("removed probe job for monitor %s", stale_id)

    for monitor_id, interval in desired.items():
        job_id = str(monitor_id)
        existing = scheduler.get_job(job_id)
        if existing is None:
            scheduler.add_job(
                _run_probe_job,
                trigger=IntervalTrigger(seconds=interval),
                id=job_id,
                replace_existing=True,
                next_run_time=datetime.now(UTC) + timedelta(seconds=1),
                max_instances=1,
                coalesce=True,
                kwargs={"monitor_id": monitor_id},
            )
            logger.info("scheduled probe for monitor %s every %ds", monitor_id, interval)
            continue

        current_interval = (
            existing.trigger.interval.total_seconds()
            if isinstance(existing.trigger, IntervalTrigger)
            else None
        )
        if current_interval != interval:
            scheduler.reschedule_job(job_id, trigger=IntervalTrigger(seconds=interval))
            logger.info(
                "rescheduled monitor %s from %ss to %ss", monitor_id, current_interval, interval
            )


async def _probe_with_retries(
    monitor: Monitor,
) -> list[tuple[ProbeOutcome, datetime]]:
    """Run probe once; on failure retry up to monitor.retries times at monitor.retry_interval.

    Returns the full list of (outcome, probe_time) tuples. The caller decides
    the final status from the last outcome. Recovery is not retried: a single UP
    after a previous DOWN flips back immediately.
    """
    attempts: list[tuple[ProbeOutcome, datetime]] = [(await run_probe(monitor), datetime.now(UTC))]
    if attempts[0][0].status is ProbeStatus.UP:
        return attempts
    for _ in range(monitor.retries):
        await asyncio.sleep(monitor.retry_interval)
        attempts.append((await run_probe(monitor), datetime.now(UTC)))
        if attempts[-1][0].status is ProbeStatus.UP:
            break
    return attempts


async def _run_probe_job(monitor_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        monitor = await session.get(Monitor, monitor_id)
        if monitor is None:
            logger.debug("monitor %s gone, skipping probe", monitor_id)
            return
        if monitor.status == MonitorStatus.PAUSED:
            return

        if await MaintenanceService(session).is_monitor_under_maintenance(monitor.id):
            logger.debug("monitor %s under maintenance, skipping probe", monitor.id)
            return

        previous_status = monitor.status
        attempts = await _probe_with_retries(monitor)
        final, _ = attempts[-1]

        for outcome, probed_at in attempts:
            session.add(
                MonitorResult(
                    monitor_id=monitor.id,
                    status=outcome.status,
                    latency_ms=outcome.latency_ms,
                    error=outcome.error,
                    checked_at=probed_at,
                )
            )

        new_status = MonitorStatus.UP if final.status is ProbeStatus.UP else MonitorStatus.DOWN
        monitor.status = new_status
        await session.commit()

        monitor_snapshot = (
            monitor.id,
            monitor.name,
            monitor.type,
            monitor.url,
        )

        # Evaluate threshold triggers against the metrics just collected. State
        # changes are persisted here; the resulting alerts are dispatched below.
        now = datetime.now(UTC)
        metric_values: dict[TriggerMetric, float | None] = {
            TriggerMetric.LATENCY_MS: final.latency_ms,
        }
        fired = await TriggerService(session).evaluate(monitor.id, metric_values, now)

        # Mirror the latency into the host/item time-series history (migrate step).
        if final.latency_ms is not None:
            item = await ensure_backing_latency_item(session, monitor)
            session.add(
                MetricValue(item_id=item.id, value_num=float(final.latency_ms), collected_at=now)
            )
            await session.commit()

        trigger_alerts = [
            TriggerAlertEvent(
                monitor_id=monitor.id,
                monitor_name=monitor.name,
                monitor_type=monitor.type,
                monitor_url=monitor.url,
                trigger_name=f.trigger_name,
                severity=f.severity,
                metric=f.metric,
                operator=f.operator,
                threshold=f.threshold,
                value=f.value,
                new_state=f.new_state,
                timestamp=now,
            )
            for f in fired
        ]

    # Only alert on UP<->DOWN transitions, never from PENDING (initial probe).
    should_alert = (
        previous_status in (MonitorStatus.UP, MonitorStatus.DOWN) and previous_status != new_status
    )
    if should_alert:
        mon_id, mon_name, mon_type, mon_url = monitor_snapshot
        schedule_dispatch(
            AlertEvent(
                monitor_id=mon_id,
                monitor_name=mon_name,
                monitor_type=mon_type,
                monitor_url=mon_url,
                previous_status=previous_status,
                new_status=new_status,
                latency_ms=final.latency_ms,
                error=final.error,
                timestamp=datetime.now(UTC),
            )
        )

    for trigger_alert in trigger_alerts:
        schedule_dispatch(trigger_alert)


def build_scheduler() -> ProbeScheduler:
    return ProbeScheduler()
