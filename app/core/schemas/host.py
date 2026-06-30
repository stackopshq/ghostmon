from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.models.host import ItemSource, ItemValueType
from app.core.security.field_crypto import REDACTED


class HostBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    address: str | None = Field(default=None, max_length=255)
    is_enabled: bool = True


class HostCreate(HostBase):
    pass


class HostUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    address: str | None = Field(default=None, max_length=255)
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
    source: ItemSource = ItemSource.TRAPPER
    config: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True
    is_private: bool = False


class ItemCreate(ItemBase):
    pass


class ItemUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    value_type: ItemValueType | None = None
    units: str | None = Field(default=None, max_length=32)
    interval: int | None = Field(default=None, ge=1, le=86400)
    source: ItemSource | None = None
    config: dict[str, Any] | None = None
    is_enabled: bool | None = None
    is_private: bool | None = None


class ItemRead(ItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    host_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("config")
    @classmethod
    def _redact_community(cls, value: dict[str, Any]) -> dict[str, Any]:
        # The SNMP community is encrypted at rest and never returned in clear.
        if value.get("community"):
            return {**value, "community": REDACTED}
        return value


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
