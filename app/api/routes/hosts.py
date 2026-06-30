import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.core.models.host import Host, Item
from app.core.schemas.host import (
    HostCreate,
    HostRead,
    HostUpdate,
    ItemCreate,
    ItemRead,
    ItemUpdate,
    MetricValueIngest,
    MetricValueRead,
)
from app.core.schemas.notification_channel import NotificationChannelRead
from app.core.services.host_service import HostService, ItemService
from app.core.services.notification_channel_service import NotificationChannelService

router = APIRouter(prefix="/hosts", tags=["hosts"])


async def _get_host_or_404(session: DBSession, host_id: uuid.UUID, owner_id: uuid.UUID) -> Host:
    host = await HostService(session).get(host_id, owner_id)
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")
    return host


async def _get_item_or_404(session: DBSession, item_id: uuid.UUID, host_id: uuid.UUID) -> Item:
    item = await ItemService(session).get(item_id, host_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


# ── Hosts ───────────────────────────────────────────────────────────────────


@router.get("", response_model=list[HostRead], summary="List hosts")
async def list_hosts(session: DBSession, current_user: CurrentUser) -> list[HostRead]:
    hosts = await HostService(session).list_for_owner(current_user.id)
    return [HostRead.model_validate(h) for h in hosts]


@router.post(
    "", response_model=HostRead, status_code=status.HTTP_201_CREATED, summary="Create host"
)
async def create_host(
    payload: HostCreate, session: DBSession, current_user: CurrentUser
) -> HostRead:
    host = await HostService(session).create(payload, current_user.id)
    return HostRead.model_validate(host)


@router.get("/{host_id}", response_model=HostRead, summary="Retrieve a host")
async def get_host(host_id: uuid.UUID, session: DBSession, current_user: CurrentUser) -> HostRead:
    return HostRead.model_validate(await _get_host_or_404(session, host_id, current_user.id))


@router.patch("/{host_id}", response_model=HostRead, summary="Update a host")
async def update_host(
    host_id: uuid.UUID, payload: HostUpdate, session: DBSession, current_user: CurrentUser
) -> HostRead:
    host = await _get_host_or_404(session, host_id, current_user.id)
    return HostRead.model_validate(await HostService(session).update(host, payload))


@router.delete("/{host_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a host")
async def delete_host(
    host_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> Response:
    host = await _get_host_or_404(session, host_id, current_user.id)
    await HostService(session).delete(host)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Items ───────────────────────────────────────────────────────────────────


@router.get("/{host_id}/items", response_model=list[ItemRead], summary="List a host's items")
async def list_items(
    host_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> list[ItemRead]:
    await _get_host_or_404(session, host_id, current_user.id)
    items = await ItemService(session).list_for_host(host_id)
    return [ItemRead.model_validate(i) for i in items]


@router.post(
    "/{host_id}/items",
    response_model=ItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an item on a host",
)
async def create_item(
    host_id: uuid.UUID, payload: ItemCreate, session: DBSession, current_user: CurrentUser
) -> ItemRead:
    await _get_host_or_404(session, host_id, current_user.id)
    item = await ItemService(session).create(host_id, payload)
    return ItemRead.model_validate(item)


@router.patch("/{host_id}/items/{item_id}", response_model=ItemRead, summary="Update an item")
async def update_item(
    host_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ItemUpdate,
    session: DBSession,
    current_user: CurrentUser,
) -> ItemRead:
    await _get_host_or_404(session, host_id, current_user.id)
    item = await _get_item_or_404(session, item_id, host_id)
    return ItemRead.model_validate(await ItemService(session).update(item, payload))


@router.delete(
    "/{host_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an item",
)
async def delete_item(
    host_id: uuid.UUID, item_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> Response:
    await _get_host_or_404(session, host_id, current_user.id)
    item = await _get_item_or_404(session, item_id, host_id)
    await ItemService(session).delete(item)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Metric history ──────────────────────────────────────────────────────────


@router.post(
    "/{host_id}/items/{item_id}/values",
    response_model=MetricValueRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a metric sample for an item",
)
async def ingest_value(
    host_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: MetricValueIngest,
    session: DBSession,
    current_user: CurrentUser,
) -> MetricValueRead:
    await _get_host_or_404(session, host_id, current_user.id)
    item = await _get_item_or_404(session, item_id, host_id)
    try:
        sample = await ItemService(session).record_value(item, payload.value, payload.collected_at)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return MetricValueRead.model_validate(sample)


@router.get(
    "/{host_id}/items/{item_id}/values",
    response_model=list[MetricValueRead],
    summary="Read recent samples for an item (newest first)",
)
async def list_values(
    host_id: uuid.UUID,
    item_id: uuid.UUID,
    session: DBSession,
    current_user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[MetricValueRead]:
    await _get_host_or_404(session, host_id, current_user.id)
    await _get_item_or_404(session, item_id, host_id)
    values = await ItemService(session).list_values(item_id, limit=limit)
    return [MetricValueRead.model_validate(v) for v in values]


# ── Notification channels ───────────────────────────────────────────────────


class AttachChannelPayload(BaseModel):
    channel_id: uuid.UUID


@router.get(
    "/{host_id}/channels",
    response_model=list[NotificationChannelRead],
    summary="List channels attached to a host",
)
async def list_host_channels(
    host_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> list[NotificationChannelRead]:
    await _get_host_or_404(session, host_id, current_user.id)
    channels = await NotificationChannelService(session).channels_for_host(host_id)
    return [NotificationChannelRead.model_validate(c) for c in channels]


@router.post(
    "/{host_id}/channels",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Attach a notification channel to a host",
)
async def attach_host_channel(
    host_id: uuid.UUID,
    payload: AttachChannelPayload,
    session: DBSession,
    current_user: CurrentUser,
) -> Response:
    await _get_host_or_404(session, host_id, current_user.id)
    channel_svc = NotificationChannelService(session)
    if await channel_svc.get(payload.channel_id, current_user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await channel_svc.attach_host(host_id, payload.channel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{host_id}/channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a notification channel from a host",
)
async def detach_host_channel(
    host_id: uuid.UUID,
    channel_id: uuid.UUID,
    session: DBSession,
    current_user: CurrentUser,
) -> Response:
    await _get_host_or_404(session, host_id, current_user.id)
    channel_svc = NotificationChannelService(session)
    if await channel_svc.get(channel_id, current_user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await channel_svc.detach_host(host_id, channel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
