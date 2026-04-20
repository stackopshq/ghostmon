import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.monitor import Monitor
from app.core.models.monitor_result import MonitorResult
from app.core.schemas.monitor import MonitorCreate, MonitorUpdate


class MonitorService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_owner(self, owner_id: uuid.UUID) -> Sequence[Monitor]:
        stmt = (
            select(Monitor).where(Monitor.owner_id == owner_id).order_by(Monitor.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get(self, monitor_id: uuid.UUID, owner_id: uuid.UUID) -> Monitor | None:
        stmt = select(Monitor).where(
            Monitor.id == monitor_id,
            Monitor.owner_id == owner_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, data: MonitorCreate, owner_id: uuid.UUID) -> Monitor:
        monitor = Monitor(
            name=data.name,
            type=data.type,
            url=data.url,
            interval=data.interval,
            retries=data.retries,
            retry_interval=data.retry_interval,
            owner_id=owner_id,
        )
        self._session.add(monitor)
        await self._session.commit()
        await self._session.refresh(monitor)
        return monitor

    async def update(
        self,
        monitor: Monitor,
        data: MonitorUpdate,
    ) -> Monitor:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(monitor, field, value)
        await self._session.commit()
        await self._session.refresh(monitor)
        return monitor

    async def delete(self, monitor: Monitor) -> None:
        await self._session.delete(monitor)
        await self._session.commit()

    async def list_results(
        self, monitor_id: uuid.UUID, limit: int = 100
    ) -> Sequence[MonitorResult]:
        stmt = (
            select(MonitorResult)
            .where(MonitorResult.monitor_id == monitor_id)
            .order_by(MonitorResult.checked_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
