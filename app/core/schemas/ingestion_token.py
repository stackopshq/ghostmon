from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.models.host import ItemValueType


class IngestionTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class IngestionTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    last_used_at: datetime | None
    created_at: datetime


class IngestionTokenCreated(IngestionTokenRead):
    # The plaintext secret, returned only once at creation.
    token: str


class IngestPayload(BaseModel):
    """An agent pushing one sample. The host must exist; a missing item is
    auto-created (a "trapper" item) using `value_type` (or inferred from `value`)."""

    host: str = Field(min_length=1, max_length=255)
    key: str = Field(min_length=1, max_length=255)
    value: float | str
    value_type: ItemValueType | None = None
    units: str | None = Field(default=None, max_length=32)
    collected_at: datetime | None = None
