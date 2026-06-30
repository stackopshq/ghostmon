import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DBSession
from app.core.schemas.discovery import DiscoveryRuleCreate, DiscoveryRuleRead
from app.core.services.discovery_service import DiscoveryService
from app.core.services.template_service import TemplateService

router = APIRouter(prefix="/discovery-rules", tags=["discovery"])


async def _validate_template(
    session: DBSession, owner_id: uuid.UUID, payload: DiscoveryRuleCreate
) -> None:
    if payload.template_id is not None:
        if await TemplateService(session).get(payload.template_id, owner_id) is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="unknown or unowned template",
            )


@router.get("", response_model=list[DiscoveryRuleRead], summary="List discovery rules")
async def list_rules(session: DBSession, current_user: CurrentUser) -> list[DiscoveryRuleRead]:
    rules = await DiscoveryService(session).list_for_owner(current_user.id)
    return [DiscoveryRuleRead.model_validate(r) for r in rules]


@router.post(
    "",
    response_model=DiscoveryRuleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a discovery rule",
)
async def create_rule(
    payload: DiscoveryRuleCreate, session: DBSession, current_user: CurrentUser
) -> DiscoveryRuleRead:
    await _validate_template(session, current_user.id, payload)
    rule = await DiscoveryService(session).create(current_user.id, payload)
    return DiscoveryRuleRead.model_validate(rule)


@router.get("/{rule_id}", response_model=DiscoveryRuleRead, summary="Retrieve a discovery rule")
async def get_rule(
    rule_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> DiscoveryRuleRead:
    rule = await DiscoveryService(session).get(rule_id, current_user.id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return DiscoveryRuleRead.model_validate(rule)


@router.post(
    "/{rule_id}/scan",
    summary="Scan a discovery rule now and provision newly-reachable hosts",
)
async def scan_rule_now(
    rule_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> dict[str, int]:
    service = DiscoveryService(session)
    rule = await service.get(rule_id, current_user.id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    created = await service.scan_rule(rule, datetime.now(UTC))
    return {"discovered": created}


@router.delete(
    "/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a discovery rule"
)
async def delete_rule(
    rule_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> Response:
    service = DiscoveryService(session)
    rule = await service.get(rule_id, current_user.id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    await service.delete(rule)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
