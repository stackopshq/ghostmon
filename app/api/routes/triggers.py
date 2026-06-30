import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DBSession
from app.core.models.trigger import Trigger
from app.core.schemas.trigger import TriggerCreate, TriggerRead, TriggerUpdate
from app.core.services.monitor_service import MonitorService
from app.core.services.trigger_service import TriggerService

router = APIRouter(prefix="/monitors/{monitor_id}/triggers", tags=["triggers"])


async def _ensure_owned_monitor(
    session: DBSession, monitor_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    if await MonitorService(session).get(monitor_id, owner_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")


async def _get_trigger_or_404(
    service: TriggerService, trigger_id: uuid.UUID, monitor_id: uuid.UUID
) -> Trigger:
    trigger = await service.get(trigger_id, monitor_id)
    if trigger is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trigger not found")
    return trigger


@router.get("", response_model=list[TriggerRead], summary="List a monitor's triggers")
async def list_triggers(
    monitor_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> list[TriggerRead]:
    await _ensure_owned_monitor(session, monitor_id, current_user.id)
    triggers = await TriggerService(session).list_for_monitor(monitor_id)
    return [TriggerRead.model_validate(t) for t in triggers]


@router.post(
    "",
    response_model=TriggerRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a threshold trigger on a monitor",
)
async def create_trigger(
    monitor_id: uuid.UUID,
    payload: TriggerCreate,
    session: DBSession,
    current_user: CurrentUser,
) -> TriggerRead:
    await _ensure_owned_monitor(session, monitor_id, current_user.id)
    trigger = await TriggerService(session).create(monitor_id, payload)
    return TriggerRead.model_validate(trigger)


@router.get("/{trigger_id}", response_model=TriggerRead, summary="Retrieve a trigger")
async def get_trigger(
    monitor_id: uuid.UUID,
    trigger_id: uuid.UUID,
    session: DBSession,
    current_user: CurrentUser,
) -> TriggerRead:
    await _ensure_owned_monitor(session, monitor_id, current_user.id)
    service = TriggerService(session)
    trigger = await _get_trigger_or_404(service, trigger_id, monitor_id)
    return TriggerRead.model_validate(trigger)


@router.patch("/{trigger_id}", response_model=TriggerRead, summary="Update a trigger")
async def update_trigger(
    monitor_id: uuid.UUID,
    trigger_id: uuid.UUID,
    payload: TriggerUpdate,
    session: DBSession,
    current_user: CurrentUser,
) -> TriggerRead:
    await _ensure_owned_monitor(session, monitor_id, current_user.id)
    service = TriggerService(session)
    trigger = await _get_trigger_or_404(service, trigger_id, monitor_id)
    updated = await service.update(trigger, payload)
    return TriggerRead.model_validate(updated)


@router.delete(
    "/{trigger_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a trigger",
)
async def delete_trigger(
    monitor_id: uuid.UUID,
    trigger_id: uuid.UUID,
    session: DBSession,
    current_user: CurrentUser,
) -> Response:
    await _ensure_owned_monitor(session, monitor_id, current_user.id)
    service = TriggerService(session)
    trigger = await _get_trigger_or_404(service, trigger_id, monitor_id)
    await service.delete(trigger)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
