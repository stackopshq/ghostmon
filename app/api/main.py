from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.sessions import SessionMiddleware

from app.api.middleware import add_security_headers
from app.api.routes import api_router, health_router
from app.api.routes.web import router as web_router
from app.core.config import get_settings
from app.tasks.scheduler import build_scheduler

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


@asynccontextmanager
async def scheduler_lifespan(_: FastAPI) -> AsyncIterator[None]:
    scheduler = build_scheduler()
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


@asynccontextmanager
async def noop_lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


def create_app(*, lifespan: Lifespan = scheduler_lifespan) -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="GhostMonitor",
        description="Self-hosted infrastructure monitoring — a free Zabbix alternative.",
        version="0.1.0",
        debug=settings.app_debug,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret_key,
        same_site="lax",
        https_only=settings.app_env == "production",
    )
    add_security_headers(app)

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/metrics", "/healthz", "/readyz"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    app.mount(
        "/static",
        StaticFiles(directory=str(_PROJECT_ROOT / "static")),
        name="static",
    )
    app.include_router(health_router)
    app.include_router(api_router)
    app.include_router(web_router)
    return app


app = create_app()
