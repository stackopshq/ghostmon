from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps.db import DBSession
from app.api.routes.web._shared import login_redirect, resolve_current_user, templates
from app.core.models.monitor import MonitorStatus, MonitorType
from app.core.models.trigger import Severity, TriggerMetric, TriggerOperator
from app.core.models.user import User
from app.core.schemas.monitor import MonitorCreate, MonitorUpdate
from app.core.schemas.trigger import TriggerCreate
from app.core.services.monitor_service import MonitorService
from app.core.services.notification_channel_service import NotificationChannelService
from app.core.services.trigger_service import TriggerService

router = APIRouter()

_OPERATOR_SYMBOLS = {
    TriggerOperator.GT: ">",
    TriggerOperator.GE: ">=",
    TriggerOperator.LT: "<",
    TriggerOperator.LE: "<=",
}


async def _detail_context(
    session: DBSession, user: User, monitor_id: uuid.UUID, error: str | None = None
) -> dict[str, object] | None:
    """Build the monitor-detail template context, or None if the monitor is not
    owned by the user. Shared by the detail view and the form error paths."""
    monitor_svc = MonitorService(session)
    monitor = await monitor_svc.get(monitor_id, user.id)
    if monitor is None:
        return None

    channel_svc = NotificationChannelService(session)
    attached = list(await channel_svc.channels_for_monitor(monitor_id))
    attached_ids = {c.id for c in attached}
    available = [c for c in await channel_svc.list_for_owner(user.id) if c.id not in attached_ids]
    triggers = list(await TriggerService(session).list_for_monitor(monitor_id))

    return {
        "current_user": user,
        "active_nav": "dashboard",
        "monitor": monitor,
        "results": await monitor_svc.list_results(monitor_id, limit=25),
        "attached_channels": attached,
        "available_channels": available,
        "triggers": triggers,
        "monitor_types": [t.value for t in MonitorType],
        "monitor_statuses": [s.value for s in MonitorStatus],
        "trigger_metrics": [m.value for m in TriggerMetric],
        "trigger_operators": [{"value": o.value, "label": s} for o, s in _OPERATOR_SYMBOLS.items()],
        "severities": [s.value for s in Severity],
        "operator_symbols": {o.value: s for o, s in _OPERATOR_SYMBOLS.items()},
        "error": error,
    }


@router.get("/monitors/new", response_class=HTMLResponse, response_model=None)
async def new_monitor_form(request: Request, session: DBSession) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    return templates.TemplateResponse(
        request,
        "monitors/form.html",
        context={
            "current_user": user,
            "active_nav": "dashboard",
            "monitor": None,
            "monitor_types": [t.value for t in MonitorType],
            "error": None,
        },
    )


