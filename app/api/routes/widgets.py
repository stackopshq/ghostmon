"""Portal bento widgets — the `data_url` endpoints ghostboard renders.

Each returns the small JSON shape ghostboard's widget contract expects for its
`kind` (stat / chart). Scoped to the token subject's own monitors; an unknown
subject yields an empty payload so the portal tile removes itself.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps.db import DBSession
from app.api.deps.portal import PortalToken
from app.core.models.monitor import Monitor, MonitorStatus
from app.core.models.monitor_result import MonitorResult

router = APIRouter(prefix="/v1/widgets", tags=["portal-widgets"])

_LATENCY_POINTS = 30


@router.get("/uptime")
async def uptime_widget(portal: PortalToken, session: DBSession) -> dict[str, Any]:
    """Stat widget: how many of the user's monitors are currently up."""
    if portal.user is None:
        return {"value": "—", "label": "no monitors", "trend": "flat"}

    stmt = select(Monitor.status).where(
        Monitor.owner_id == portal.user.id,
        Monitor.status != MonitorStatus.PAUSED,
    )
    statuses = list(await session.scalars(stmt))
    total = len(statuses)
    up = sum(1 for s in statuses if s == MonitorStatus.UP)

    if total == 0:
        trend = "flat"
    elif up == total:
        trend = "up"
    else:
        trend = "down"
    return {"value": f"{up}/{total}", "label": "services up", "trend": trend}


@router.get("/latency")
async def latency_widget(portal: PortalToken, session: DBSession) -> dict[str, Any]:
    """Chart widget: recent probe latencies across the user's monitors."""
    empty: dict[str, Any] = {"points": [0], "variant": "line", "unit": "ms"}
    if portal.user is None:
        return empty

    stmt = (
        select(MonitorResult.latency_ms)
        .join(Monitor, Monitor.id == MonitorResult.monitor_id)
        .where(
            Monitor.owner_id == portal.user.id,
            MonitorResult.latency_ms.is_not(None),
        )
        .order_by(MonitorResult.checked_at.desc())
        .limit(_LATENCY_POINTS)
    )
    latencies = [v for v in await session.scalars(stmt) if v is not None]
    if not latencies:
        return empty
    # DB gave newest-first; the sparkline reads left-to-right oldest-to-newest.
    points = [float(v) for v in reversed(latencies)]
    return {"points": points, "variant": "line", "unit": "ms"}
