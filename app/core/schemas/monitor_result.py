import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.models.monitor_result import ProbeStatus


class MonitorResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    monitor_id: uuid.UUID
    status: ProbeStatus
    latency_ms: int | None
    error: str | None
    checked_at: datetime
