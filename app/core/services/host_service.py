from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.host import Host, Item, ItemValueType
from app.core.models.metric_value import MetricValue
from app.core.schemas.host import HostCreate, HostUpdate, ItemCreate, ItemUpdate
from app.core.security.field_crypto import REDACTED, encrypt_secret


def _seal_item_config(config: dict) -> dict:  # type: ignore[type-arg]
    """Encrypt the SNMP community at rest (idempotent)."""
    community = config.get("community")
    if not community or community == REDACTED:
        config.pop("community", None)
    else:
        config["community"] = encrypt_secret(str(community))
    return config


class HostService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_owner(self, owner_id: uuid.UUID) -> Sequence[Host]:
        stmt = select(Host).where(Host.owner_id == owner_id).order_by(Host.created_at.desc())
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, host_id: uuid.UUID, owner_id: uuid.UUID) -> Host | None:
        stmt = select(Host).where(Host.id == host_id, Host.owner_id == owner_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, owner_id: uuid.UUID, name: str) -> Host | None:
        stmt = select(Host).where(Host.owner_id == owner_id, Host.name == name)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, data: HostCreate, owner_id: uuid.UUID) -> Host:
        host = Host(
            name=data.name,
            description=data.description,
            address=data.address,
            is_enabled=data.is_enabled,
            owner_id=owner_id,
        )
        self._session.add(host)
        await self._session.commit()
        await self._session.refresh(host)
        return host

    async def update(self, host: Host, data: HostUpdate) -> Host:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(host, field, value)
        await self._session.commit()
        await self._session.refresh(host)
        return host

    async def delete(self, host: Host) -> None:
        await self._session.delete(host)
        await self._session.commit()


def _split_value(value_type: ItemValueType, value: float | str) -> tuple[float | None, str | None]:
    """Route an ingested value to the numeric or text column based on item type."""
    if value_type.is_numeric:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"item expects a numeric value, got {value!r}")
        return float(value), None
    return None, str(value)


class ItemService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_host(self, host_id: uuid.UUID) -> Sequence[Item]:
        stmt = select(Item).where(Item.host_id == host_id).order_by(Item.created_at.desc())
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, item_id: uuid.UUID, host_id: uuid.UUID) -> Item | None:
        stmt = select(Item).where(Item.id == item_id, Item.host_id == host_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_key(self, host_id: uuid.UUID, key: str) -> Item | None:
        stmt = select(Item).where(Item.host_id == host_id, Item.key == key)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, host_id: uuid.UUID, data: ItemCreate) -> Item:
        item = Item(
            host_id=host_id,
            key=data.key,
            name=data.name,
            value_type=data.value_type,
            units=data.units,
            interval=data.interval,
            source=data.source,
            config=_seal_item_config(dict(data.config)),
            is_enabled=data.is_enabled,
            is_private=data.is_private,
        )
        self._session.add(item)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def update(self, item: Item, data: ItemUpdate) -> Item:
        payload = data.model_dump(exclude_unset=True)
        if "config" in payload and payload["config"] is not None:
            new_config = dict(payload["config"])
            # Blank or redacted community on update → keep the existing (encrypted) one.
            if new_config.get("community") in (None, "", REDACTED) and item.config.get("community"):
                new_config["community"] = item.config["community"]
            payload["config"] = _seal_item_config(new_config)
        for field, value in payload.items():
            setattr(item, field, value)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def delete(self, item: Item) -> None:
        await self._session.delete(item)
        await self._session.commit()

    async def record_value(
        self, item: Item, value: float | str, collected_at: datetime | None = None
    ) -> MetricValue:
        value_num: float | None
        value_text: str | None
        if item.is_private:
            # Zero-knowledge: store the client-encrypted token verbatim, opaque.
            value_num, value_text = None, str(value)
        else:
            value_num, value_text = _split_value(item.value_type, value)
        sample = MetricValue(
            item_id=item.id,
            value_num=value_num,
            value_text=value_text,
            collected_at=collected_at or datetime.now(UTC),
        )
        self._session.add(sample)
        await self._session.commit()
        await self._session.refresh(sample)
        return sample

    async def list_values(self, item_id: uuid.UUID, limit: int = 100) -> Sequence[MetricValue]:
        stmt = (
            select(MetricValue)
            .where(MetricValue.item_id == item_id)
            .order_by(MetricValue.collected_at.desc())
            .limit(limit)
        )
        return (await self._session.execute(stmt)).scalars().all()
