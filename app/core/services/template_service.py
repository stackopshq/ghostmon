from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.host import Host, Item
from app.core.models.template import Template, TemplateItem
from app.core.schemas.template import (
    TemplateApplyResult,
    TemplateCreate,
    TemplateItemCreate,
    TemplateUpdate,
)


class TemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_owner(self, owner_id: uuid.UUID) -> Sequence[Template]:
        stmt = (
            select(Template)
            .where(Template.owner_id == owner_id)
            .order_by(Template.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, template_id: uuid.UUID, owner_id: uuid.UUID) -> Template | None:
        stmt = select(Template).where(Template.id == template_id, Template.owner_id == owner_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, data: TemplateCreate, owner_id: uuid.UUID) -> Template:
        template = Template(name=data.name, description=data.description, owner_id=owner_id)
        self._session.add(template)
        await self._session.commit()
        await self._session.refresh(template)
        return template

    async def update(self, template: Template, data: TemplateUpdate) -> Template:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(template, field, value)
        await self._session.commit()
        await self._session.refresh(template)
        return template

    async def delete(self, template: Template) -> None:
        await self._session.delete(template)
        await self._session.commit()

    async def list_items(self, template_id: uuid.UUID) -> Sequence[TemplateItem]:
        stmt = (
            select(TemplateItem)
            .where(TemplateItem.template_id == template_id)
            .order_by(TemplateItem.key)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get_item(self, item_id: uuid.UUID, template_id: uuid.UUID) -> TemplateItem | None:
        stmt = select(TemplateItem).where(
            TemplateItem.id == item_id, TemplateItem.template_id == template_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add_item(self, template_id: uuid.UUID, data: TemplateItemCreate) -> TemplateItem:
        item = TemplateItem(
            template_id=template_id,
            key=data.key,
            name=data.name,
            value_type=data.value_type,
            units=data.units,
            interval=data.interval,
        )
        self._session.add(item)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def delete_item(self, item: TemplateItem) -> None:
        await self._session.delete(item)
        await self._session.commit()

    async def apply_to_host(self, template_id: uuid.UUID, host: Host) -> TemplateApplyResult:
        """Create the template's items on the host. Items whose key already exists
        on the host are left untouched (idempotent re-apply)."""
        template_items = await self.list_items(template_id)
        existing_keys = set(
            (await self._session.execute(select(Item.key).where(Item.host_id == host.id))).scalars()
        )

        created = 0
        for template_item in template_items:
            if template_item.key in existing_keys:
                continue
            self._session.add(
                Item(
                    host_id=host.id,
                    key=template_item.key,
                    name=template_item.name,
                    value_type=template_item.value_type,
                    units=template_item.units,
                    interval=template_item.interval,
                )
            )
            created += 1

        if created:
            await self._session.commit()
        return TemplateApplyResult(created=created, skipped=len(template_items) - created)
