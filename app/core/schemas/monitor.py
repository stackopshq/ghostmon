import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.models.monitor import MonitorStatus, MonitorType


class MonitorBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: MonitorType
    url: str = Field(min_length=1, max_length=2048)
    interval: int = Field(default=60, ge=10, le=86400)
    retries: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Consecutive probe failures tolerated before flipping to DOWN.",
    )
    retry_interval: int = Field(
        default=20,
        ge=5,
        le=3600,
        description="Seconds to wait between retry probes after a failure.",
    )


class MonitorCreate(MonitorBase):
    pass


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    type: MonitorType | None = None
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    interval: int | None = Field(default=None, ge=10, le=86400)
    retries: int | None = Field(default=None, ge=0, le=10)
    retry_interval: int | None = Field(default=None, ge=5, le=3600)
    status: MonitorStatus | None = None


class MonitorRead(MonitorBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: MonitorStatus
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    is_under_maintenance: bool = False
