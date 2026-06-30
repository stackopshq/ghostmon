from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.models.monitor import Monitor
from app.core.models.notification_channel import (
    NotificationChannel,
    host_channels,
    monitor_channels,
)
from app.core.schemas.notification_channel import (
    NotificationChannelCreate,
    NotificationChannelUpdate,
)
from app.core.security.field_crypto import REDACTED, encrypt_secret


def _seal_channel_config(config: dict) -> dict:  # type: ignore[type-arg]
    """Encrypt the webhook signing secret at rest (idempotent)."""
    secret = config.get("secret")
    if not secret or secret == REDACTED:
        config.pop("secret", None)
    else:
        config["secret"] = encrypt_secret(str(secret))
    return config


class NotificationChannelService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_owner(self, owner_id: uuid.UUID) -> Sequence[NotificationChannel]:
        stmt = (
            select(NotificationChannel)
            .where(NotificationChannel.owner_id == owner_id)
            .order_by(NotificationChannel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get(self, channel_id: uuid.UUID, owner_id: uuid.UUID) -> NotificationChannel | None:
        stmt = select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.owner_id == owner_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self, data: NotificationChannelCreate, owner_id: uuid.UUID
    ) -> NotificationChannel:
        channel = NotificationChannel(
            name=data.name,
            type=data.config.type,
            config=_seal_channel_config(data.config.model_dump(mode="json", exclude={"type"})),
            is_enabled=data.is_enabled,
            min_severity=data.min_severity,
            owner_id=owner_id,
        )
        self._session.add(channel)
        await self._session.commit()
        await self._session.refresh(channel)
        return channel

    async def update(
        self, channel: NotificationChannel, data: NotificationChannelUpdate
    ) -> NotificationChannel:
        payload = data.model_dump(exclude_unset=True)
        if "name" in payload:
            channel.name = payload["name"]
        if "is_enabled" in payload:
            channel.is_enabled = payload["is_enabled"]
        if "min_severity" in payload:
            channel.min_severity = payload["min_severity"]
        if data.config is not None:
            new_config = data.config.model_dump(mode="json", exclude={"type"})
            # Blank or redacted secret on update → keep the existing (encrypted) one.
            if new_config.get("secret") in (None, "", REDACTED) and channel.config.get("secret"):
                new_config["secret"] = channel.config["secret"]
            channel.type = data.config.type
            channel.config = _seal_channel_config(new_config)
        await self._session.commit()
        await self._session.refresh(channel)
        return channel

    async def delete(self, channel: NotificationChannel) -> None:
        await self._session.delete(channel)
        await self._session.commit()

    async def attach(self, monitor_id: uuid.UUID, channel_id: uuid.UUID) -> None:
        stmt = (
            pg_insert(monitor_channels)
            .values(monitor_id=monitor_id, channel_id=channel_id)
            .on_conflict_do_nothing()
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def detach(self, monitor_id: uuid.UUID, channel_id: uuid.UUID) -> None:
        stmt = delete(monitor_channels).where(
            monitor_channels.c.monitor_id == monitor_id,
            monitor_channels.c.channel_id == channel_id,
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def channels_for_monitor(self, monitor_id: uuid.UUID) -> Sequence[NotificationChannel]:
        stmt = (
            select(NotificationChannel)
            .join(monitor_channels, monitor_channels.c.channel_id == NotificationChannel.id)
            .where(monitor_channels.c.monitor_id == monitor_id)
            .order_by(NotificationChannel.name)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def attach_host(self, host_id: uuid.UUID, channel_id: uuid.UUID) -> None:
        stmt = (
            pg_insert(host_channels)
            .values(host_id=host_id, channel_id=channel_id)
            .on_conflict_do_nothing()
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def detach_host(self, host_id: uuid.UUID, channel_id: uuid.UUID) -> None:
        stmt = delete(host_channels).where(
            host_channels.c.host_id == host_id,
            host_channels.c.channel_id == channel_id,
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def channels_for_host(self, host_id: uuid.UUID) -> Sequence[NotificationChannel]:
        stmt = (
            select(NotificationChannel)
            .join(host_channels, host_channels.c.channel_id == NotificationChannel.id)
            .where(host_channels.c.host_id == host_id)
            .order_by(NotificationChannel.name)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_monitor_with_channels(self, monitor_id: uuid.UUID) -> Monitor | None:
        stmt = (
            select(Monitor).where(Monitor.id == monitor_id).options(selectinload(Monitor.channels))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
