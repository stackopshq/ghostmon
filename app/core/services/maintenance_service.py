from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter  # type: ignore[import-untyped]
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.maintenance import (
    Maintenance,
    MaintenanceStrategy,
    maintenance_monitors,
)
from app.core.schemas.maintenance import MaintenanceCreate, MaintenanceUpdate


class MaintenanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_owner(self, owner_id: uuid.UUID) -> Sequence[Maintenance]:
        stmt = (
            select(Maintenance)
            .where(Maintenance.owner_id == owner_id)
            .order_by(Maintenance.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get(self, maintenance_id: uuid.UUID, owner_id: uuid.UUID) -> Maintenance | None:
        stmt = select(Maintenance).where(
            Maintenance.id == maintenance_id,
            Maintenance.owner_id == owner_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, data: MaintenanceCreate, owner_id: uuid.UUID) -> Maintenance:
        maintenance = Maintenance(
            title=data.title,
            description=data.description,
            is_active=data.is_active,
            strategy=data.strategy,
            start_at=data.start_at,
            end_at=data.end_at,
            cron=data.cron,
            duration_minutes=data.duration_minutes,
            timezone=data.timezone,
            owner_id=owner_id,
        )
        self._session.add(maintenance)
        await self._session.commit()
        await self._session.refresh(maintenance)
        return maintenance

    async def update(self, maintenance: Maintenance, data: MaintenanceUpdate) -> Maintenance:
        payload = data.model_dump(exclude_unset=True)
        for field, value in payload.items():
            setattr(maintenance, field, value)
        await self._session.commit()
        await self._session.refresh(maintenance)
        return maintenance

    async def delete(self, maintenance: Maintenance) -> None:
        await self._session.delete(maintenance)
        await self._session.commit()

    async def attach_monitor(self, maintenance_id: uuid.UUID, monitor_id: uuid.UUID) -> None:
        stmt = (
            pg_insert(maintenance_monitors)
            .values(maintenance_id=maintenance_id, monitor_id=monitor_id)
            .on_conflict_do_nothing()
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def detach_monitor(self, maintenance_id: uuid.UUID, monitor_id: uuid.UUID) -> None:
        stmt = delete(maintenance_monitors).where(
            maintenance_monitors.c.maintenance_id == maintenance_id,
            maintenance_monitors.c.monitor_id == monitor_id,
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def monitors_for_maintenance(self, maintenance_id: uuid.UUID) -> Sequence[uuid.UUID]:
        stmt = select(maintenance_monitors.c.monitor_id).where(
            maintenance_monitors.c.maintenance_id == maintenance_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def active_maintenances_for_monitor(self, monitor_id: uuid.UUID) -> Sequence[Maintenance]:
        stmt = (
            select(Maintenance)
            .join(
                maintenance_monitors,
                maintenance_monitors.c.maintenance_id == Maintenance.id,
            )
            .where(
                maintenance_monitors.c.monitor_id == monitor_id,
                Maintenance.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def is_monitor_under_maintenance(
        self, monitor_id: uuid.UUID, now: datetime | None = None
    ) -> bool:
        moment = now or datetime.now(UTC)
        for maintenance in await self.active_maintenances_for_monitor(monitor_id):
            if is_maintenance_active(maintenance, moment):
                return True
        return False


def is_maintenance_active(maintenance: Maintenance, now: datetime) -> bool:
    """Return True if ``now`` falls inside an active window of ``maintenance``.

    ONCE windows match when start_at <= now <= end_at.
    CRON windows use croniter: find the latest fire time at or before now and
    check whether now is still within ``duration_minutes`` of it.
    """
    if not maintenance.is_active:
        return False
    moment = _as_aware_utc(now)

    if maintenance.strategy is MaintenanceStrategy.ONCE:
        if maintenance.start_at is None or maintenance.end_at is None:
            return False
        start = _as_aware_utc(maintenance.start_at)
        end = _as_aware_utc(maintenance.end_at)
        return start <= moment <= end

    if maintenance.strategy is MaintenanceStrategy.CRON:
        if not maintenance.cron or maintenance.duration_minutes is None:
            return False
        tz = _safe_zoneinfo(maintenance.timezone)
        local_now = moment.astimezone(tz)
        itr = croniter(maintenance.cron, local_now)
        previous_fire: datetime = itr.get_prev(datetime)
        window_end = previous_fire + timedelta(minutes=maintenance.duration_minutes)
        return bool(previous_fire <= local_now <= window_end)

    return False


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_zoneinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")
