from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.models.trigger import Severity


class ProblemEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trigger_id: uuid.UUID
    subject: str
    trigger_name: str
    severity: Severity
    value: float | None
    started_at: datetime
    resolved_at: datetime | None
    acknowledged_at: datetime | None
    acknowledged_by_id: uuid.UUID | None
