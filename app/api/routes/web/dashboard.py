from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps.db import DBSession
from app.api.routes.web._shared import login_redirect, resolve_current_user, templates
from app.core.services.maintenance_service import MaintenanceService
from app.core.services.monitor_service import MonitorService

router = APIRouter()


@router.get("/", response_class=HTMLResponse, response_model=None)
async def dashboard(request: Request, session: DBSession) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()

    monitors = list(await MonitorService(session).list_for_owner(user.id))
    maintenance_svc = MaintenanceService(session)
    under_maintenance: set[str] = set()
    for monitor in monitors:
        if await maintenance_svc.is_monitor_under_maintenance(monitor.id):
            under_maintenance.add(str(monitor.id))

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context={
            "current_user": user,
            "monitors": monitors,
            "under_maintenance": under_maintenance,
            "active_nav": "dashboard",
        },
    )
