from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db.session import SessionLocal
from app.core.models.monitor import Monitor
from app.core.models.notification_channel import (
    ChannelType,
    NotificationChannel,
    monitor_channels,
)
from app.core.models.trigger import TriggerOperator
from app.tasks.notifications.delivery import (
    DeliveryError,
    send_email,
    send_webhook,
)
from app.tasks.notifications.events import AlertEvent, TriggerAlertEvent

logger = logging.getLogger(__name__)

Alert = AlertEvent | TriggerAlertEvent

_OPERATOR_SYMBOL = {
    TriggerOperator.GT: ">",
    TriggerOperator.GE: ">=",
    TriggerOperator.LT: "<",
    TriggerOperator.LE: "<=",
}


def _monitor_link(monitor_id: uuid.UUID) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/?monitor={monitor_id}"


def _format_email(event: Alert) -> tuple[str, str]:
    if isinstance(event, AlertEvent):
        verb = "recovered" if event.is_recovery else "went DOWN"
        subject = f"[GhostMonitor] {event.monitor_name} {verb}"
        lines = [
            f"Monitor: {event.monitor_name} ({event.monitor_type.value})",
            f"URL: {event.monitor_url}",
            f"Status: {event.previous_status.value} -> {event.new_status.value}",
            f"Time: {event.timestamp.isoformat()}",
        ]
        if event.latency_ms is not None:
            lines.append(f"Latency: {event.latency_ms} ms")
        if event.error:
            lines.append(f"Error: {event.error}")
    else:
        state = "cleared" if event.is_recovery else "PROBLEM"
        subject = (
            f"[GhostMonitor] {event.severity.value.upper()} "
            f"{event.monitor_name}: {event.trigger_name} {state}"
        )
        symbol = _OPERATOR_SYMBOL[event.operator]
        lines = [
            f"Monitor: {event.monitor_name} ({event.monitor_type.value})",
            f"URL: {event.monitor_url}",
            f"Trigger: {event.trigger_name} [{event.severity.value}]",
            f"Condition: {event.metric.value} {symbol} {event.threshold}",
            f"Value: {event.value}",
            f"State: {event.new_state.value}",
            f"Time: {event.timestamp.isoformat()}",
        ]

    lines.append("")
    lines.append(f"Details: {_monitor_link(event.monitor_id)}")
    return subject, "\n".join(lines)


async def _deliver(event: Alert, channel: NotificationChannel) -> None:
    config = channel.config or {}
    try:
        if channel.type == ChannelType.EMAIL:
            subject, body = _format_email(event)
            to = config.get("to")
            if not to:
                raise DeliveryError("email channel config missing 'to'")
            await send_email(get_settings(), to=to, subject=subject, body=body)
        elif channel.type == ChannelType.WEBHOOK:
            url = config.get("url")
            if not url:
                raise DeliveryError("webhook channel config missing 'url'")
            await send_webhook(url=url, payload=event.payload(), secret=config.get("secret"))
        else:  # pragma: no cover - exhaustive via StrEnum
            raise DeliveryError(f"unknown channel type: {channel.type}")
    except DeliveryError as exc:
        logger.warning(
            "alert delivery failed for channel %s (%s): %s",
            channel.id,
            channel.type.value,
            exc,
        )


async def _channels_for_monitor(monitor_id: uuid.UUID) -> list[NotificationChannel]:
    async with SessionLocal() as session:
        stmt = (
            select(NotificationChannel)
            .join(monitor_channels, monitor_channels.c.channel_id == NotificationChannel.id)
            .where(
                monitor_channels.c.monitor_id == monitor_id,
                NotificationChannel.is_enabled.is_(True),
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def dispatch_alert(event: Alert) -> None:
    channels = await _channels_for_monitor(event.monitor_id)
    # Severity routing: a channel only receives alerts at or above its threshold.
    eligible = [c for c in channels if c.min_severity.rank <= event.severity.rank]
    if not eligible:
        return
    await asyncio.gather(*(_deliver(event, ch) for ch in eligible), return_exceptions=True)


async def send_test_notification(
    channel: NotificationChannel, monitor: Monitor | None = None
) -> None:
    from datetime import UTC, datetime

    from app.core.models.monitor import MonitorStatus, MonitorType

    event = AlertEvent(
        monitor_id=monitor.id if monitor else uuid.uuid4(),
        monitor_name=monitor.name if monitor else "Test monitor",
        monitor_type=monitor.type if monitor else MonitorType.HTTP,
        monitor_url=monitor.url if monitor else "https://example.com",
        previous_status=MonitorStatus.UP,
        new_status=MonitorStatus.DOWN,
        latency_ms=None,
        error="This is a test notification from GhostMonitor.",
        timestamp=datetime.now(UTC),
    )
    await _deliver(event, channel)


def schedule_dispatch(event: Alert) -> None:
    """Fire-and-forget dispatch on the current event loop.

    Probe jobs call this after committing a status transition; we do not
    await delivery so the probe loop isn't blocked by a slow SMTP server.
    """
    loop = asyncio.get_event_loop()
    task = loop.create_task(dispatch_alert(event))
    task.add_done_callback(_log_task_exception)


def _log_task_exception(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("alert dispatch task failed", exc_info=exc)


__all__ = [
    "dispatch_alert",
    "schedule_dispatch",
    "send_test_notification",
]
