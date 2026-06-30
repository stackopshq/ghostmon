"""Secrets encrypted at rest — the privacy layer Zabbix doesn't have."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select

from app.core.models.host import Item
from app.core.models.notification_channel import NotificationChannel
from app.core.schemas.notification_channel import (
    NotificationChannelCreate,
    WebhookChannelConfig,
)
from app.core.security.field_crypto import decrypt_secret, encrypt_secret, is_encrypted
from app.core.services.notification_channel_service import NotificationChannelService
from app.tasks.notifications import dispatcher


def test_encrypt_decrypt_roundtrip() -> None:
    enc = encrypt_secret("s3cr3t-value")
    assert is_encrypted(enc)
    assert enc != "s3cr3t-value"
    assert "s3cr3t-value" not in enc
    assert decrypt_secret(enc) == "s3cr3t-value"
    # Idempotent, and plaintext passes through (back-compat with legacy rows).
    assert encrypt_secret(enc) == enc
    assert decrypt_secret("plain") == "plain"


async def test_webhook_secret_encrypted_and_redacted(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any
) -> None:
    resp = await client.post(
        "/api/channels",
        headers=auth_headers,
        json={
            "name": "hook",
            "config": {"type": "webhook", "url": "https://h/x", "secret": "supersecret1"},
        },
    )
    assert resp.status_code == 201, resp.text
    # The API never returns the secret in clear.
    assert resp.json()["config"]["secret"] == "__redacted__"

    # At rest it is encrypted, not plaintext.
    channel = (await session.execute(select(NotificationChannel))).scalars().one()
    assert channel.config["secret"].startswith("enc:v1:")
    assert "supersecret1" not in channel.config["secret"]


async def test_dispatch_decrypts_webhook_secret(session: Any, user: Any, monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    async def _fake_send_webhook(url: str, payload: Any, secret: str | None) -> None:
        captured["secret"] = secret

    monkeypatch.setattr(dispatcher, "send_webhook", _fake_send_webhook)
    channel = await NotificationChannelService(session).create(
        NotificationChannelCreate(
            name="h", config=WebhookChannelConfig(url="https://h/x", secret="plain-secret-1")
        ),
        user.id,
    )
    await dispatcher.send_test_notification(channel)
    assert captured["secret"] == "plain-secret-1"


async def test_snmp_community_encrypted_and_redacted(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any
) -> None:
    host = await client.post("/api/hosts", headers=auth_headers, json={"name": "r1"})
    host_id = host.json()["id"]
    resp = await client.post(
        f"/api/hosts/{host_id}/items",
        headers=auth_headers,
        json={
            "key": "if.in",
            "name": "In",
            "value_type": "unsigned",
            "source": "snmp",
            "config": {"oid": "1.2.3", "community": "s3cretcomm"},
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["config"]["community"] == "__redacted__"

    item = (await session.execute(select(Item))).scalars().one()
    assert item.config["community"].startswith("enc:v1:")
    assert "s3cretcomm" not in item.config["community"]
