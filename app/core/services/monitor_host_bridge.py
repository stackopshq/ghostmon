"""Bridge between the legacy Monitor model and the Host/Item model.

Part of the expand→migrate step (ADR 0001): every monitor is backed by a Host
carrying its metrics as items. The latency item is provisioned lazily on the
first probe, so existing monitors are migrated without a data migration.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.host import Host, Item, ItemValueType
from app.core.models.monitor import Monitor

LATENCY_ITEM_KEY = "latency_ms"


def _backing_host_name(monitor: Monitor) -> str:
    # Suffixed with the monitor id so the (owner, name) unique constraint never
    # collides — even between two monitors that share a display name.
    return f"{monitor.name} [{monitor.id.hex[:8]}]"


async def ensure_backing_latency_item(session: AsyncSession, monitor: Monitor) -> Item:
    """Return the monitor's backing latency item, creating its host and item the
    first time. Commits the host/item and the monitor→host link."""
    if monitor.host_id is not None:
        stmt = select(Item).where(Item.host_id == monitor.host_id, Item.key == LATENCY_ITEM_KEY)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

    host = Host(
        name=_backing_host_name(monitor),
        description=f"Backing host for monitor “{monitor.name}”.",
        owner_id=monitor.owner_id,
    )
    session.add(host)
    await session.flush()

    item = Item(
        host_id=host.id,
        key=LATENCY_ITEM_KEY,
        name="Latency",
        value_type=ItemValueType.FLOAT,
        units="ms",
        interval=monitor.interval,
    )
    session.add(item)
    monitor.host_id = host.id
    await session.commit()
    await session.refresh(item)
    return item
