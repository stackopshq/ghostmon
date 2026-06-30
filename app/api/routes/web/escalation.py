from __future__ import annotations

import uuid
from itertools import zip_longest

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps.db import DBSession
from app.api.routes.web._shared import login_redirect, resolve_current_user, templates
from app.core.models.notification_channel import ChannelType
from app.core.models.user import User
from app.core.schemas.escalation import EscalationPolicyCreate, EscalationStepCreate
from app.core.services.escalation_service import EscalationService
from app.core.services.notification_channel_service import NotificationChannelService

router = APIRouter()

_STEP_ROWS = 5  # fixed step rows in the no-JS form; rows without a channel are ignored


async def _context(
    session: DBSession, user: User, error: str | None = None, flash: str | None = None
) -> dict[str, object]:
    channels = list(await NotificationChannelService(session).list_for_owner(user.id))
    return {
        "current_user": user,
        "active_nav": "escalation",
        "policies": list(await EscalationService(session).list_for_owner(user.id)),
        "channels": channels,
        "channel_names": {c.id: c.name for c in channels},
        "step_rows": list(range(_STEP_ROWS)),
        "error": error,
        "flash": flash,
    }


@router.get("/escalation", response_class=HTMLResponse, response_model=None)
async def escalation_page(request: Request, session: DBSession) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    context = await _context(session, user, flash=request.query_params.get("flash"))
    return templates.TemplateResponse(request, "escalation/list.html", context=context)


@router.post("/escalation/new", response_class=HTMLResponse, response_model=None)
async def create_escalation_form(
    request: Request,
    session: DBSession,
    name: str = Form(...),
    is_enabled: str | None = Form(None),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = EscalationService(session)

    form = await request.form()
    delay_minutes = [str(v) for v in form.getlist("delay_minutes")]
    channel_id = [str(v) for v in form.getlist("channel_id")]
    action_command = [str(v) for v in form.getlist("action_command")]
    steps: list[EscalationStepCreate] = []
    order = 0
    for delay, channel, command in zip_longest(
        delay_minutes, channel_id, action_command, fillvalue=""
    ):
        if not channel:
            continue
        order += 1
        try:
            steps.append(
                EscalationStepCreate(
                    step_order=order,
                    delay_minutes=int(delay or 0),
                    channel_id=uuid.UUID(channel),
                    action_command=command.strip() or None,
                )
            )
        except (ValueError, TypeError):
            continue

    async def _error(message: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "escalation/list.html",
            context=await _context(session, user, error=message),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if not steps:
        return await _error("Add at least one step with a channel.")
    wanted = {s.channel_id for s in steps}
    if await service.channels_owned_by(user.id, wanted) != wanted:
        return await _error("One or more selected channels are not yours.")
    remediation_channels = {s.channel_id for s in steps if s.action_command}
    if remediation_channels:
        types = await service.channel_types(user.id, remediation_channels)
        if any(types.get(cid) != ChannelType.WEBHOOK for cid in remediation_channels):
            return await _error("Auto-remediation steps must target a webhook channel.")
    try:
        payload = EscalationPolicyCreate(name=name, is_enabled=(is_enabled == "on"), steps=steps)
    except (ValueError, TypeError) as exc:
        return await _error(str(exc))

    await service.create(user.id, payload)
    return RedirectResponse(url="/escalation?flash=Saved", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/escalation/{policy_id}/delete")
async def delete_escalation_form(
    policy_id: uuid.UUID, request: Request, session: DBSession
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = EscalationService(session)
    policy = await service.get(policy_id, user.id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    await service.delete(policy)
    return RedirectResponse(url="/escalation?flash=Deleted", status_code=status.HTTP_303_SEE_OTHER)
