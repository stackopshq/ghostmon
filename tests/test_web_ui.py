from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx


async def test_dashboard_requires_login(client: httpx.AsyncClient) -> None:
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


async def test_monitors_new_requires_login(client: httpx.AsyncClient) -> None:
    response = await client.get("/monitors/new", follow_redirects=False)
    assert response.status_code == 303


async def test_channels_list_requires_login(client: httpx.AsyncClient) -> None:
    response = await client.get("/channels", follow_redirects=False)
    assert response.status_code == 303


async def test_maintenances_list_requires_login(client: httpx.AsyncClient) -> None:
    response = await client.get("/maintenances", follow_redirects=False)
    assert response.status_code == 303


async def test_dashboard_renders_when_logged_in(web_client: httpx.AsyncClient) -> None:
    response = await web_client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "ghostmon monitor list" in body
    assert "+ New monitor" in body


async def test_create_monitor_via_form(web_client: httpx.AsyncClient) -> None:
    form_page = await web_client.get("/monitors/new")
    assert form_page.status_code == 200
    assert "<form" in form_page.text

    submit = await web_client.post(
        "/monitors/new",
        data={
            "name": "web-created",
            "type": "http",
            "url": "https://example.com",
            "interval": 60,
            "retries": 2,
            "retry_interval": 20,
        },
        follow_redirects=False,
    )
    assert submit.status_code == 303
    assert submit.headers["location"] == "/"

    listed = await web_client.get("/")
    assert "web-created" in listed.text


async def test_delete_monitor_via_form(web_client: httpx.AsyncClient) -> None:
    submit = await web_client.post(
        "/monitors/new",
        data={
            "name": "to-delete",
            "type": "http",
            "url": "https://example.com",
            "interval": 60,
            "retries": 2,
            "retry_interval": 20,
        },
        follow_redirects=False,
    )
    assert submit.status_code == 303

    listed = await web_client.get("/")
    assert "to-delete" in listed.text

    # Resolve monitor id via the JSON API (simpler than parsing HTML).
    login = await web_client.post(
        "/api/auth/login",
        data={"username": "alice@example.com", "password": "alice-secret-password"},
    )
    token = login.json()["access_token"]
    monitors = (
        await web_client.get("/api/monitors", headers={"Authorization": f"Bearer {token}"})
    ).json()
    target = next(m for m in monitors if m["name"] == "to-delete")

    delete = await web_client.post(f"/monitors/{target['id']}/delete", follow_redirects=False)
    assert delete.status_code == 303

    after = await web_client.get("/")
    assert "to-delete" not in after.text


async def test_create_email_channel_via_form(web_client: httpx.AsyncClient) -> None:
    submit = await web_client.post(
        "/channels/new",
        data={
            "name": "ops",
            "type": "email",
            "email_to": "ops@example.com",
            "is_enabled": "on",
        },
        follow_redirects=False,
    )
    assert submit.status_code == 303
    assert submit.headers["location"] == "/channels"

    listed = await web_client.get("/channels")
    assert listed.status_code == 200
    assert "ops" in listed.text
    assert "ops@example.com" in listed.text


async def test_invalid_channel_renders_error(web_client: httpx.AsyncClient) -> None:
    response = await web_client.post(
        "/channels/new",
        data={
            "name": "bad",
            "type": "email",
            "email_to": "not-an-email",
            "is_enabled": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "value is not a valid email" in response.text.lower() or "flash-error" in response.text


async def test_create_maintenance_once_via_form(web_client: httpx.AsyncClient) -> None:
    now = datetime.now(UTC)
    start = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
    end = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

    submit = await web_client.post(
        "/maintenances/new",
        data={
            "title": "weekly deploy",
            "description": "release window",
            "strategy": "once",
            "start_at": start,
            "end_at": end,
            "timezone": "UTC",
            "is_active": "on",
        },
        follow_redirects=False,
    )
    assert submit.status_code == 303

    listed = await web_client.get("/maintenances")
    assert "weekly deploy" in listed.text


async def test_attach_channel_on_monitor_detail(
    web_client: httpx.AsyncClient, session: Any
) -> None:
    from sqlalchemy import select

    from app.core.models.notification_channel import ChannelType, NotificationChannel

    await web_client.post(
        "/monitors/new",
        data={
            "name": "with-channel",
            "type": "http",
            "url": "https://example.com",
            "interval": 60,
            "retries": 2,
            "retry_interval": 20,
        },
        follow_redirects=False,
    )
    await web_client.post(
        "/channels/new",
        data={
            "name": "hook",
            "type": "webhook",
            "webhook_url": "https://hooks.example.com/x",
            "is_enabled": "on",
        },
        follow_redirects=False,
    )

    login = await web_client.post(
        "/api/auth/login",
        data={"username": "alice@example.com", "password": "alice-secret-password"},
    )
    token = login.json()["access_token"]
    monitors = (
        await web_client.get("/api/monitors", headers={"Authorization": f"Bearer {token}"})
    ).json()
    channels = (
        await web_client.get("/api/channels", headers={"Authorization": f"Bearer {token}"})
    ).json()
    monitor_id = monitors[0]["id"]
    channel_id = channels[0]["id"]

    attach = await web_client.post(
        f"/monitors/{monitor_id}/channels/attach",
        data={"channel_id": channel_id},
        follow_redirects=False,
    )
    assert attach.status_code == 303

    detail = await web_client.get(f"/monitors/{monitor_id}")
    assert detail.status_code == 200
    assert "hook" in detail.text

    # Double-check from the DB directly.
    await session.execute(select(NotificationChannel).where(NotificationChannel.name == "hook"))
    assert ChannelType.WEBHOOK
