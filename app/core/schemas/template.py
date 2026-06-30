from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.models.host import ItemValueType


class TemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class TemplateCreate(TemplateBase):
    pass


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class TemplateRead(TemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class TemplateItemBase(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    value_type: ItemValueType
    units: str | None = Field(default=None, max_length=32)
    interval: int = Field(default=60, ge=1, le=86400)


class TemplateItemCreate(TemplateItemBase):
    pass


class TemplateItemRead(TemplateItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID


class TemplateApply(BaseModel):
    host_id: uuid.UUID


class TemplateApplyResult(BaseModel):
    created: int
    skipped: int
