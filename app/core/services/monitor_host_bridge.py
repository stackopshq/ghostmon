"""Bridge between the legacy Monitor model and the Host/Item model.

Part of the expand→migrate step (ADR 0001): every monitor is backed by a Host
carrying its probe signals as items — latency, status (1=up/0=down) and error.
Items are provisioned lazily on the first probe, so existing monitors are
migrated without a data migration. Modelling status/error as items (not just
latency) is the precondition for eventually retiring the monitor-specific tables.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.host import Host, Item, ItemValueType
from app.core.models.monitor import Monitor

LATENCY_ITEM_KEY = "latency_ms"
STATUS_ITEM_KEY = "status"
ERROR_ITEM_KEY = "error"


@dataclass(slots=True)
class BackingItems:
    """A monitor's backing items: latency (ms), status (1=up/0=down), error (text)."""

    latency: Item
    status: Item
    error: Item


def _backing_host_name(monitor: Monitor) -> str:
    # Suffixed with the monitor id so the (owner, name) unique constraint never
    # collides — even between two monitors that share a display name.
    return f"{monitor.name} [{monitor.id.hex[:8]}]"


async def ensure_backing_items(session: AsyncSession, monitor: Monitor) -> BackingItems:
    """Return the monitor's backing items, creating its host and any missing items
    on first use. Commits when it creates anything; otherwise reads through."""
    host_created = False
    if monitor.host_id is None:
        host = Host(
            name=_backing_host_name(monitor),
            description=f"Backing host for monitor “{monitor.name}”.",
            owner_id=monitor.owner_id,
        )
        session.add(host)
        await session.flush()
        monitor.host_id = host.id
        host_created = True

    existing = {
        item.key: item
        for item in (
            await session.execute(select(Item).where(Item.host_id == monitor.host_id))
        ).scalars()
    }
    new_items: list[Item] = []

    def _ensure(key: str, name: str, value_type: ItemValueType, units: str | None = None) -> Item:
        found = existing.get(key)
        if found is not None:
            return found
        item = Item(
            host_id=monitor.host_id,
            key=key,
            name=name,
            value_type=value_type,
            units=units,
            interval=monitor.interval,
        )
        session.add(item)
        new_items.append(item)
        return item

    latency = _ensure(LATENCY_ITEM_KEY, "Latency", ItemValueType.FLOAT, "ms")
    status = _ensure(STATUS_ITEM_KEY, "Status", ItemValueType.UNSIGNED)
    error = _ensure(ERROR_ITEM_KEY, "Error", ItemValueType.TEXT)

    if host_created or new_items:
        await session.commit()
        for item in (latency, status, error):
            await session.refresh(item)
    return BackingItems(latency=latency, status=status, error=error)


async def ensure_backing_latency_item(session: AsyncSession, monitor: Monitor) -> Item:
    """Backwards-compatible accessor for the latency item specifically."""
    return (await ensure_backing_items(session, monitor)).latency
