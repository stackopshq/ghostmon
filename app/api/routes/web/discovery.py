from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps.db import DBSession
from app.api.routes.web._shared import login_redirect, resolve_current_user, templates
from app.core.models.discovery import DiscoveryMethod
from app.core.models.user import User
from app.core.schemas.discovery import DiscoveryRuleCreate
from app.core.services.discovery_service import DiscoveryService
from app.core.services.template_service import TemplateService

router = APIRouter()


async def _context(
    session: DBSession, user: User, error: str | None = None, flash: str | None = None
) -> dict[str, object]:
    tmpls = list(await TemplateService(session).list_for_owner(user.id))
    return {
        "current_user": user,
        "active_nav": "discovery",
        "rules": list(await DiscoveryService(session).list_for_owner(user.id)),
        "templates_list": tmpls,
        "template_names": {t.id: t.name for t in tmpls},
        "methods": [m.value for m in DiscoveryMethod],
        "error": error,
        "flash": flash,
    }


@router.get("/discovery", response_class=HTMLResponse, response_model=None)
async def discovery_page(request: Request, session: DBSession) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    context = await _context(session, user, flash=request.query_params.get("flash"))
    return templates.TemplateResponse(request, "discovery/list.html", context=context)


@router.post("/discovery/new", response_class=HTMLResponse, response_model=None)
async def create_discovery_form(
    request: Request,
    session: DBSession,
    name: str = Form(...),
    cidr: str = Form(...),
    method: str = Form("ping"),
    port: str | None = Form(None),
    template_id: str | None = Form(None),
    interval_seconds: int = Form(3600),
    is_enabled: str | None = Form(None),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = DiscoveryService(session)

    async def _error(message: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "discovery/list.html",
            context=await _context(session, user, error=message),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    template_uuid = uuid.UUID(template_id) if template_id else None
    if (
        template_uuid is not None
        and await TemplateService(session).get(template_uuid, user.id) is None
    ):
        return await _error("Unknown template.")
    try:
        payload = DiscoveryRuleCreate(
            name=name,
            cidr=cidr,
            method=DiscoveryMethod(method),
            port=int(port) if port else None,
            template_id=template_uuid,
            interval_seconds=interval_seconds,
            is_enabled=is_enabled == "on",
        )
    except (ValueError, TypeError) as exc:
        return await _error(str(exc))

    await service.create(user.id, payload)
    return RedirectResponse(url="/discovery?flash=Saved", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/discovery/{rule_id}/scan")
async def scan_discovery_form(
    rule_id: uuid.UUID, request: Request, session: DBSession
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = DiscoveryService(session)
    rule = await service.get(rule_id, user.id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    created = await service.scan_rule(rule, datetime.now(UTC))
    return RedirectResponse(
        url=f"/discovery?flash=Discovered+{created}+host(s)", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/discovery/{rule_id}/delete")
async def delete_discovery_form(
    rule_id: uuid.UUID, request: Request, session: DBSession
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = DiscoveryService(session)
    rule = await service.get(rule_id, user.id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    await service.delete(rule)
    return RedirectResponse(url="/discovery?flash=Deleted", status_code=status.HTTP_303_SEE_OTHER)
