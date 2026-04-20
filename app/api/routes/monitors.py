import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.core.models.monitor import Monitor
from app.core.schemas.monitor import MonitorCreate, MonitorRead, MonitorUpdate
from app.core.schemas.monitor_result import MonitorResultRead
from app.core.schemas.notification_channel import NotificationChannelRead
from app.core.services.maintenance_service import (
    MaintenanceService,
    is_maintenance_active,
)
from app.core.services.monitor_service import MonitorService
from app.core.services.notification_channel_service import NotificationChannelService

router = APIRouter(prefix="/monitors", tags=["monitors"])


async def _get_owned_or_404(
    service: MonitorService, monitor_id: uuid.UUID, owner_id: uuid.UUID
) -> Monitor:
    monitor = await service.get(monitor_id, owner_id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    return monitor


@router.get(
    "",
    response_model=list[MonitorRead],
    status_code=status.HTTP_200_OK,
    summary="List monitors for the authenticated user",
)
async def list_monitors(session: DBSession, current_user: CurrentUser) -> list[MonitorRead]:
    monitors = await MonitorService(session).list_for_owner(current_user.id)
    maintenance_svc = MaintenanceService(session)
    now = datetime.now(UTC)
    reads: list[MonitorRead] = []
    for monitor in monitors:
        flag = False
        for maintenance in await maintenance_svc.active_maintenances_for_monitor(monitor.id):
            if is_maintenance_active(maintenance, now):
                flag = True
                break
        reads.append(
            MonitorRead.model_validate(monitor).model_copy(update={"is_under_maintenance": flag})
        )
    return reads


@router.post(
    "",
    response_model=MonitorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a monitor owned by the authenticated user",
)
async def create_monitor(
    payload: MonitorCreate, session: DBSession, current_user: CurrentUser
) -> MonitorRead:
    monitor = await MonitorService(session).create(payload, current_user.id)
    return MonitorRead.model_validate(monitor)


@router.get(
    "/{monitor_id}",
    response_model=MonitorRead,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a monitor by id",
)
async def get_monitor(
    monitor_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> MonitorRead:
    service = MonitorService(session)
    monitor = await _get_owned_or_404(service, monitor_id, current_user.id)
    flag = await MaintenanceService(session).is_monitor_under_maintenance(monitor.id)
    return MonitorRead.model_validate(monitor).model_copy(update={"is_under_maintenance": flag})


@router.patch(
    "/{monitor_id}",
    response_model=MonitorRead,
    status_code=status.HTTP_200_OK,
    summary="Partially update a monitor",
)
async def update_monitor(
    monitor_id: uuid.UUID,
    payload: MonitorUpdate,
    session: DBSession,
    current_user: CurrentUser,
) -> MonitorRead:
    service = MonitorService(session)
    monitor = await _get_owned_or_404(service, monitor_id, current_user.id)
    updated = await service.update(monitor, payload)
    return MonitorRead.model_validate(updated)


@router.delete(
    "/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a monitor",
)
async def delete_monitor(
    monitor_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> Response:
    service = MonitorService(session)
    monitor = await _get_owned_or_404(service, monitor_id, current_user.id)
    await service.delete(monitor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{monitor_id}/results",
    response_model=list[MonitorResultRead],
    status_code=status.HTTP_200_OK,
    summary="List recent probe results for a monitor (newest first)",
)
async def list_monitor_results(
    monitor_id: uuid.UUID,
    session: DBSession,
    current_user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[MonitorResultRead]:
    service = MonitorService(session)
    await _get_owned_or_404(service, monitor_id, current_user.id)
    results = await service.list_results(monitor_id, limit=limit)
    return [MonitorResultRead.model_validate(r) for r in results]


class AttachChannelPayload(BaseModel):
    channel_id: uuid.UUID


@router.get(
    "/{monitor_id}/channels",
    response_model=list[NotificationChannelRead],
    summary="List channels attached to a monitor",
)
async def list_monitor_channels(
    monitor_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> list[NotificationChannelRead]:
    monitor_svc = MonitorService(session)
    await _get_owned_or_404(monitor_svc, monitor_id, current_user.id)
    channels = await NotificationChannelService(session).channels_for_monitor(monitor_id)
    return [NotificationChannelRead.model_validate(c) for c in channels]


@router.post(
    "/{monitor_id}/channels",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Attach a notification channel to a monitor",
)
async def attach_channel(
    monitor_id: uuid.UUID,
    payload: AttachChannelPayload,
    session: DBSession,
    current_user: CurrentUser,
) -> Response:
    monitor_svc = MonitorService(session)
    channel_svc = NotificationChannelService(session)
    await _get_owned_or_404(monitor_svc, monitor_id, current_user.id)
    channel = await channel_svc.get(payload.channel_id, current_user.id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await channel_svc.attach(monitor_id, payload.channel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{monitor_id}/channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a notification channel from a monitor",
)
async def detach_channel(
    monitor_id: uuid.UUID,
    channel_id: uuid.UUID,
    session: DBSession,
    current_user: CurrentUser,
) -> Response:
    monitor_svc = MonitorService(session)
    channel_svc = NotificationChannelService(session)
    await _get_owned_or_404(monitor_svc, monitor_id, current_user.id)
    # Ownership check: the channel must belong to the same user.
    if await channel_svc.get(channel_id, current_user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await channel_svc.detach(monitor_id, channel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
