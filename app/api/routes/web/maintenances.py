from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps.db import DBSession
from app.api.routes.web._shared import login_redirect, resolve_current_user, templates
from app.core.models.maintenance import MaintenanceStrategy
from app.core.schemas.maintenance import MaintenanceCreate, MaintenanceUpdate
from app.core.services.maintenance_service import MaintenanceService
from app.core.services.monitor_service import MonitorService

router = APIRouter()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    # HTML datetime-local inputs yield "YYYY-MM-DDTHH:MM" (no seconds, no tz).
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@router.get("/maintenances", response_class=HTMLResponse, response_model=None)
async def list_maintenances(
    request: Request, session: DBSession
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    items = list(await MaintenanceService(session).list_for_owner(user.id))
    return templates.TemplateResponse(
        request,
        "maintenances/list.html",
        context={
            "current_user": user,
            "active_nav": "maintenances",
            "maintenances": items,
        },
    )


@router.get("/maintenances/new", response_class=HTMLResponse, response_model=None)
async def new_maintenance_form(
    request: Request, session: DBSession
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    return templates.TemplateResponse(
        request,
        "maintenances/form.html",
        context={
            "current_user": user,
            "active_nav": "maintenances",
            "maintenance": None,
            "strategies": [s.value for s in MaintenanceStrategy],
            "error": None,
        },
    )


@router.post("/maintenances/new", response_class=HTMLResponse, response_model=None)
async def create_maintenance(
    request: Request,
    session: DBSession,
    title: str = Form(...),
    description: str | None = Form(None),
    strategy: str = Form(...),
    start_at: str | None = Form(None),
    end_at: str | None = Form(None),
    cron: str | None = Form(None),
    duration_minutes: int | None = Form(None),
    timezone: str = Form("UTC"),
    is_active: str | None = Form(None),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    try:
        payload = MaintenanceCreate(
            title=title,
            description=description or None,
            is_active=(is_active == "on"),
            strategy=MaintenanceStrategy(strategy),
            start_at=_parse_datetime(start_at),
            end_at=_parse_datetime(end_at),
            cron=cron or None,
            duration_minutes=duration_minutes,
            timezone=timezone,
        )
    except (ValueError, TypeError) as exc:
        return templates.TemplateResponse(
            request,
            "maintenances/form.html",
            context={
                "current_user": user,
                "active_nav": "maintenances",
                "maintenance": None,
                "strategies": [s.value for s in MaintenanceStrategy],
                "error": str(exc),
                "form": {
                    "title": title,
                    "description": description,
                    "strategy": strategy,
                    "start_at": start_at,
                    "end_at": end_at,
                    "cron": cron,
                    "duration_minutes": duration_minutes,
                    "timezone": timezone,
                    "is_active": is_active == "on",
                },
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    await MaintenanceService(session).create(payload, user.id)
    return RedirectResponse(url="/maintenances", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/maintenances/{maintenance_id}", response_class=HTMLResponse, response_model=None)
async def maintenance_detail(
    maintenance_id: uuid.UUID, request: Request, session: DBSession
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = MaintenanceService(session)
    maintenance = await service.get(maintenance_id, user.id)
    if maintenance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance not found")

    attached_ids = set(await service.monitors_for_maintenance(maintenance_id))
    all_monitors = list(await MonitorService(session).list_for_owner(user.id))
    attached = [m for m in all_monitors if m.id in attached_ids]
    available = [m for m in all_monitors if m.id not in attached_ids]

    return templates.TemplateResponse(
        request,
        "maintenances/detail.html",
        context={
            "current_user": user,
            "active_nav": "maintenances",
            "maintenance": maintenance,
            "strategies": [s.value for s in MaintenanceStrategy],
            "attached_monitors": attached,
            "available_monitors": available,
            "error": None,
        },
    )


@router.post("/maintenances/{maintenance_id}", response_class=HTMLResponse, response_model=None)
async def update_maintenance(
    maintenance_id: uuid.UUID,
    request: Request,
    session: DBSession,
    title: str = Form(...),
    description: str | None = Form(None),
    strategy: str = Form(...),
    start_at: str | None = Form(None),
    end_at: str | None = Form(None),
    cron: str | None = Form(None),
    duration_minutes: int | None = Form(None),
    timezone: str = Form("UTC"),
    is_active: str | None = Form(None),
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = MaintenanceService(session)
    maintenance = await service.get(maintenance_id, user.id)
    if maintenance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance not found")
    try:
        payload = MaintenanceUpdate(
            title=title,
            description=description or None,
            is_active=(is_active == "on"),
            strategy=MaintenanceStrategy(strategy),
            start_at=_parse_datetime(start_at),
            end_at=_parse_datetime(end_at),
            cron=cron or None,
            duration_minutes=duration_minutes,
            timezone=timezone,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    await service.update(maintenance, payload)
    return RedirectResponse(
        url=f"/maintenances/{maintenance_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/maintenances/{maintenance_id}/delete")
async def delete_maintenance(
    maintenance_id: uuid.UUID, request: Request, session: DBSession
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = MaintenanceService(session)
    maintenance = await service.get(maintenance_id, user.id)
    if maintenance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance not found")
    await service.delete(maintenance)
    return RedirectResponse(url="/maintenances", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/maintenances/{maintenance_id}/monitors/attach")
async def attach_monitor_form(
    maintenance_id: uuid.UUID,
    request: Request,
    session: DBSession,
    monitor_id: Annotated[uuid.UUID, Form()],
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    maint_svc = MaintenanceService(session)
    monitor_svc = MonitorService(session)
    if await maint_svc.get(maintenance_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance not found")
    if await monitor_svc.get(monitor_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    await maint_svc.attach_monitor(maintenance_id, monitor_id)
    return RedirectResponse(
        url=f"/maintenances/{maintenance_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/maintenances/{maintenance_id}/monitors/{monitor_id}/detach")
async def detach_monitor_form(
    maintenance_id: uuid.UUID,
    monitor_id: uuid.UUID,
    request: Request,
    session: DBSession,
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    maint_svc = MaintenanceService(session)
    monitor_svc = MonitorService(session)
    if await maint_svc.get(maintenance_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance not found")
    if await monitor_svc.get(monitor_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    await maint_svc.detach_monitor(maintenance_id, monitor_id)
    return RedirectResponse(
        url=f"/maintenances/{maintenance_id}", status_code=status.HTTP_303_SEE_OTHER
    )
