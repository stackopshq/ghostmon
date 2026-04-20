import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.models.monitor import MonitorStatus, MonitorType


class MonitorBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: MonitorType
    url: str = Field(min_length=1, max_length=2048)
    interval: int = Field(default=60, ge=10, le=86400)


class MonitorCreate(MonitorBase):
    pass


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    type: MonitorType | None = None
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    interval: int | None = Field(default=None, ge=10, le=86400)
    status: MonitorStatus | None = None


class MonitorRead(MonitorBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: MonitorStatus
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
