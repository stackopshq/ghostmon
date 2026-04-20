from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DBSession
from app.core.models.notification_channel import NotificationChannel
from app.core.schemas.notification_channel import (
    NotificationChannelCreate,
    NotificationChannelRead,
    NotificationChannelUpdate,
)
from app.core.services.notification_channel_service import NotificationChannelService
from app.tasks.notifications.dispatcher import send_test_notification

router = APIRouter(prefix="/channels", tags=["channels"])


async def _get_owned_or_404(
    service: NotificationChannelService, channel_id: uuid.UUID, owner_id: uuid.UUID
) -> NotificationChannel:
    channel = await service.get(channel_id, owner_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return channel


@router.get(
    "",
    response_model=list[NotificationChannelRead],
    summary="List notification channels for the authenticated user",
)
async def list_channels(
    session: DBSession, current_user: CurrentUser
) -> list[NotificationChannelRead]:
    channels = await NotificationChannelService(session).list_for_owner(current_user.id)
    return [NotificationChannelRead.model_validate(c) for c in channels]


@router.post(
    "",
    response_model=NotificationChannelRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a notification channel",
)
async def create_channel(
    payload: NotificationChannelCreate,
    session: DBSession,
    current_user: CurrentUser,
) -> NotificationChannelRead:
    try:
        channel = await NotificationChannelService(session).create(payload, current_user.id)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Channel name already exists: {payload.name}",
        ) from exc
    return NotificationChannelRead.model_validate(channel)


@router.get(
    "/{channel_id}",
    response_model=NotificationChannelRead,
    summary="Retrieve a notification channel",
)
async def get_channel(
    channel_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> NotificationChannelRead:
    service = NotificationChannelService(session)
    channel = await _get_owned_or_404(service, channel_id, current_user.id)
    return NotificationChannelRead.model_validate(channel)


@router.patch(
    "/{channel_id}",
    response_model=NotificationChannelRead,
    summary="Partially update a notification channel",
)
async def update_channel(
    channel_id: uuid.UUID,
    payload: NotificationChannelUpdate,
    session: DBSession,
    current_user: CurrentUser,
) -> NotificationChannelRead:
    service = NotificationChannelService(session)
    channel = await _get_owned_or_404(service, channel_id, current_user.id)
    try:
        updated = await service.update(channel, payload)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Channel name conflict",
        ) from exc
    return NotificationChannelRead.model_validate(updated)


@router.delete(
    "/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a notification channel",
)
async def delete_channel(
    channel_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> Response:
    service = NotificationChannelService(session)
    channel = await _get_owned_or_404(service, channel_id, current_user.id)
    await service.delete(channel)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{channel_id}/test",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a test notification via this channel",
)
async def test_channel(
    channel_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> dict[str, str]:
    service = NotificationChannelService(session)
    channel = await _get_owned_or_404(service, channel_id, current_user.id)
    await send_test_notification(channel)
    return {"status": "sent"}
