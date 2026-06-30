from __future__ import annotations

import uuid

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError

from app.api.deps.db import DBSession
from app.api.routes.web._shared import login_redirect, resolve_current_user, templates
from app.core.models.host import ItemSource, ItemValueType
from app.core.models.trigger import Severity, TriggerAggregation, TriggerOperator
from app.core.models.user import User
from app.core.schemas.host import HostCreate, HostUpdate, ItemCreate
from app.core.schemas.trigger import ItemTriggerCreate
from app.core.services.host_service import HostService, ItemService
from app.core.services.trigger_service import TriggerService

router = APIRouter()

_SPARK_W = 160
_SPARK_H = 32

_OPERATOR_SYMBOLS = {
    TriggerOperator.GT: ">",
    TriggerOperator.GE: ">=",
    TriggerOperator.LT: "<",
    TriggerOperator.LE: "<=",
}


def _sparkline_points(values: list[float], width: int = _SPARK_W, height: int = _SPARK_H) -> str:
    """Server-rendered sparkline: scale values into an SVG polyline `points`
    string. No JavaScript, no external chart library."""
    if len(values) < 2:
        return ""
    pad = 2.0
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    last = len(values) - 1
    points = []
    for i, value in enumerate(values):
        x = pad + (width - 2 * pad) * i / last
        y = pad + (height - 2 * pad) * (1 - (value - lo) / span)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


async def _host_detail_context(
    session: DBSession, user: User, host_id: uuid.UUID, error: str | None = None
) -> dict[str, object] | None:
    host = await HostService(session).get(host_id, user.id)
    if host is None:
        return None
    item_svc = ItemService(session)
    item_views = []
    for item in await item_svc.list_for_host(host_id):
        recent = list(await item_svc.list_values(item.id, limit=30))  # newest first
        chrono = list(reversed(recent))
        nums = [v.value_num for v in chrono if v.value_num is not None]
        item_views.append(
            {
                "item": item,
                "latest": recent[0] if recent else None,
                "count": len(recent),
                "min": min(nums) if nums else None,
                "max": max(nums) if nums else None,
                "spark": _sparkline_points(nums) if item.value_type.is_numeric else "",
            }
        )
    return {
        "current_user": user,
        "active_nav": "hosts",
        "host": host,
        "item_views": item_views,
        "value_types": [t.value for t in ItemValueType],
        "item_sources": [s.value for s in ItemSource],
        "spark_w": _SPARK_W,
        "spark_h": _SPARK_H,
        "error": error,
        "flash": None,
    }


@router.get("/hosts", response_class=HTMLResponse, response_model=None)
async def list_hosts(request: Request, session: DBSession) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    hosts = list(await HostService(session).list_for_owner(user.id))
    return templates.TemplateResponse(
        request,
        "hosts/list.html",
        context={"current_user": user, "active_nav": "hosts", "hosts": hosts},
    )


@router.get("/hosts/new", response_class=HTMLResponse, response_model=None)
async def new_host_form(request: Request, session: DBSession) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    return templates.TemplateResponse(
        request,
        "hosts/form.html",
        context={"current_user": user, "active_nav": "hosts", "host": None, "error": None},
    )


