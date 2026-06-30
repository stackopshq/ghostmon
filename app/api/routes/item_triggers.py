import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DBSession
from app.core.models.trigger import Trigger
from app.core.schemas.trigger import ItemTriggerCreate, TriggerRead, TriggerUpdate
from app.core.services.host_service import HostService, ItemService
from app.core.services.trigger_service import TriggerService

router = APIRouter(prefix="/hosts/{host_id}/items/{item_id}/triggers", tags=["item-triggers"])


async def _ensure_owned_item(
    session: DBSession, host_id: uuid.UUID, item_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    if await HostService(session).get(host_id, owner_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")
    if await ItemService(session).get(item_id, host_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")


async def _get_trigger_or_404(
    service: TriggerService, trigger_id: uuid.UUID, item_id: uuid.UUID
) -> Trigger:
    trigger = await service.get_for_item(trigger_id, item_id)
    if trigger is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trigger not found")
    return trigger


@router.get("", response_model=list[TriggerRead], summary="List an item's triggers")
async def list_item_triggers(
    host_id: uuid.UUID, item_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> list[TriggerRead]:
    await _ensure_owned_item(session, host_id, item_id, current_user.id)
    triggers = await TriggerService(session).list_for_item(item_id)
    return [TriggerRead.model_validate(t) for t in triggers]


@router.post(
    "",
    response_model=TriggerRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a threshold trigger on an item",
)
async def create_item_trigger(
    host_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ItemTriggerCreate,
    session: DBSession,
    current_user: CurrentUser,
) -> TriggerRead:
    await _ensure_owned_item(session, host_id, item_id, current_user.id)
    trigger = await TriggerService(session).create_for_item(item_id, payload)
    return TriggerRead.model_validate(trigger)


@router.patch("/{trigger_id}", response_model=TriggerRead, summary="Update an item trigger")
async def update_item_trigger(
    host_id: uuid.UUID,
    item_id: uuid.UUID,
    trigger_id: uuid.UUID,
    payload: TriggerUpdate,
    session: DBSession,
    current_user: CurrentUser,
) -> TriggerRead:
    await _ensure_owned_item(session, host_id, item_id, current_user.id)
    service = TriggerService(session)
    trigger = await _get_trigger_or_404(service, trigger_id, item_id)
    return TriggerRead.model_validate(await service.update(trigger, payload))


@router.delete(
    "/{trigger_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an item trigger",
)
async def delete_item_trigger(
    host_id: uuid.UUID,
    item_id: uuid.UUID,
    trigger_id: uuid.UUID,
    session: DBSession,
    current_user: CurrentUser,
) -> Response:
    await _ensure_owned_item(session, host_id, item_id, current_user.id)
    service = TriggerService(session)
    trigger = await _get_trigger_or_404(service, trigger_id, item_id)
    await service.delete(trigger)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
