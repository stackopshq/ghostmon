from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.models.host import ItemValueType


class HostBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    is_enabled: bool = True


class HostCreate(HostBase):
    pass


class HostUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_enabled: bool | None = None


class HostRead(HostBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ItemBase(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    value_type: ItemValueType
    units: str | None = Field(default=None, max_length=32)
    interval: int = Field(default=60, ge=1, le=86400)
    is_enabled: bool = True


class ItemCreate(ItemBase):
    pass


class ItemUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    value_type: ItemValueType | None = None
    units: str | None = Field(default=None, max_length=32)
    interval: int | None = Field(default=None, ge=1, le=86400)
    is_enabled: bool | None = None


class ItemRead(ItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    host_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MetricValueIngest(BaseModel):
    """Push a single sample for an item. `value` is numeric or text depending on
    the item's value_type; `collected_at` defaults to now when omitted."""

    value: float | str
    collected_at: datetime | None = None


class MetricValueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    value_num: float | None
    value_text: str | None
    collected_at: datetime
