from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, TypeAdapter, field_validator

from app.core.models.notification_channel import ChannelType
from app.core.models.trigger import Severity
from app.core.security.field_crypto import REDACTED, decrypt_secret


class EmailChannelConfig(BaseModel):
    type: Literal[ChannelType.EMAIL] = ChannelType.EMAIL
    to: EmailStr


class WebhookChannelConfig(BaseModel):
    type: Literal[ChannelType.WEBHOOK] = ChannelType.WEBHOOK
    url: HttpUrl
    secret: str | None = Field(
        default=None,
        min_length=8,
        description="Optional shared secret; when set, payloads are signed with HMAC-SHA256.",
    )


ChannelConfig = Annotated[
    EmailChannelConfig | WebhookChannelConfig,
    Field(discriminator="type"),
]

_ChannelConfigAdapter: TypeAdapter[EmailChannelConfig | WebhookChannelConfig] = TypeAdapter(
    ChannelConfig
)


def parse_channel_config(data: dict[str, Any]) -> EmailChannelConfig | WebhookChannelConfig:
    return _ChannelConfigAdapter.validate_python(data)


class NotificationChannelBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_enabled: bool = True
    min_severity: Severity = Severity.INFO


class NotificationChannelCreate(NotificationChannelBase):
    config: ChannelConfig


class NotificationChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_enabled: bool | None = None
    min_severity: Severity | None = None
    config: ChannelConfig | None = None


class NotificationChannelRead(NotificationChannelBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: ChannelType
    config: dict[str, Any]
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("config")
    @classmethod
    def _protect_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        # Encrypted at rest: the signing secret is never returned in clear (write-only),
        # while the alert targets are decrypted back for the owner who edits them.
        out = dict(value)
        if out.get("secret"):
            out["secret"] = REDACTED
        for field in ("url", "to"):
            if out.get(field):
                out[field] = decrypt_secret(out[field])
        return out
