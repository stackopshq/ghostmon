import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.core.db.session import engine

router = APIRouter(tags=["health"], include_in_schema=False)

_log = logging.getLogger("ghostmon.health")


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> JSONResponse:
    # Liveness: 200 as long as the process is alive. Deliberately does NOT
    # touch the database — that is what /readyz is for. A database outage must
    # not trigger a container restart (the dependency is unhealthy, not the
    # app), so this endpoint never returns 503.
    return JSONResponse({"status": "ok", "version": __version__})


@router.get("/readyz", summary="Readiness probe")
async def readyz() -> JSONResponse:
    # Readiness: 200 only if the database answers. A 503 tells the ingress
    # (K8s service, load balancer) to drain traffic until the dependency
    # recovers — without restarting the process.
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        _log.exception("database readiness check failed")
        return JSONResponse(
            {"status": "error", "version": __version__},
            status_code=503,
        )
    return JSONResponse({"status": "ok", "version": __version__})