@router.post("/hosts/new", response_class=HTMLResponse, response_model=None)
async def create_host(
    request: Request,
    session: DBSession,
    name: str = Form(...),
    description: str | None = Form(None),
    address: str | None = Form(None),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    try:
        payload = HostCreate(name=name, description=description or None, address=address or None)
    except (ValueError, TypeError) as exc:
        return templates.TemplateResponse(
            request,
            "hosts/form.html",
            context={"current_user": user, "active_nav": "hosts", "host": None, "error": str(exc)},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    try:
        host = await HostService(session).create(payload, user.id)
    except IntegrityError:
        return templates.TemplateResponse(
            request,
            "hosts/form.html",
            context={
                "current_user": user,
                "active_nav": "hosts",
                "host": None,
                "error": f"Host name already exists: {name}",
            },
            status_code=status.HTTP_409_CONFLICT,
        )
    return RedirectResponse(url=f"/hosts/{host.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/hosts/{host_id}", response_class=HTMLResponse, response_model=None)
async def host_detail(
    host_id: uuid.UUID, request: Request, session: DBSession
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    context = await _host_detail_context(session, user, host_id)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")
    return templates.TemplateResponse(request, "hosts/detail.html", context=context)


@router.post("/hosts/{host_id}", response_class=HTMLResponse, response_model=None)
async def update_host(
    host_id: uuid.UUID,
    request: Request,
    session: DBSession,
    name: str = Form(...),
    description: str | None = Form(None),
    address: str | None = Form(None),
    is_enabled: str | None = Form(None),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = HostService(session)
    host = await service.get(host_id, user.id)
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")
    await service.update(
        host,
        HostUpdate(
            name=name,
            description=description or None,
            address=address or None,
            is_enabled=is_enabled == "on",
        ),
    )
    return RedirectResponse(url=f"/hosts/{host_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/hosts/{host_id}/delete")
async def delete_host(host_id: uuid.UUID, request: Request, session: DBSession) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = HostService(session)
    host = await service.get(host_id, user.id)
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")
    await service.delete(host)
    return RedirectResponse(url="/hosts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/hosts/{host_id}/items/new", response_class=HTMLResponse, response_model=None)
async def create_item_form(
    host_id: uuid.UUID,
    request: Request,
    session: DBSession,
    key: str = Form(...),
    name: str = Form(...),
    value_type: str = Form(...),
    units: str | None = Form(None),
    interval: int = Form(60),
    source: str = Form("trapper"),
    oid: str | None = Form(None),
    community: str | None = Form(None),
    is_private: str | None = Form(None),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    if await HostService(session).get(host_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")
    config: dict[str, str] = {}
    if source == ItemSource.SNMP.value and oid:
        config = {"oid": oid, "community": community or "public"}
    try:
        payload = ItemCreate(
            key=key,
            name=name,
            value_type=ItemValueType(value_type),
            units=units or None,
            interval=interval,
            source=ItemSource(source),
            config=config,
            is_private=is_private == "on",
        )
    except (ValueError, TypeError) as exc:
        context = await _host_detail_context(session, user, host_id, error=str(exc))
        return templates.TemplateResponse(
            request,
            "hosts/detail.html",
            context=context or {},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    try:
        await ItemService(session).create(host_id, payload)
    except IntegrityError:
        context = await _host_detail_context(
            session, user, host_id, error=f"Item key already exists: {key}"
        )
        return templates.TemplateResponse(
            request,
            "hosts/detail.html",
            context=context or {},
            status_code=status.HTTP_409_CONFLICT,
        )
    return RedirectResponse(url=f"/hosts/{host_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/hosts/{host_id}/items/{item_id}/delete")
async def delete_item_form(
    host_id: uuid.UUID, item_id: uuid.UUID, request: Request, session: DBSession
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    if await HostService(session).get(host_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")
    service = ItemService(session)
    item = await service.get(item_id, host_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    await service.delete(item)
    return RedirectResponse(url=f"/hosts/{host_id}", status_code=status.HTTP_303_SEE_OTHER)


# ── Item detail + item triggers ─────────────────────────────────────────────


async def _item_detail_context(
    session: DBSession, user: User, host_id: uuid.UUID, item_id: uuid.UUID, error: str | None = None
) -> dict[str, object] | None:
    host = await HostService(session).get(host_id, user.id)
    if host is None:
        return None
    item_svc = ItemService(session)
    item = await item_svc.get(item_id, host_id)
    if item is None:
        return None
    return {
        "current_user": user,
        "active_nav": "hosts",
        "host": host,
        "item": item,
        "triggers": list(await TriggerService(session).list_for_item(item_id)),
        "values": list(await item_svc.list_values(item_id, limit=25)),
        "trends": list(await item_svc.list_trends(item_id, limit=24)),
        "trigger_operators": [{"value": o.value, "label": s} for o, s in _OPERATOR_SYMBOLS.items()],
        "trigger_aggregations": [a.value for a in TriggerAggregation],
        "severities": [s.value for s in Severity],
        "operator_symbols": {o.value: s for o, s in _OPERATOR_SYMBOLS.items()},
        "error": error,
    }


@router.get("/hosts/{host_id}/items/{item_id}", response_class=HTMLResponse, response_model=None)
async def item_detail(
    host_id: uuid.UUID, item_id: uuid.UUID, request: Request, session: DBSession
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    context = await _item_detail_context(session, user, host_id, item_id)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return templates.TemplateResponse(request, "hosts/item_detail.html", context=context)


@router.post(
    "/hosts/{host_id}/items/{item_id}/triggers/new",
    response_class=HTMLResponse,
    response_model=None,
)
async def create_item_trigger_form(
    host_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    session: DBSession,
    name: str = Form(...),
    operator: str = Form(...),
    threshold: float = Form(...),
    severity: str = Form(...),
    aggregation: str = Form("last"),
    window_seconds: int = Form(0),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    if await HostService(session).get(host_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")
    if await ItemService(session).get(item_id, host_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    try:
        payload = ItemTriggerCreate(
            name=name,
            operator=TriggerOperator(operator),
            threshold=threshold,
            severity=Severity(severity),
            aggregation=TriggerAggregation(aggregation),
            window_seconds=window_seconds,
        )
    except (ValueError, TypeError) as exc:
        context = await _item_detail_context(session, user, host_id, item_id, error=str(exc))
        return templates.TemplateResponse(
            request,
            "hosts/item_detail.html",
            context=context or {},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    await TriggerService(session).create_for_item(item_id, payload)
    return RedirectResponse(
        url=f"/hosts/{host_id}/items/{item_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/hosts/{host_id}/items/{item_id}/triggers/{trigger_id}/delete")
async def delete_item_trigger_form(
    host_id: uuid.UUID,
    item_id: uuid.UUID,
    trigger_id: uuid.UUID,
    request: Request,
    session: DBSession,
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    if await HostService(session).get(host_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host not found")
    service = TriggerService(session)
    trigger = await service.get_for_item(trigger_id, item_id)
    if trigger is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trigger not found")
    await service.delete(trigger)
    return RedirectResponse(
        url=f"/hosts/{host_id}/items/{item_id}", status_code=status.HTTP_303_SEE_OTHER
    )
