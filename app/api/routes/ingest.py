import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DBSession, IngestOwner
from app.core.models.host import ItemValueType
from app.core.schemas.host import ItemCreate, MetricValueRead
from app.core.schemas.ingestion_token import (
    IngestionTokenCreate,
    IngestionTokenCreated,
    IngestionTokenRead,
    IngestPayload,
)
from app.core.services.host_service import HostService, ItemService
from app.core.services.ingestion_token_service import IngestionTokenService

router = APIRouter(tags=["ingest"])


# ── Token management (user-authenticated) ───────────────────────────────────


@router.get("/ingest-tokens", response_model=list[IngestionTokenRead], summary="List ingest tokens")
async def list_tokens(session: DBSession, current_user: CurrentUser) -> list[IngestionTokenRead]:
    tokens = await IngestionTokenService(session).list_for_owner(current_user.id)
    return [IngestionTokenRead.model_validate(t) for t in tokens]


@router.post(
    "/ingest-tokens",
    response_model=IngestionTokenCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create an ingest token (the secret is returned only once)",
)
async def create_token(
    payload: IngestionTokenCreate, session: DBSession, current_user: CurrentUser
) -> IngestionTokenCreated:
    token, plaintext = await IngestionTokenService(session).create(current_user.id, payload.name)
    read = IngestionTokenRead.model_validate(token)
    return IngestionTokenCreated(**read.model_dump(), token=plaintext)


@router.delete(
    "/ingest-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an ingest token",
)
async def delete_token(
    token_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> Response:
    service = IngestionTokenService(session)
    token = await service.get(token_id, current_user.id)
    if token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    await service.delete(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Ingestion (token-authenticated) ─────────────────────────────────────────


@router.post(
    "/ingest",
    response_model=MetricValueRead,
    status_code=status.HTTP_201_CREATED,
    summary="Push a metric sample for a host item (agent-facing, token auth)",
)
async def ingest(payload: IngestPayload, session: DBSession, owner: IngestOwner) -> MetricValueRead:
    host = await HostService(session).get_by_name(owner.id, payload.host)
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")

    item_svc = ItemService(session)
    item = await item_svc.get_by_key(host.id, payload.key)
    if item is None:
        # Trapper item: auto-created on first push, type inferred when not given.
        value_type = payload.value_type or (
            ItemValueType.FLOAT
            if isinstance(payload.value, int | float) and not isinstance(payload.value, bool)
            else ItemValueType.TEXT
        )
        item = await item_svc.create(
            host.id,
            ItemCreate(
                key=payload.key, name=payload.key, value_type=value_type, units=payload.units
            ),
        )

    try:
        sample = await item_svc.record_value(item, payload.value, payload.collected_at)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return MetricValueRead.model_validate(sample)
