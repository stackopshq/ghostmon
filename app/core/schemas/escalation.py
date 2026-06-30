from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EscalationStepCreate(BaseModel):
    step_order: int = Field(ge=1, le=100)
    delay_minutes: int = Field(ge=0, le=10080)  # up to a week
    channel_id: uuid.UUID
    # When set, an auto-remediation step: POSTs this command (+ context) to a webhook.
    action_command: str | None = Field(default=None, max_length=500)


class EscalationStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    step_order: int
    delay_minutes: int
    channel_id: uuid.UUID
    action_command: str | None


class EscalationPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_enabled: bool = True
    steps: list[EscalationStepCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_step_orders(self) -> EscalationPolicyCreate:
        orders = [s.step_order for s in self.steps]
        if len(set(orders)) != len(orders):
            raise ValueError("step_order values must be unique")
        return self


class EscalationPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_enabled: bool
    steps: list[EscalationStepRead]
    created_at: datetime
    updated_at: datetime
