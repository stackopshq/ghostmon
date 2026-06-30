from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.models.escalation import EscalationPolicy, EscalationStep
from app.core.models.notification_channel import ChannelType, NotificationChannel
from app.core.models.problem_event import ProblemEvent
from app.core.schemas.escalation import EscalationPolicyCreate
from app.tasks.notifications.events import EscalationAlertEvent

logger = logging.getLogger(__name__)


class EscalationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_owner(self, owner_id: uuid.UUID) -> Sequence[EscalationPolicy]:
        stmt = (
            select(EscalationPolicy)
            .where(EscalationPolicy.owner_id == owner_id)
            .options(selectinload(EscalationPolicy.steps))
            .order_by(EscalationPolicy.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, policy_id: uuid.UUID, owner_id: uuid.UUID) -> EscalationPolicy | None:
        stmt = (
            select(EscalationPolicy)
            .where(EscalationPolicy.id == policy_id, EscalationPolicy.owner_id == owner_id)
            .options(selectinload(EscalationPolicy.steps))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, owner_id: uuid.UUID, data: EscalationPolicyCreate) -> EscalationPolicy:
        policy = EscalationPolicy(owner_id=owner_id, name=data.name, is_enabled=data.is_enabled)
        for step in data.steps:
            policy.steps.append(
                EscalationStep(
                    step_order=step.step_order,
                    delay_minutes=step.delay_minutes,
                    channel_id=step.channel_id,
                    action_command=step.action_command,
                )
            )
        self._session.add(policy)
        await self._session.commit()
        return await self._reload(policy.id, owner_id)

    async def replace(
        self, policy: EscalationPolicy, data: EscalationPolicyCreate
    ) -> EscalationPolicy:
        policy.name = data.name
        policy.is_enabled = data.is_enabled
        policy.steps.clear()
        for step in data.steps:
            policy.steps.append(
                EscalationStep(
                    step_order=step.step_order,
                    delay_minutes=step.delay_minutes,
                    channel_id=step.channel_id,
                    action_command=step.action_command,
                )
            )
        await self._session.commit()
        return await self._reload(policy.id, policy.owner_id)

    async def delete(self, policy: EscalationPolicy) -> None:
        await self._session.delete(policy)
        await self._session.commit()

    async def _reload(self, policy_id: uuid.UUID, owner_id: uuid.UUID) -> EscalationPolicy:
        reloaded = await self.get(policy_id, owner_id)
        assert reloaded is not None  # just persisted
        return reloaded

    async def channels_owned_by(
        self, owner_id: uuid.UUID, channel_ids: set[uuid.UUID]
    ) -> set[uuid.UUID]:
        """The subset of `channel_ids` that the owner actually owns (for validation)."""
        if not channel_ids:
            return set()
        stmt = select(NotificationChannel.id).where(
            NotificationChannel.owner_id == owner_id,
            NotificationChannel.id.in_(channel_ids),
        )
        return set((await self._session.execute(stmt)).scalars().all())

    async def channel_types(
        self, owner_id: uuid.UUID, channel_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, ChannelType]:
        """Map the owner's channels (among `channel_ids`) to their type."""
        if not channel_ids:
            return {}
        stmt = select(NotificationChannel.id, NotificationChannel.type).where(
            NotificationChannel.owner_id == owner_id,
            NotificationChannel.id.in_(channel_ids),
        )
        return {cid: ctype for cid, ctype in (await self._session.execute(stmt))}

    async def _enabled_policy(self, owner_id: uuid.UUID) -> EscalationPolicy | None:
        stmt = (
            select(EscalationPolicy)
            .where(EscalationPolicy.owner_id == owner_id, EscalationPolicy.is_enabled.is_(True))
            .options(selectinload(EscalationPolicy.steps))
            .order_by(EscalationPolicy.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def due_escalations(
        self, now: datetime
    ) -> list[tuple[EscalationAlertEvent, NotificationChannel]]:
        """Advance escalation for every open, unacknowledged problem and return the
        (event, channel) deliveries whose step delay has just elapsed. Persists the
        per-problem progress so steps fire once. Ack/resolve naturally stop it."""
        problems = (
            (
                await self._session.execute(
                    select(ProblemEvent).where(
                        ProblemEvent.resolved_at.is_(None),
                        ProblemEvent.acknowledged_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        deliveries: list[tuple[EscalationAlertEvent, NotificationChannel]] = []
        policy_cache: dict[uuid.UUID, EscalationPolicy | None] = {}
        for problem in problems:
            if problem.owner_id not in policy_cache:
                policy_cache[problem.owner_id] = await self._enabled_policy(problem.owner_id)
            policy = policy_cache[problem.owner_id]
            if policy is None:
                continue
            elapsed_minutes = (now - problem.started_at).total_seconds() / 60
            for step in policy.steps:  # ordered by step_order
                if step.step_order <= problem.escalated_step:
                    continue
                if elapsed_minutes < step.delay_minutes:
                    break  # later steps have larger delays
                channel = await self._session.get(NotificationChannel, step.channel_id)
                # Defense-in-depth: never deliver to a channel of a different owner.
                if channel is not None and channel.owner_id != problem.owner_id:
                    channel = None
                if channel is not None and channel.is_enabled:
                    # Auto-remediation must reach a machine endpoint, never an inbox.
                    if step.action_command is not None and channel.type != ChannelType.WEBHOOK:
                        logger.warning(
                            "remediation step %s targets a non-webhook channel; skipping", step.id
                        )
                    else:
                        deliveries.append(
                            (
                                EscalationAlertEvent(
                                    problem_id=problem.id,
                                    subject=problem.subject,
                                    trigger_name=problem.trigger_name,
                                    severity=problem.severity,
                                    step_order=step.step_order,
                                    value=problem.value,
                                    started_at=problem.started_at,
                                    timestamp=now,
                                    action_command=step.action_command,
                                ),
                                channel,
                            )
                        )
                problem.escalated_step = step.step_order
        await self._session.commit()
        return deliveries
