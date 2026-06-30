"""Liveness and readiness probe tests.

Mirrors the ghostbit convention: /healthz never touches the database (a DB
outage must not restart the container), /readyz returns 503 when the database
is unreachable so the ingress drains traffic instead.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app import __version__
from app.api.routes import health


async def test_healthz_is_ok_and_does_not_touch_db(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


async def test_readyz_ok_when_database_is_up(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readyz_returns_503_when_database_is_down(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _BrokenEngine:
        def connect(self) -> Any:
            raise OSError("database unreachable")

    monkeypatch.setattr(health, "engine", _BrokenEngine())

    response = await client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["version"] == __version__
