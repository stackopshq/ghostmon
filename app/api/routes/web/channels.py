from __future__ import annotations

import uuid

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError

from app.api.deps.db import DBSession
from app.api.routes.web._shared import login_redirect, resolve_current_user, templates
from app.core.models.notification_channel import ChannelType, NotificationChannel
from app.core.schemas.notification_channel import (
    EmailChannelConfig,
    NotificationChannelCreate,
    NotificationChannelUpdate,
    WebhookChannelConfig,
)
from app.core.security.field_crypto import decrypt_secret
from app.core.services.notification_channel_service import NotificationChannelService
from app.tasks.notifications.dispatcher import send_test_notification

router = APIRouter()


def _edit_form(channel: NotificationChannel) -> dict[str, object]:
    """Pre-fill the edit form from a stored channel, decrypting the alert target
    (url/to) back to plaintext so the owner can see and edit it."""
    cfg = channel.config or {}
    return {
        "name": channel.name,
        "type": channel.type.value,
        "email_to": decrypt_secret(cfg["to"]) if cfg.get("to") else "",
        "webhook_url": decrypt_secret(cfg["url"]) if cfg.get("url") else "",
        "webhook_secret": "",
        "is_enabled": channel.is_enabled,
    }


@router.get("/channels", response_class=HTMLResponse, response_model=None)
async def list_channels(request: Request, session: DBSession) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    channels = list(await NotificationChannelService(session).list_for_owner(user.id))
    return templates.TemplateResponse(
        request,
        "channels/list.html",
        context={
            "current_user": user,
            "active_nav": "channels",
            "channels": channels,
            "flash": request.query_params.get("flash"),
        },
    )


@router.get("/channels/new", response_class=HTMLResponse, response_model=None)
async def new_channel_form(request: Request, session: DBSession) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    return templates.TemplateResponse(
        request,
        "channels/form.html",
        context={
            "current_user": user,
            "active_nav": "channels",
            "channel": None,
            "channel_types": [t.value for t in ChannelType],
            "error": None,
        },
    )


@router.post("/channels/new", response_class=HTMLResponse, response_model=None)
async def create_channel(
    request: Request,
    session: DBSession,
    name: str = Form(...),
    type: str = Form(...),
    email_to: str | None = Form(None),
    webhook_url: str | None = Form(None),
    webhook_secret: str | None = Form(None),
    is_enabled: str | None = Form(None),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()

    form_data = {
        "name": name,
        "type": type,
        "email_to": email_to,
        "webhook_url": webhook_url,
        "webhook_secret": webhook_secret,
        "is_enabled": is_enabled == "on",
    }

    try:
        config: EmailChannelConfig | WebhookChannelConfig
        if type == ChannelType.EMAIL.value:
            config = EmailChannelConfig(to=email_to or "")
        elif type == ChannelType.WEBHOOK.value:
            config = WebhookChannelConfig(
                url=webhook_url or "",
                secret=webhook_secret or None,
            )
        else:
            raise ValueError(f"unknown channel type: {type!r}")
        payload = NotificationChannelCreate(
            name=name,
            is_enabled=(is_enabled == "on"),
            config=config,
        )
    except (ValueError, TypeError) as exc:
        return templates.TemplateResponse(
            request,
            "channels/form.html",
            context={
                "current_user": user,
                "active_nav": "channels",
                "channel": None,
                "channel_types": [t.value for t in ChannelType],
                "error": str(exc),
                "form": form_data,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    try:
        await NotificationChannelService(session).create(payload, user.id)
    except IntegrityError:
        return templates.TemplateResponse(
            request,
            "channels/form.html",
            context={
                "current_user": user,
                "active_nav": "channels",
                "channel": None,
                "channel_types": [t.value for t in ChannelType],
                "error": f"Channel name already exists: {name}",
                "form": form_data,
            },
            status_code=status.HTTP_409_CONFLICT,
        )
    return RedirectResponse(url="/channels", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/channels/{channel_id}", response_class=HTMLResponse, response_model=None)
async def channel_detail(
    channel_id: uuid.UUID, request: Request, session: DBSession
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = NotificationChannelService(session)
    channel = await service.get(channel_id, user.id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return templates.TemplateResponse(
        request,
        "channels/form.html",
        context={
            "current_user": user,
            "active_nav": "channels",
            "channel": channel,
            "channel_types": [t.value for t in ChannelType],
            "error": None,
            "flash": request.query_params.get("flash"),
            "form": _edit_form(channel),
        },
    )


@router.post("/channels/{channel_id}", response_class=HTMLResponse, response_model=None)
async def update_channel(
    channel_id: uuid.UUID,
    request: Request,
    session: DBSession,
    name: str = Form(...),
    type: str = Form(...),
    email_to: str | None = Form(None),
    webhook_url: str | None = Form(None),
    webhook_secret: str | None = Form(None),
    is_enabled: str | None = Form(None),
) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = NotificationChannelService(session)
    channel = await service.get(channel_id, user.id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    form_data = {
        "name": name,
        "type": type,
        "email_to": email_to,
        "webhook_url": webhook_url,
        "webhook_secret": webhook_secret,
        "is_enabled": is_enabled == "on",
    }
    try:
        config: EmailChannelConfig | WebhookChannelConfig
        if type == ChannelType.EMAIL.value:
            config = EmailChannelConfig(to=email_to or "")
        elif type == ChannelType.WEBHOOK.value:
            config = WebhookChannelConfig(
                url=webhook_url or "",
                secret=webhook_secret or None,
            )
        else:
            raise ValueError(f"unknown channel type: {type!r}")
        payload = NotificationChannelUpdate(
            name=name,
            is_enabled=(is_enabled == "on"),
            config=config,
        )
    except (ValueError, TypeError) as exc:
        return templates.TemplateResponse(
            request,
            "channels/form.html",
            context={
                "current_user": user,
                "active_nav": "channels",
                "channel": channel,
                "channel_types": [t.value for t in ChannelType],
                "error": str(exc),
                "form": form_data,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    await service.update(channel, payload)
    return RedirectResponse(
        url=f"/channels/{channel_id}?flash=Saved",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/channels/{channel_id}/delete")
async def delete_channel(
    channel_id: uuid.UUID, request: Request, session: DBSession
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = NotificationChannelService(session)
    channel = await service.get(channel_id, user.id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await service.delete(channel)
    return RedirectResponse(url="/channels", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/channels/{channel_id}/test")
async def test_channel_form(
    channel_id: uuid.UUID, request: Request, session: DBSession
) -> RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()
    service = NotificationChannelService(session)
    channel = await service.get(channel_id, user.id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await send_test_notification(channel)
    return RedirectResponse(
        url=f"/channels/{channel_id}?flash=Test+sent",
        status_code=status.HTTP_303_SEE_OTHER,
    )
