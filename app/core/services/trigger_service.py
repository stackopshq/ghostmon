from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.host import Item
from app.core.models.metric_value import MetricValue
from app.core.models.monitor import Monitor
from app.core.models.trigger import (
    Severity,
    Trigger,
    TriggerAggregation,
    TriggerMetric,
    TriggerOperator,
    TriggerState,
)
from app.core.schemas.trigger import ItemTriggerCreate, TriggerCreate, TriggerUpdate
from app.core.services.monitor_host_bridge import LATENCY_ITEM_KEY
from app.core.services.problem_event_service import ProblemEventService

_AGGREGATE_FN: dict[TriggerAggregation, Any] = {
    TriggerAggregation.AVG: func.avg,
    TriggerAggregation.MIN: func.min,
    TriggerAggregation.MAX: func.max,
}


@dataclass(slots=True)
class TriggerFired:
    """A trigger that just changed state, returned by `evaluate` so the caller
    can raise an alert. Carries only what an alert needs — no extra host data."""

    trigger_id: uuid.UUID
    trigger_name: str
    monitor_id: uuid.UUID
    severity: Severity
    metric: TriggerMetric | None
    operator: TriggerOperator
    threshold: float
    value: float
    new_state: TriggerState


@dataclass(slots=True)
class ItemTriggerFired:
    """An item trigger that just changed state. Carries host/item identity so the
    alert can be routed through the host's channels."""

    trigger_id: uuid.UUID
    trigger_name: str
    host_id: uuid.UUID
    host_name: str
    item_key: str
    item_name: str
    severity: Severity
    operator: TriggerOperator
    threshold: float
    value: float
    new_state: TriggerState


def _condition_met(operator: TriggerOperator, value: float, threshold: float) -> bool:
    match operator:
        case TriggerOperator.GT:
            return value > threshold
        case TriggerOperator.GE:
            return value >= threshold
        case TriggerOperator.LT:
            return value < threshold
        case TriggerOperator.LE:
            return value <= threshold


