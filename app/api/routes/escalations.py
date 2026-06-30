import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DBSession
from app.core.models.notification_channel import ChannelType
from app.core.schemas.escalation import EscalationPolicyCreate, EscalationPolicyRead
from app.core.services.escalation_service import EscalationService

router = APIRouter(prefix="/escalation-policies", tags=["escalation"])


async def _validate_channels(
    service: EscalationService, owner_id: uuid.UUID, payload: EscalationPolicyCreate
) -> None:
    wanted = {s.channel_id for s in payload.steps}
    owned = await service.channels_owned_by(owner_id, wanted)
    missing = wanted - owned
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown or unowned channel(s): {', '.join(str(m) for m in missing)}",
        )
    # Auto-remediation steps must target a webhook (a machine endpoint).
    remediation_channels = {s.channel_id for s in payload.steps if s.action_command}
    if remediation_channels:
        types = await service.channel_types(owner_id, remediation_channels)
        non_webhook = [cid for cid in remediation_channels if types.get(cid) != ChannelType.WEBHOOK]
        if non_webhook:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="auto-remediation steps must target a webhook channel",
            )


@router.get("", response_model=list[EscalationPolicyRead], summary="List escalation policies")
async def list_policies(
    session: DBSession, current_user: CurrentUser
) -> list[EscalationPolicyRead]:
    policies = await EscalationService(session).list_for_owner(current_user.id)
    return [EscalationPolicyRead.model_validate(p) for p in policies]


@router.post(
    "",
    response_model=EscalationPolicyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an escalation policy",
)
async def create_policy(
    payload: EscalationPolicyCreate, session: DBSession, current_user: CurrentUser
) -> EscalationPolicyRead:
    service = EscalationService(session)
    await _validate_channels(service, current_user.id, payload)
    policy = await service.create(current_user.id, payload)
    return EscalationPolicyRead.model_validate(policy)


@router.get("/{policy_id}", response_model=EscalationPolicyRead, summary="Retrieve a policy")
async def get_policy(
    policy_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> EscalationPolicyRead:
    policy = await EscalationService(session).get(policy_id, current_user.id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    return EscalationPolicyRead.model_validate(policy)


@router.put("/{policy_id}", response_model=EscalationPolicyRead, summary="Replace a policy")
async def replace_policy(
    policy_id: uuid.UUID,
    payload: EscalationPolicyCreate,
    session: DBSession,
    current_user: CurrentUser,
) -> EscalationPolicyRead:
    service = EscalationService(session)
    policy = await service.get(policy_id, current_user.id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    await _validate_channels(service, current_user.id, payload)
    updated = await service.replace(policy, payload)
    return EscalationPolicyRead.model_validate(updated)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a policy")
async def delete_policy(
    policy_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> Response:
    service = EscalationService(session)
    policy = await service.get(policy_id, current_user.id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    await service.delete(policy)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
