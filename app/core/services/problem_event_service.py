from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.problem_event import ProblemEvent
from app.core.models.trigger import Severity


class ProblemEventService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def open(
        self,
        *,
        trigger_id: uuid.UUID,
        owner_id: uuid.UUID,
        subject: str,
        trigger_name: str,
        severity: Severity,
        value: float | None,
        now: datetime,
    ) -> None:
        """Record a new problem occurrence (added to the current unit of work; the
        caller commits)."""
        self._session.add(
            ProblemEvent(
                trigger_id=trigger_id,
                owner_id=owner_id,
                subject=subject,
                trigger_name=trigger_name,
                severity=severity,
                value=value,
                started_at=now,
            )
        )

    async def close(self, trigger_id: uuid.UUID, now: datetime) -> None:
        """Resolve any still-open problem(s) for a trigger that recovered."""
        await self._session.execute(
            update(ProblemEvent)
            .where(ProblemEvent.trigger_id == trigger_id, ProblemEvent.resolved_at.is_(None))
            .values(resolved_at=now)
        )

    async def list_for_owner(self, owner_id: uuid.UUID, limit: int = 100) -> Sequence[ProblemEvent]:
        """Ongoing problems first (newest started), then recently resolved ones."""
        stmt = (
            select(ProblemEvent)
            .where(ProblemEvent.owner_id == owner_id)
            .order_by(ProblemEvent.resolved_at.isnot(None), ProblemEvent.started_at.desc())
            .limit(limit)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, event_id: uuid.UUID, owner_id: uuid.UUID) -> ProblemEvent | None:
        stmt = select(ProblemEvent).where(
            ProblemEvent.id == event_id, ProblemEvent.owner_id == owner_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def acknowledge(
        self, event_id: uuid.UUID, owner_id: uuid.UUID, user_id: uuid.UUID, now: datetime
    ) -> ProblemEvent | None:
        event = await self.get(event_id, owner_id)
        if event is None:
            return None
        if event.acknowledged_at is None:
            event.acknowledged_at = now
            event.acknowledged_by_id = user_id
            await self._session.commit()
            await self._session.refresh(event)
        return event
