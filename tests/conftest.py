"""Test configuration.

Environment variables are set BEFORE any app import so that the settings
singleton (`@lru_cache get_settings()`) picks up the test database URL.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://ghostmon:ghostmon@localhost:5432/ghostmon_test",
)
os.environ.setdefault("APP_SECRET_KEY", "test-secret-at-least-16-characters-long")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("APP_DEBUG", "true")
os.environ.setdefault("OIDC_ENABLED", "false")

from collections.abc import AsyncIterator  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.api.main import create_app, noop_lifespan  # noqa: E402
from app.core.db.session import Base, SessionLocal, engine  # noqa: E402
from app.core.models import Monitor, MonitorResult, User  # noqa: E402,F401
from app.core.schemas.user import UserCreate  # noqa: E402
from app.core.services.user_service import UserService  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def _create_schema() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _truncate_tables() -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE users, monitors, monitor_results, "
                "notification_channels, monitor_channels, "
                "maintenances, maintenance_monitors RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
async def session() -> AsyncIterator[Any]:
    async with SessionLocal() as s:
        yield s


@pytest.fixture
def app() -> Any:
    return create_app(lifespan=noop_lifespan)


@pytest.fixture
async def client(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def user(session: Any) -> Any:
    return await UserService(session).create_local(
        UserCreate(
            email="alice@example.com",
            password="alice-secret-password",
            full_name="Alice",
        )
    )


@pytest.fixture
async def auth_headers(client: httpx.AsyncClient, user: Any) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login",
        data={"username": "alice@example.com", "password": "alice-secret-password"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def web_client(app: Any, user: Any) -> AsyncIterator[httpx.AsyncClient]:
    """httpx client pre-authenticated via the web /login form (cookie session)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/login",
            data={"email": "alice@example.com", "password": "alice-secret-password"},
        )
        assert response.status_code in (200, 303), response.text
        yield client
