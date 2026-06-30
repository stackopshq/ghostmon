from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.models.trigger import (
    Severity,
    TriggerAggregation,
    TriggerMetric,
    TriggerOperator,
    TriggerState,
)


class TriggerRuleBase(BaseModel):
    """The threshold rule, shared by monitor triggers and item triggers."""

    name: str = Field(min_length=1, max_length=255)
    operator: TriggerOperator
    threshold: float
    severity: Severity
    aggregation: TriggerAggregation = TriggerAggregation.LAST
    window_seconds: int = Field(default=0, ge=0, le=86400)
    is_enabled: bool = True


class TriggerCreate(TriggerRuleBase):
    """Create a monitor trigger (the metric selects the monitor signal)."""

    metric: TriggerMetric = TriggerMetric.LATENCY_MS


class ItemTriggerCreate(TriggerRuleBase):
    """Create an item trigger — the item itself is the metric (no `metric`)."""


class TriggerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    metric: TriggerMetric | None = None
    operator: TriggerOperator | None = None
    threshold: float | None = None
    severity: Severity | None = None
    aggregation: TriggerAggregation | None = None
    window_seconds: int | None = Field(default=None, ge=0, le=86400)
    is_enabled: bool | None = None


class TriggerRead(TriggerRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    monitor_id: uuid.UUID | None
    item_id: uuid.UUID | None
    metric: TriggerMetric | None
    state: TriggerState
    state_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime
