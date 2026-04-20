from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.core.models.maintenance import Maintenance
from app.core.schemas.maintenance import (
    MaintenanceCreate,
    MaintenanceRead,
    MaintenanceUpdate,
)
from app.core.services.maintenance_service import MaintenanceService
from app.core.services.monitor_service import MonitorService

router = APIRouter(prefix="/maintenances", tags=["maintenances"])


async def _get_owned_or_404(
    service: MaintenanceService, maintenance_id: uuid.UUID, owner_id: uuid.UUID
) -> Maintenance:
    maintenance = await service.get(maintenance_id, owner_id)
    if maintenance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance not found")
    return maintenance


@router.get("", response_model=list[MaintenanceRead], summary="List maintenance windows")
async def list_maintenances(session: DBSession, current_user: CurrentUser) -> list[MaintenanceRead]:
    items = await MaintenanceService(session).list_for_owner(current_user.id)
    return [MaintenanceRead.model_validate(m) for m in items]


@router.post(
    "",
    response_model=MaintenanceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a maintenance window",
)
async def create_maintenance(
    payload: MaintenanceCreate, session: DBSession, current_user: CurrentUser
) -> MaintenanceRead:
    maintenance = await MaintenanceService(session).create(payload, current_user.id)
    return MaintenanceRead.model_validate(maintenance)


@router.get(
    "/{maintenance_id}",
    response_model=MaintenanceRead,
    summary="Retrieve a maintenance window",
)
async def get_maintenance(
    maintenance_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> MaintenanceRead:
    service = MaintenanceService(session)
    maintenance = await _get_owned_or_404(service, maintenance_id, current_user.id)
    return MaintenanceRead.model_validate(maintenance)


@router.patch(
    "/{maintenance_id}",
    response_model=MaintenanceRead,
    summary="Partially update a maintenance window",
)
async def update_maintenance(
    maintenance_id: uuid.UUID,
    payload: MaintenanceUpdate,
    session: DBSession,
    current_user: CurrentUser,
) -> MaintenanceRead:
    service = MaintenanceService(session)
    maintenance = await _get_owned_or_404(service, maintenance_id, current_user.id)
    updated = await service.update(maintenance, payload)
    return MaintenanceRead.model_validate(updated)


@router.delete(
    "/{maintenance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a maintenance window",
)
async def delete_maintenance(
    maintenance_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> Response:
    service = MaintenanceService(session)
    maintenance = await _get_owned_or_404(service, maintenance_id, current_user.id)
    await service.delete(maintenance)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class AttachMonitorPayload(BaseModel):
    monitor_id: uuid.UUID


@router.post(
    "/{maintenance_id}/monitors",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Attach a monitor to a maintenance window",
)
async def attach_monitor(
    maintenance_id: uuid.UUID,
    payload: AttachMonitorPayload,
    session: DBSession,
    current_user: CurrentUser,
) -> Response:
    maint_svc = MaintenanceService(session)
    await _get_owned_or_404(maint_svc, maintenance_id, current_user.id)
    monitor_svc = MonitorService(session)
    if await monitor_svc.get(payload.monitor_id, current_user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    await maint_svc.attach_monitor(maintenance_id, payload.monitor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{maintenance_id}/monitors/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a monitor from a maintenance window",
)
async def detach_monitor(
    maintenance_id: uuid.UUID,
    monitor_id: uuid.UUID,
    session: DBSession,
    current_user: CurrentUser,
) -> Response:
    maint_svc = MaintenanceService(session)
    await _get_owned_or_404(maint_svc, maintenance_id, current_user.id)
    monitor_svc = MonitorService(session)
    if await monitor_svc.get(monitor_id, current_user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    await maint_svc.detach_monitor(maintenance_id, monitor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