@router.post("/monitors/new", response_class=HTMLResponse, response_model=None)
async def create_monitor(
    request: Request,
    session: DBSession,
    name: str = Form(...),
    type: str = Form(...),
    url: str = Form(...),
    interval: int = Form(60),
    retries: int = Form(2),
    retry_interval: int = Form(20),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    try:
        payload = MonitorCreate(
            name=name,
            type=MonitorType(type),
            url=url,
            interval=interval,
            retries=retries,
            retry_interval=retry_interval,
        )
    except (ValueError, TypeError) as exc:
        return templates.TemplateResponse(
            request,
            "monitors/form.html",
            context={
                "current_user": user,
                "active_nav": "dashboard",
                "monitor": None,
                "monitor_types": [t.value for t in MonitorType],
                "error": str(exc),
                "form": {
                    "name": name,
                    "type": type,
                    "url": url,
                    "interval": interval,
                    "retries": retries,
                    "retry_interval": retry_interval,
                },
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    await MonitorService(session).create(payload, user.id)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/monitors/{monitor_id}", response_class=HTMLResponse, response_model=None)
async def monitor_detail(
    monitor_id: uuid.UUID, request: Request, session: DBSession
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    context = await _detail_context(session, user, monitor_id)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    return templates.TemplateResponse(request, "monitors/detail.html", context=context)


@router.post("/monitors/{monitor_id}", response_class=HTMLResponse, response_model=None)
async def update_monitor(
    monitor_id: uuid.UUID,
    request: Request,
    session: DBSession,
    name: str = Form(...),
    type: str = Form(...),
    url: str = Form(...),
    interval: int = Form(...),
    retries: int = Form(...),
    retry_interval: int = Form(...),
    status_field: str = Form(..., alias="status"),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = MonitorService(session)
    monitor = await service.get(monitor_id, user.id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    try:
        payload = MonitorUpdate(
            name=name,
            type=MonitorType(type),
            url=url,
            interval=interval,
            retries=retries,
            retry_interval=retry_interval,
            status=MonitorStatus(status_field),
        )
    except (ValueError, TypeError) as exc:
        return await _render_detail_with_error(request, session, user, monitor_id, str(exc))
    await service.update(monitor, payload)
    return RedirectResponse(url=f"/monitors/{monitor_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/monitors/{monitor_id}/delete")
async def delete_monitor(
    monitor_id: uuid.UUID, request: Request, session: DBSession
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = MonitorService(session)
    monitor = await service.get(monitor_id, user.id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    await service.delete(monitor)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/monitors/{monitor_id}/channels/attach")
async def attach_channel_form(
    monitor_id: uuid.UUID,
    request: Request,
    session: DBSession,
    channel_id: Annotated[uuid.UUID, Form()],
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    monitor_svc = MonitorService(session)
    channel_svc = NotificationChannelService(session)
    if await monitor_svc.get(monitor_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    if await channel_svc.get(channel_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await channel_svc.attach(monitor_id, channel_id)
    return RedirectResponse(url=f"/monitors/{monitor_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/monitors/{monitor_id}/channels/{channel_id}/detach")
async def detach_channel_form(
    monitor_id: uuid.UUID,
    channel_id: uuid.UUID,
    request: Request,
    session: DBSession,
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    monitor_svc = MonitorService(session)
    channel_svc = NotificationChannelService(session)
    if await monitor_svc.get(monitor_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    if await channel_svc.get(channel_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await channel_svc.detach(monitor_id, channel_id)
    return RedirectResponse(url=f"/monitors/{monitor_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/monitors/{monitor_id}/triggers/new", response_class=HTMLResponse, response_model=None
)
async def create_trigger_form(
    monitor_id: uuid.UUID,
    request: Request,
    session: DBSession,
    name: str = Form(...),
    metric: str = Form(...),
    operator: str = Form(...),
    threshold: float = Form(...),
    severity: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    if await MonitorService(session).get(monitor_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    try:
        payload = TriggerCreate(
            name=name,
            metric=TriggerMetric(metric),
            operator=TriggerOperator(operator),
            threshold=threshold,
            severity=Severity(severity),
        )
    except (ValueError, TypeError) as exc:
        return await _render_detail_with_error(request, session, user, monitor_id, str(exc))
    await TriggerService(session).create(monitor_id, payload)
    return RedirectResponse(url=f"/monitors/{monitor_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/monitors/{monitor_id}/triggers/{trigger_id}/delete")
async def delete_trigger_form(
    monitor_id: uuid.UUID,
    trigger_id: uuid.UUID,
    request: Request,
    session: DBSession,
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    if await MonitorService(session).get(monitor_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    service = TriggerService(session)
    trigger = await service.get(trigger_id, monitor_id)
    if trigger is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trigger not found")
    await service.delete(trigger)
    return RedirectResponse(url=f"/monitors/{monitor_id}", status_code=status.HTTP_303_SEE_OTHER)


async def _render_detail_with_error(
    request: Request,
    session: DBSession,
    user: User,
    monitor_id: uuid.UUID,
    error: str,
) -> HTMLResponse:
    context = await _detail_context(session, user, monitor_id, error=error)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    return templates.TemplateResponse(
        request,
        "monitors/detail.html",
        context=context,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
