from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps.db import DBSession
from app.api.routes.web._shared import login_redirect, resolve_current_user, templates
from app.core.models.monitor import MonitorStatus, MonitorType
from app.core.schemas.monitor import MonitorCreate, MonitorUpdate
from app.core.services.monitor_service import MonitorService
from app.core.services.notification_channel_service import NotificationChannelService

router = APIRouter()


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
    service = MonitorService(session)
    monitor = await service.get(monitor_id, user.id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    results = await service.list_results(monitor_id, limit=25)
    channel_svc = NotificationChannelService(session)
    attached = list(await channel_svc.channels_for_monitor(monitor_id))
    attached_ids = {c.id for c in attached}
    all_channels = list(await channel_svc.list_for_owner(user.id))
    available = [c for c in all_channels if c.id not in attached_ids]

    return templates.TemplateResponse(
        request,
        "monitors/detail.html",
        context={
            "current_user": user,
            "active_nav": "dashboard",
            "monitor": monitor,
            "results": results,
            "attached_channels": attached,
            "available_channels": available,
            "monitor_types": [t.value for t in MonitorType],
            "monitor_statuses": [s.value for s in MonitorStatus],
            "error": None,
        },
    )


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


async def _render_detail_with_error(
    request: Request,
    session: DBSession,
    user: object,
    monitor_id: uuid.UUID,
    error: str,
) -> HTMLResponse:
    service = MonitorService(session)
    monitor = await service.get(monitor_id, user.id)  # type: ignore[attr-defined]
    results = await service.list_results(monitor_id, limit=25)
    channel_svc = NotificationChannelService(session)
    attached = list(await channel_svc.channels_for_monitor(monitor_id))
    attached_ids = {c.id for c in attached}
    all_channels = list(await channel_svc.list_for_owner(user.id))  # type: ignore[attr-defined]
    available = [c for c in all_channels if c.id not in attached_ids]
    return templates.TemplateResponse(
        request,
        "monitors/detail.html",
        context={
            "current_user": user,
            "active_nav": "dashboard",
            "monitor": monitor,
            "results": results,
            "attached_channels": attached,
            "available_channels": available,
            "monitor_types": [t.value for t in MonitorType],
            "monitor_statuses": [s.value for s in MonitorStatus],
            "error": error,
        },
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
