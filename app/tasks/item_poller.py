"""Server-side item polling.

Items whose `source` is SNMP are polled from their host on their interval and the
value appended to history — the counterpart of trapper items (pushed in). A
scheduler job runs `poll_due_items` every cycle.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.session import SessionLocal
from app.core.models.host import Host, Item, ItemSource, ItemValueType
from app.core.models.metric_value import MetricValue
from app.core.observability import count_ingested
from app.core.security.field_crypto import decrypt_secret
from app.core.security.ssrf import BlockedTargetError, assert_target_allowed
from app.core.services.trigger_service import TriggerService
from app.tasks.notifications.dispatcher import schedule_item_trigger_alerts
from app.tasks.probes import SnmpError, _snmp_get

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _PollTarget:
    item_id: uuid.UUID
    item_key: str
    item_name: str
    host_id: uuid.UUID
    host_name: str
    owner_id: uuid.UUID
    value_type: ItemValueType
    address: str
    config: dict[str, Any]


def _coerce(value_type: ItemValueType, raw: str) -> tuple[float | None, str | None]:
    if value_type.is_numeric:
        try:
            return float(raw), None
        except (TypeError, ValueError):
            return None, None  # numeric item but non-numeric response → skip
    return None, str(raw)


async def _due_snmp_targets(session: AsyncSession, now: datetime) -> list[_PollTarget]:
    stmt = (
        select(
            Item,
            Host.id,
            Host.name,
            Host.owner_id,
            Host.address,
            func.max(MetricValue.collected_at),
        )
        .join(Host, Host.id == Item.host_id)
        .outerjoin(MetricValue, MetricValue.item_id == Item.id)
        .where(
            Item.is_enabled.is_(True),
            Item.is_private.is_(False),
            Item.source == ItemSource.SNMP,
            Host.address.is_not(None),
        )
        .group_by(Item.id, Host.id, Host.name, Host.owner_id, Host.address)
    )
    targets: list[_PollTarget] = []
    for item, host_id, host_name, owner_id, address, last_at in (await session.execute(stmt)).all():
        if last_at is None or last_at <= now - timedelta(seconds=item.interval):
            targets.append(
                _PollTarget(
                    item_id=item.id,
                    item_key=item.key,
                    item_name=item.name,
                    host_id=host_id,
                    host_name=host_name,
                    owner_id=owner_id,
                    value_type=item.value_type,
                    address=address,
                    config=item.config or {},
                )
            )
    return targets


async def _poll_one(target: _PollTarget, now: datetime) -> None:
    oid = target.config.get("oid")
    if not oid:
        logger.warning("snmp item %s has no 'oid' in config; skipping", target.item_id)
        return
    try:
        await assert_target_allowed(target.address)
    except BlockedTargetError:
        logger.debug("snmp item %s target blocked by egress policy", target.item_id)
        return
    community = decrypt_secret(str(target.config.get("community", "public")))
    port = int(target.config.get("port", 161))
    try:
        raw = await _snmp_get(target.address, port, community, str(oid))
    except (SnmpError, OSError, TimeoutError) as exc:
        logger.debug("snmp poll failed for item %s: %s", target.item_id, exc)
        return

    value_num, value_text = _coerce(target.value_type, raw)
    if value_num is None and value_text is None:
        return
    async with SessionLocal() as session:
        session.add(
            MetricValue(
                item_id=target.item_id,
                value_num=value_num,
                value_text=value_text,
                collected_at=now,
            )
        )
        await session.commit()
        count_ingested()
        fired = await TriggerService(session).evaluate_item(
            target.item_id,
            target.item_key,
            target.item_name,
            target.host_id,
            target.host_name,
            value_num,
            now,
            owner_id=target.owner_id,
        )
    schedule_item_trigger_alerts(fired, now)


async def poll_due_items() -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        targets = await _due_snmp_targets(session, now)
    if targets:
        await asyncio.gather(*(_poll_one(t, now) for t in targets), return_exceptions=True)
