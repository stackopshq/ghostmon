from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.models.monitor import Monitor, MonitorStatus, MonitorType
from app.core.models.notification_channel import ChannelType, NotificationChannel
from app.tasks.notifications.delivery import (
    DeliveryError,
    send_webhook,
    sign_payload,
)
from app.tasks.notifications.dispatcher import (
    _channels_for_monitor,
    _deliver,
    dispatch_alert,
)
from app.tasks.notifications.events import AlertEvent


def _event(new_status: MonitorStatus = MonitorStatus.DOWN) -> AlertEvent:
    return AlertEvent(
        monitor_id=uuid.uuid4(),
        monitor_name="example",
        monitor_type=MonitorType.HTTP,
        monitor_url="https://example.com",
        previous_status=MonitorStatus.UP,
        new_status=new_status,
        latency_ms=None,
        error="timeout",
        timestamp=datetime.now(UTC),
    )


def test_sign_payload_matches_reference() -> None:
    secret = "shh"
    body = b'{"hello":"world"}'
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert sign_payload(secret, body) == expected


def test_alert_event_payload_shape() -> None:
    event = _event()
    payload = event.payload()
    assert payload["event"] == "status_change"
    assert payload["status"] == "down"
    assert payload["previous_status"] == "up"
    assert payload["monitor"]["url"] == "https://example.com"


async def test_send_webhook_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["body"] = request.content
        received["sig"] = request.headers.get("x-ghostmonitor-signature")
        received["ct"] = request.headers.get("content-type")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("app.tasks.notifications.delivery.httpx.AsyncClient", factory)

    await send_webhook("https://hook.example.com", {"hello": "world"}, secret="shh")

    assert received["ct"] == "application/json"
    assert received["sig"] == sign_payload("shh", received["body"])
    assert json.loads(received["body"]) == {"hello": "world"}


async def test_send_webhook_raises_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(503, text="bad"))
    original = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("app.tasks.notifications.delivery.httpx.AsyncClient", factory)

    with pytest.raises(DeliveryError):
        await send_webhook("https://hook.example.com", {})


async def test_deliver_skips_on_missing_webhook_url_without_raising() -> None:
    channel = NotificationChannel(
        id=uuid.uuid4(),
        name="broken",
        type=ChannelType.WEBHOOK,
        config={},  # missing url
        is_enabled=True,
        owner_id=uuid.uuid4(),
    )
    # _deliver swallows DeliveryError and logs; should not raise.
    await _deliver(_event(), channel)


async def test_channels_for_monitor_filters_disabled(session: Any, user: Any) -> None:
    from app.core.models.monitor import Monitor as MonitorModel
    from app.core.services.notification_channel_service import (
        NotificationChannelService,
    )

    monitor = MonitorModel(
        name="m",
        type=MonitorType.HTTP,
        url="https://example.com",
        interval=60,
        owner_id=user.id,
    )
    session.add(monitor)

    enabled = NotificationChannel(
        name="on",
        type=ChannelType.WEBHOOK,
        config={"url": "https://hook.example.com/live"},
        is_enabled=True,
        owner_id=user.id,
    )
    disabled = NotificationChannel(
        name="off",
        type=ChannelType.WEBHOOK,
        config={"url": "https://hook.example.com/dead"},
        is_enabled=False,
        owner_id=user.id,
    )
    session.add_all([enabled, disabled])
    await session.commit()

    svc = NotificationChannelService(session)
    await svc.attach(monitor.id, enabled.id)
    await svc.attach(monitor.id, disabled.id)

    channels = await _channels_for_monitor(monitor.id)
    assert [c.id for c in channels] == [enabled.id]


async def test_dispatch_alert_fires_for_attached_channel(
    session: Any, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.services.notification_channel_service import (
        NotificationChannelService,
    )

    monitor = Monitor(
        name="m",
        type=MonitorType.HTTP,
        url="https://example.com",
        interval=60,
        owner_id=user.id,
        status=MonitorStatus.UP,
    )
    session.add(monitor)

    channel = NotificationChannel(
        name="hook",
        type=ChannelType.WEBHOOK,
        config={"url": "https://hook.example.com/x"},
        is_enabled=True,
        owner_id=user.id,
    )
    session.add(channel)
    await session.commit()

    await NotificationChannelService(session).attach(monitor.id, channel.id)

    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("app.tasks.notifications.delivery.httpx.AsyncClient", factory)

    event = AlertEvent(
        monitor_id=monitor.id,
        monitor_name=monitor.name,
        monitor_type=monitor.type,
        monitor_url=monitor.url,
        previous_status=MonitorStatus.UP,
        new_status=MonitorStatus.DOWN,
        latency_ms=None,
        error="timeout",
        timestamp=datetime.now(UTC),
    )
    await dispatch_alert(event)

    assert len(calls) == 1
    assert calls[0]["body"]["status"] == "down"


async def test_dispatch_alert_no_channels_is_noop() -> None:
    # Monitor id with no attached channels — must not raise.
    await dispatch_alert(_event())
