from __future__ import annotations

import uuid
from datetime import datetime

from croniter import croniter  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.models.maintenance import MaintenanceStrategy


class MaintenanceBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    is_active: bool = True
    strategy: MaintenanceStrategy
    start_at: datetime | None = None
    end_at: datetime | None = None
    cron: str | None = Field(default=None, max_length=128)
    duration_minutes: int | None = Field(default=None, ge=1, le=14 * 24 * 60)
    timezone: str = Field(default="UTC", max_length=64)

    @field_validator("cron")
    @classmethod
    def _validate_cron(cls, value: str | None) -> str | None:
        if value is not None and not croniter.is_valid(value):
            raise ValueError(f"invalid cron expression: {value!r}")
        return value

    @model_validator(mode="after")
    def _validate_strategy_fields(self) -> MaintenanceBase:
        if self.strategy is MaintenanceStrategy.ONCE:
            if self.start_at is None or self.end_at is None:
                raise ValueError("'once' strategy requires start_at and end_at")
            if self.end_at <= self.start_at:
                raise ValueError("end_at must be strictly after start_at")
        elif self.strategy is MaintenanceStrategy.CRON:
            if not self.cron or self.duration_minutes is None:
                raise ValueError("'cron' strategy requires cron and duration_minutes")
        return self


class MaintenanceCreate(MaintenanceBase):
    pass


class MaintenanceUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None
    strategy: MaintenanceStrategy | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    cron: str | None = Field(default=None, max_length=128)
    duration_minutes: int | None = Field(default=None, ge=1, le=14 * 24 * 60)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("cron")
    @classmethod
    def _validate_cron(cls, value: str | None) -> str | None:
        if value is not None and not croniter.is_valid(value):
            raise ValueError(f"invalid cron expression: {value!r}")
        return value


class MaintenanceRead(MaintenanceBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
