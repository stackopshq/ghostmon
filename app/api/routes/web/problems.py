from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps.db import DBSession
from app.api.routes.web._shared import login_redirect, resolve_current_user, templates
from app.core.services.problem_event_service import ProblemEventService

router = APIRouter()


def _fmt_duration(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


@router.get("/problems", response_class=HTMLResponse, response_model=None)
async def problems_page(request: Request, session: DBSession) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    events = await ProblemEventService(session).list_for_owner(user.id, limit=200)
    now = datetime.now(UTC)
    rows = [
        {
            "event": e,
            "ongoing": e.resolved_at is None,
            "duration": _fmt_duration((e.resolved_at or now) - e.started_at),
        }
        for e in events
    ]
    ongoing = sum(1 for r in rows if r["ongoing"])
    return templates.TemplateResponse(
        request,
        "problems/list.html",
        context={
            "current_user": user,
            "active_nav": "problems",
            "rows": rows,
            "ongoing": ongoing,
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/problems/{event_id}/ack")
async def acknowledge_problem_form(
    event_id: uuid.UUID, request: Request, session: DBSession
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    await ProblemEventService(session).acknowledge(event_id, user.id, user.id, datetime.now(UTC))
    return RedirectResponse(
        url="/problems?flash=Acknowledged", status_code=status.HTTP_303_SEE_OTHER
    )
