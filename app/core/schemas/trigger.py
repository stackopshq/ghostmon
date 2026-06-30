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


class TriggerBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    metric: TriggerMetric = TriggerMetric.LATENCY_MS
    operator: TriggerOperator
    threshold: float
    severity: Severity
    aggregation: TriggerAggregation = TriggerAggregation.LAST
    window_seconds: int = Field(default=0, ge=0, le=86400)
    is_enabled: bool = True


class TriggerCreate(TriggerBase):
    pass


class TriggerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    metric: TriggerMetric | None = None
    operator: TriggerOperator | None = None
    threshold: float | None = None
    severity: Severity | None = None
    aggregation: TriggerAggregation | None = None
    window_seconds: int | None = Field(default=None, ge=0, le=86400)
    is_enabled: bool | None = None


class TriggerRead(TriggerBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    monitor_id: uuid.UUID
    state: TriggerState
    state_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime
