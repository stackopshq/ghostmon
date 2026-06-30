"""Ingestion tokens and the agent-facing token-authenticated ingest endpoint."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.services.ingestion_token_service import IngestionTokenService


async def _create_host(client: httpx.AsyncClient, headers: dict[str, str], name: str) -> None:
    resp = await client.post("/api/hosts", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text


async def _make_token(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post("/api/ingest-tokens", headers=headers, json={"name": "agent-1"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token"].startswith("gmi_")
    return body["token"]


async def test_token_lifecycle(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    create = await client.post("/api/ingest-tokens", headers=auth_headers, json={"name": "agent"})
    assert create.status_code == 201
    token_id = create.json()["id"]

    listed = await client.get("/api/ingest-tokens", headers=auth_headers)
    assert [t["id"] for t in listed.json()] == [token_id]
    # The secret is never returned by the list endpoint.
    assert "token" not in listed.json()[0]

    deleted = await client.delete(f"/api/ingest-tokens/{token_id}", headers=auth_headers)
    assert deleted.status_code == 204


async def test_ingest_auto_creates_trapper_item(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create_host(client, auth_headers, "web-01")
    token = await _make_token(client, auth_headers)

    resp = await client.post(
        "/api/ingest",
        headers={"X-Ingest-Token": token},
        json={"host": "web-01", "key": "system.cpu.util", "value": 42.5, "units": "%"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["value_num"] == 42.5

    # The item was created on first push and now carries the sample.
    hosts = await client.get("/api/hosts", headers=auth_headers)
    host_id = hosts.json()[0]["id"]
    items = await client.get(f"/api/hosts/{host_id}/items", headers=auth_headers)
    assert [i["key"] for i in items.json()] == ["system.cpu.util"]


async def test_ingest_unknown_host_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    token = await _make_token(client, auth_headers)
    resp = await client.post(
        "/api/ingest",
        headers={"X-Ingest-Token": token},
        json={"host": "ghost", "key": "x", "value": 1},
    )
    assert resp.status_code == 404


async def test_ingest_requires_valid_token(client: httpx.AsyncClient) -> None:
    missing = await client.post("/api/ingest", json={"host": "h", "key": "k", "value": 1})
    assert missing.status_code == 401
    bad = await client.post(
        "/api/ingest",
        headers={"X-Ingest-Token": "gmi_not-a-real-token"},
        json={"host": "h", "key": "k", "value": 1},
    )
    assert bad.status_code == 401


async def test_authenticate_stamps_last_used(session: Any, user: Any) -> None:
    service = IngestionTokenService(session)
    token, plaintext = await service.create(user.id, "agent")
    assert token.last_used_at is None

    resolved = await service.authenticate(plaintext)
    assert resolved is not None
    assert resolved.id == user.id

    await session.refresh(token)
    assert token.last_used_at is not None
    assert await service.authenticate("gmi_wrong") is None
