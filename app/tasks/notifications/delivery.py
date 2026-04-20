from __future__ import annotations

import hashlib
import hmac
import json
import logging
from email.message import EmailMessage
from typing import Any

import aiosmtplib
import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class DeliveryError(RuntimeError):
    pass


def sign_payload(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def send_email(settings: Settings, to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        raise DeliveryError("SMTP is not configured (SMTP_HOST is empty)")

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_starttls,
            timeout=15,
        )
    except aiosmtplib.SMTPException as exc:
        raise DeliveryError(f"SMTP delivery failed: {exc}") from exc


WEBHOOK_TIMEOUT_SECONDS = 10.0


async def send_webhook(url: str, payload: dict[str, Any], secret: str | None = None) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "GhostMonitor/0.1",
    }
    if secret:
        headers["X-GhostMonitor-Signature"] = sign_payload(secret, body)

    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(url, content=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise DeliveryError("webhook timeout") from exc
    except httpx.HTTPError as exc:
        raise DeliveryError(f"webhook error: {exc}") from exc

    if response.status_code >= 400:
        raise DeliveryError(f"webhook returned {response.status_code}: {response.text[:200]}")
