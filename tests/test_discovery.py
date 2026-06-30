"""Network discovery: the scan engine (provision/dedupe), due gating, caps and API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.core.models.discovery import DiscoveryMethod, DiscoveryRule
from app.core.schemas.discovery import DiscoveryRuleCreate
from app.core.services import discovery_service as ds
from app.core.services.discovery_service import DiscoveryService
from app.core.services.host_service import HostService

NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _rule(owner_id: Any, **kw: Any) -> DiscoveryRule:
    defaults: dict[str, Any] = {
        "name": "lan",
        "cidr": "10.9.9.0/30",
        "method": DiscoveryMethod.PING,
        "interval_seconds": 3600,
    }
    defaults.update(kw)
    return DiscoveryRule(owner_id=owner_id, **defaults)


async def test_scan_provisions_reachable_and_dedupes(
    session: Any, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = _rule(user.id)
    session.add(rule)
    await session.commit()

    async def fake_reachable(address: str, method: Any, port: Any) -> bool:
        return address == "10.9.9.1"  # only .1 answers (of .1 and .2)

    monkeypatch.setattr(ds, "check_reachable", fake_reachable)

    created = await DiscoveryService(session).scan_rule(rule, NOW)
    assert created == 1
    hosts = list(await HostService(session).list_for_owner(user.id))
    assert {h.address for h in hosts} == {"10.9.9.1"}
    assert rule.last_run_at == NOW

    # A second scan finds it already provisioned → nothing new.
    assert await DiscoveryService(session).scan_rule(rule, NOW) == 0


async def test_due_rules_gating(session: Any, user: Any) -> None:
    never = _rule(user.id, name="never", last_run_at=None)
    fresh = _rule(user.id, name="fresh", last_run_at=NOW - timedelta(minutes=30))
    stale = _rule(user.id, name="stale", last_run_at=NOW - timedelta(hours=2))
    off = _rule(user.id, name="off", last_run_at=None, is_enabled=False)
    session.add_all([never, fresh, stale, off])
    await session.commit()

    due = await DiscoveryService(session).due_rules(NOW)
    assert {r.name for r in due} == {"never", "stale"}


def test_cidr_is_capped_and_validated() -> None:
    with pytest.raises(ValueError, match="max is"):
        DiscoveryRuleCreate(name="huge", cidr="10.0.0.0/8")
    with pytest.raises(ValueError, match="invalid CIDR"):
        DiscoveryRuleCreate(name="bad", cidr="not-a-cidr")
    with pytest.raises(ValueError, match="port is required"):
        DiscoveryRuleCreate(name="tcp", cidr="10.0.0.0/30", method=DiscoveryMethod.TCP)


async def test_discovery_api_crud_and_scan(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    session: Any,
    user: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await client.post(
        "/api/discovery-rules",
        headers=auth_headers,
        json={"name": "lan", "cidr": "10.9.9.0/30", "method": "ping", "interval_seconds": 3600},
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    bad_template = await client.post(
        "/api/discovery-rules",
        headers=auth_headers,
        json={"name": "x", "cidr": "10.9.9.0/30", "template_id": str(uuid.uuid4())},
    )
    assert bad_template.status_code == 422

    async def fake_reachable(address: str, method: Any, port: Any) -> bool:
        return True

    monkeypatch.setattr(ds, "check_reachable", fake_reachable)
    scanned = await client.post(f"/api/discovery-rules/{rule_id}/scan", headers=auth_headers)
    assert scanned.status_code == 200
    assert scanned.json()["discovered"] == 2  # .1 and .2

    deleted = await client.delete(f"/api/discovery-rules/{rule_id}", headers=auth_headers)
    assert deleted.status_code == 204
