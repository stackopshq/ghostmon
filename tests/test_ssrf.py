"""Optional SSRF egress guard for probes and webhooks."""

from __future__ import annotations

from ipaddress import ip_address

import pytest

from app.core.config import get_settings
from app.core.models.monitor_result import ProbeStatus
from app.core.security import ssrf


def test_internal_ip_classification() -> None:
    for internal in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "::1"):
        assert ssrf._is_internal_ip(ip_address(internal)), internal
    assert not ssrf._is_internal_ip(ip_address("8.8.8.8"))


async def test_host_is_blocked_for_ip_literals() -> None:
    assert await ssrf.host_is_blocked("169.254.169.254") is True  # cloud metadata
    assert await ssrf.host_is_blocked("10.0.0.5") is True
    assert await ssrf.host_is_blocked("192.168.1.1") is True
    assert await ssrf.host_is_blocked("::1") is True
    assert await ssrf.host_is_blocked("1.1.1.1") is False


async def test_assert_target_allowed_respects_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    # Off by default: even internal targets pass (monitoring reaches internal hosts).
    await ssrf.assert_target_allowed("127.0.0.1")

    enabled = get_settings().model_copy(update={"ssrf_block_private": True})
    monkeypatch.setattr(ssrf, "get_settings", lambda: enabled)
    with pytest.raises(ssrf.BlockedTargetError):
        await ssrf.assert_target_allowed("169.254.169.254")
    await ssrf.assert_target_allowed("8.8.8.8")  # public still allowed


async def test_http_probe_blocked_when_guard_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import probes

    enabled = get_settings().model_copy(update={"ssrf_block_private": True})
    monkeypatch.setattr(ssrf, "get_settings", lambda: enabled)
    outcome = await probes._probe_http("http://127.0.0.1:9/")
    assert outcome.status is ProbeStatus.DOWN
    assert "blocked" in (outcome.error or "")


async def test_webhook_blocked_when_guard_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks.notifications.delivery import DeliveryError, send_webhook

    enabled = get_settings().model_copy(update={"ssrf_block_private": True})
    monkeypatch.setattr(ssrf, "get_settings", lambda: enabled)
    with pytest.raises(DeliveryError, match="blocked"):
        await send_webhook("http://10.0.0.1/hook", {"x": 1})