class TriggerService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_monitor(self, monitor_id: uuid.UUID) -> Sequence[Trigger]:
        stmt = (
            select(Trigger)
            .where(Trigger.monitor_id == monitor_id)
            .order_by(Trigger.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get(self, trigger_id: uuid.UUID, monitor_id: uuid.UUID) -> Trigger | None:
        stmt = select(Trigger).where(
            Trigger.id == trigger_id,
            Trigger.monitor_id == monitor_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, monitor_id: uuid.UUID, data: TriggerCreate) -> Trigger:
        trigger = Trigger(
            monitor_id=monitor_id,
            name=data.name,
            metric=data.metric,
            operator=data.operator,
            threshold=data.threshold,
            severity=data.severity,
            aggregation=data.aggregation,
            window_seconds=data.window_seconds,
            is_enabled=data.is_enabled,
        )
        self._session.add(trigger)
        await self._session.commit()
        await self._session.refresh(trigger)
        return trigger

    async def list_for_item(self, item_id: uuid.UUID) -> Sequence[Trigger]:
        stmt = select(Trigger).where(Trigger.item_id == item_id).order_by(Trigger.created_at.desc())
        return (await self._session.execute(stmt)).scalars().all()

    async def get_for_item(self, trigger_id: uuid.UUID, item_id: uuid.UUID) -> Trigger | None:
        stmt = select(Trigger).where(Trigger.id == trigger_id, Trigger.item_id == item_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_for_item(self, item_id: uuid.UUID, data: ItemTriggerCreate) -> Trigger:
        trigger = Trigger(
            item_id=item_id,
            name=data.name,
            metric=None,
            operator=data.operator,
            threshold=data.threshold,
            severity=data.severity,
            aggregation=data.aggregation,
            window_seconds=data.window_seconds,
            is_enabled=data.is_enabled,
        )
        self._session.add(trigger)
        await self._session.commit()
        await self._session.refresh(trigger)
        return trigger

    async def update(self, trigger: Trigger, data: TriggerUpdate) -> Trigger:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(trigger, field, value)
        await self._session.commit()
        await self._session.refresh(trigger)
        return trigger

    async def delete(self, trigger: Trigger) -> None:
        await self._session.delete(trigger)
        await self._session.commit()

    async def evaluate(
        self,
        monitor_id: uuid.UUID,
        values: dict[TriggerMetric, float | None],
        now: datetime,
        *,
        owner_id: uuid.UUID | None = None,
        subject: str | None = None,
    ) -> list[TriggerFired]:
        """Evaluate the monitor's enabled triggers against freshly collected
        metric values and persist any state change. Returns the triggers whose
        state flipped (OK<->PROBLEM) so the caller can alert. Triggers whose
        metric has no value this round are left untouched (no-data, not OK).

        When `owner_id`/`subject` are given, state changes are also recorded as
        problem events for the timeline."""
        stmt = select(Trigger).where(
            Trigger.monitor_id == monitor_id,
            Trigger.is_enabled.is_(True),
        )
        triggers = (await self._session.execute(stmt)).scalars().all()

        fired: list[TriggerFired] = []
        for trigger in triggers:
            value = await self._observe(trigger, monitor_id, values, now)
            if value is None:
                continue
            new_state = (
                TriggerState.PROBLEM
                if _condition_met(trigger.operator, value, trigger.threshold)
                else TriggerState.OK
            )
            if new_state == trigger.state:
                continue
            trigger.state = new_state
            trigger.state_changed_at = now
            if owner_id is not None and subject is not None:
                await self._record_problem(trigger, new_state, owner_id, subject, value, now)
            fired.append(
                TriggerFired(
                    trigger_id=trigger.id,
                    trigger_name=trigger.name,
                    monitor_id=monitor_id,
                    severity=trigger.severity,
                    metric=trigger.metric,
                    operator=trigger.operator,
                    threshold=trigger.threshold,
                    value=value,
                    new_state=new_state,
                )
            )

        if fired:
            await self._session.commit()
        return fired

    async def _record_problem(
        self,
        trigger: Trigger,
        new_state: TriggerState,
        owner_id: uuid.UUID,
        subject: str,
        value: float,
        now: datetime,
    ) -> None:
        events = ProblemEventService(self._session)
        if new_state is TriggerState.PROBLEM:
            events.open(
                trigger_id=trigger.id,
                owner_id=owner_id,
                subject=subject,
                trigger_name=trigger.name,
                severity=trigger.severity,
                value=value,
                now=now,
            )
        else:
            await events.close(trigger.id, now)

    async def _observe(
        self,
        trigger: Trigger,
        monitor_id: uuid.UUID,
        values: dict[TriggerMetric, float | None],
        now: datetime,
    ) -> float | None:
        """The value a trigger compares to its threshold: the latest probe value
        (LAST / no window), or an aggregate over the backing item's history."""
        if trigger.metric is None:
            return None
        if trigger.aggregation == TriggerAggregation.LAST or trigger.window_seconds <= 0:
            return values.get(trigger.metric)

        aggregate = _AGGREGATE_FN[trigger.aggregation]
        since = now - timedelta(seconds=trigger.window_seconds)
        stmt = (
            select(aggregate(MetricValue.value_num))
            .join(Item, Item.id == MetricValue.item_id)
            .join(Monitor, Monitor.host_id == Item.host_id)
            .where(
                Monitor.id == monitor_id,
                Item.key == LATENCY_ITEM_KEY,
                MetricValue.collected_at >= since,
                MetricValue.value_num.is_not(None),
            )
        )
        result = (await self._session.execute(stmt)).scalar_one_or_none()
        return float(result) if result is not None else None

    async def evaluate_item(
        self,
        item_id: uuid.UUID,
        item_key: str,
        item_name: str,
        host_id: uuid.UUID,
        host_name: str,
        latest_value: float | None,
        now: datetime,
        *,
        owner_id: uuid.UUID | None = None,
    ) -> list[ItemTriggerFired]:
        """Evaluate an item's enabled triggers against its latest value (or a
        window of its history), persisting state changes and returning the flips.

        When `owner_id` is given, state changes are also recorded as problem events
        for the timeline (subject = host / item key)."""
        stmt = select(Trigger).where(Trigger.item_id == item_id, Trigger.is_enabled.is_(True))
        triggers = (await self._session.execute(stmt)).scalars().all()

        fired: list[ItemTriggerFired] = []
        for trigger in triggers:
            value = await self._observe_item(trigger, item_id, latest_value, now)
            if value is None:
                continue
            new_state = (
                TriggerState.PROBLEM
                if _condition_met(trigger.operator, value, trigger.threshold)
                else TriggerState.OK
            )
            if new_state == trigger.state:
                continue
            trigger.state = new_state
            trigger.state_changed_at = now
            if owner_id is not None:
                await self._record_problem(
                    trigger, new_state, owner_id, f"{host_name} / {item_key}", value, now
                )
            fired.append(
                ItemTriggerFired(
                    trigger_id=trigger.id,
                    trigger_name=trigger.name,
                    host_id=host_id,
                    host_name=host_name,
                    item_key=item_key,
                    item_name=item_name,
                    severity=trigger.severity,
                    operator=trigger.operator,
                    threshold=trigger.threshold,
                    value=value,
                    new_state=new_state,
                )
            )

        if fired:
            await self._session.commit()
        return fired

    async def _observe_item(
        self, trigger: Trigger, item_id: uuid.UUID, latest_value: float | None, now: datetime
    ) -> float | None:
        if trigger.aggregation == TriggerAggregation.LAST or trigger.window_seconds <= 0:
            return latest_value
        aggregate = _AGGREGATE_FN[trigger.aggregation]
        since = now - timedelta(seconds=trigger.window_seconds)
        stmt = select(aggregate(MetricValue.value_num)).where(
            MetricValue.item_id == item_id,
            MetricValue.collected_at >= since,
            MetricValue.value_num.is_not(None),
        )
        result = (await self._session.execute(stmt)).scalar_one_or_none()
        return float(result) if result is not None else None
