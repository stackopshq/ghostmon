from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.routes import api_router
from app.api.routes.web import router as web_router
from app.core.config import get_settings

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="GhostMonitor",
        description="Self-hosted monitoring — alternative moderne à Uptime-Kuma.",
        version="0.1.0",
        debug=settings.app_debug,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/metrics", "/health"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    app.mount(
        "/static",
        StaticFiles(directory=str(_PROJECT_ROOT / "static")),
        name="static",
    )
    app.include_router(api_router)
    app.include_router(web_router)
    return app


app = create_app()
