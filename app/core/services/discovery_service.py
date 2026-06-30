from __future__ import annotations

import asyncio
import ipaddress
import logging
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.discovery import DiscoveryMethod, DiscoveryRule
from app.core.models.host import Host
from app.core.models.monitor_result import ProbeStatus
from app.core.schemas.discovery import MAX_SCAN_HOSTS, DiscoveryRuleCreate
from app.core.services.template_service import TemplateService
from app.tasks.probes import _probe_ping, _probe_tcp

logger = logging.getLogger(__name__)

_SCAN_CONCURRENCY = 32


async def check_reachable(address: str, method: DiscoveryMethod, port: int | None) -> bool:
    """Probe a single address. Module-level so tests can stub it."""
    if method is DiscoveryMethod.TCP and port is not None:
        outcome = await _probe_tcp(f"{address}:{port}")
    else:
        outcome = await _probe_ping(address)
    return outcome.status is ProbeStatus.UP


class DiscoveryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_owner(self, owner_id: uuid.UUID) -> Sequence[DiscoveryRule]:
        stmt = (
            select(DiscoveryRule)
            .where(DiscoveryRule.owner_id == owner_id)
            .order_by(DiscoveryRule.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, rule_id: uuid.UUID, owner_id: uuid.UUID) -> DiscoveryRule | None:
        stmt = select(DiscoveryRule).where(
            DiscoveryRule.id == rule_id, DiscoveryRule.owner_id == owner_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, owner_id: uuid.UUID, data: DiscoveryRuleCreate) -> DiscoveryRule:
        rule = DiscoveryRule(
            owner_id=owner_id,
            name=data.name,
            cidr=data.cidr,
            method=data.method,
            port=data.port,
            template_id=data.template_id,
            interval_seconds=data.interval_seconds,
            is_enabled=data.is_enabled,
        )
        self._session.add(rule)
        await self._session.commit()
        await self._session.refresh(rule)
        return rule

    async def delete(self, rule: DiscoveryRule) -> None:
        await self._session.delete(rule)
        await self._session.commit()

    async def due_rules(self, now: datetime) -> list[DiscoveryRule]:
        stmt = select(DiscoveryRule).where(DiscoveryRule.is_enabled.is_(True))
        rules = (await self._session.execute(stmt)).scalars().all()
        return [
            r
            for r in rules
            if r.last_run_at is None or (now - r.last_run_at).total_seconds() >= r.interval_seconds
        ]

    async def scan_rule(self, rule: DiscoveryRule, now: datetime) -> int:
        """Scan a rule's range, provision hosts for newly-reachable addresses (not
        already a host), apply its template, and stamp last_run_at. Returns the count
        of hosts created."""
        addresses = [str(a) for a in ipaddress.ip_network(rule.cidr, strict=False).hosts()][
            :MAX_SCAN_HOSTS
        ]

        existing_rows = await self._session.execute(
            select(Host.address).where(Host.owner_id == rule.owner_id, Host.address.in_(addresses))
        )
        existing = {addr for (addr,) in existing_rows}
        candidates = [a for a in addresses if a not in existing]

        semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)

        async def _probe(address: str) -> tuple[str, bool]:
            async with semaphore:
                try:
                    return address, await check_reachable(address, rule.method, rule.port)
                except (OSError, TimeoutError):
                    return address, False

        results = await asyncio.gather(*(_probe(a) for a in candidates))
        reachable = [address for address, ok in results if ok]

        templates = TemplateService(self._session)
        created = 0
        for address in reachable:
            host = Host(
                name=address,
                address=address,
                owner_id=rule.owner_id,
                description=f"Discovered by “{rule.name}”.",
            )
            self._session.add(host)
            await self._session.flush()
            if rule.template_id is not None:
                await templates.apply_to_host(rule.template_id, host)
            created += 1

        rule.last_run_at = now
        await self._session.commit()
        if created:
            logger.info("discovery rule %s provisioned %d host(s)", rule.id, created)
        return created
