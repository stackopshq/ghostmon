import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DBSession
from app.core.models.template import Template, TemplateItem
from app.core.schemas.template import (
    TemplateApply,
    TemplateApplyResult,
    TemplateCreate,
    TemplateItemCreate,
    TemplateItemRead,
    TemplateRead,
    TemplateUpdate,
)
from app.core.services.host_service import HostService
from app.core.services.template_service import TemplateService

router = APIRouter(prefix="/templates", tags=["templates"])


async def _get_template_or_404(
    session: DBSession, template_id: uuid.UUID, owner_id: uuid.UUID
) -> Template:
    template = await TemplateService(session).get(template_id, owner_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template


async def _get_template_item_or_404(
    service: TemplateService, item_id: uuid.UUID, template_id: uuid.UUID
) -> TemplateItem:
    item = await service.get_item(item_id, template_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template item not found")
    return item


@router.get("", response_model=list[TemplateRead], summary="List templates")
async def list_templates(session: DBSession, current_user: CurrentUser) -> list[TemplateRead]:
    templates = await TemplateService(session).list_for_owner(current_user.id)
    return [TemplateRead.model_validate(t) for t in templates]


@router.post(
    "",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a template",
)
async def create_template(
    payload: TemplateCreate, session: DBSession, current_user: CurrentUser
) -> TemplateRead:
    template = await TemplateService(session).create(payload, current_user.id)
    return TemplateRead.model_validate(template)


@router.get("/{template_id}", response_model=TemplateRead, summary="Retrieve a template")
async def get_template(
    template_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> TemplateRead:
    return TemplateRead.model_validate(
        await _get_template_or_404(session, template_id, current_user.id)
    )


@router.patch("/{template_id}", response_model=TemplateRead, summary="Update a template")
async def update_template(
    template_id: uuid.UUID,
    payload: TemplateUpdate,
    session: DBSession,
    current_user: CurrentUser,
) -> TemplateRead:
    template = await _get_template_or_404(session, template_id, current_user.id)
    return TemplateRead.model_validate(await TemplateService(session).update(template, payload))


@router.delete(
    "/{template_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a template"
)
async def delete_template(
    template_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> Response:
    template = await _get_template_or_404(session, template_id, current_user.id)
    await TemplateService(session).delete(template)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Template items ──────────────────────────────────────────────────────────


@router.get(
    "/{template_id}/items",
    response_model=list[TemplateItemRead],
    summary="List a template's item definitions",
)
async def list_template_items(
    template_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> list[TemplateItemRead]:
    await _get_template_or_404(session, template_id, current_user.id)
    items = await TemplateService(session).list_items(template_id)
    return [TemplateItemRead.model_validate(i) for i in items]


@router.post(
    "/{template_id}/items",
    response_model=TemplateItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an item definition to a template",
)
async def create_template_item(
    template_id: uuid.UUID,
    payload: TemplateItemCreate,
    session: DBSession,
    current_user: CurrentUser,
) -> TemplateItemRead:
    await _get_template_or_404(session, template_id, current_user.id)
    item = await TemplateService(session).add_item(template_id, payload)
    return TemplateItemRead.model_validate(item)


@router.delete(
    "/{template_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an item definition from a template",
)
async def delete_template_item(
    template_id: uuid.UUID,
    item_id: uuid.UUID,
    session: DBSession,
    current_user: CurrentUser,
) -> Response:
    await _get_template_or_404(session, template_id, current_user.id)
    service = TemplateService(session)
    item = await _get_template_item_or_404(service, item_id, template_id)
    await service.delete_item(item)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Apply ───────────────────────────────────────────────────────────────────


@router.post(
    "/{template_id}/apply",
    response_model=TemplateApplyResult,
    summary="Apply a template's items to a host (idempotent)",
)
async def apply_template(
    template_id: uuid.UUID,
    payload: TemplateApply,
    session: DBSession,
    current_user: CurrentUser,
) -> TemplateApplyResult:
    await _get_template_or_404(session, template_id, current_user.id)
    host = await HostService(session).get(payload.host_id, current_user.id)
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")
    return await TemplateService(session).apply_to_host(template_id, host)
