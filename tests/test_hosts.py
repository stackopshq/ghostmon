"""Hosts, items and metric history: CRUD API, value ingestion and ownership."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.models.host import Host, Item, ItemValueType
from app.core.services.host_service import ItemService


async def _create_host(
    client: httpx.AsyncClient, headers: dict[str, str], name: str = "web-01"
) -> str:
    resp = await client.post("/api/hosts", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_item(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    host_id: str,
    *,
    key: str = "latency",
    value_type: str = "float",
) -> str:
    resp = await client.post(
        f"/api/hosts/{host_id}/items",
        headers=headers,
        json={"key": key, "name": key.title(), "value_type": value_type, "units": "ms"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_host_and_item_crud(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    host_id = await _create_host(client, auth_headers)

    listed = await client.get("/api/hosts", headers=auth_headers)
    assert [h["id"] for h in listed.json()] == [host_id]

    patched = await client.patch(
        f"/api/hosts/{host_id}", headers=auth_headers, json={"description": "edge node"}
    )
    assert patched.status_code == 200
    assert patched.json()["description"] == "edge node"

    item_id = await _create_item(client, auth_headers, host_id)
    items = await client.get(f"/api/hosts/{host_id}/items", headers=auth_headers)
    assert [i["id"] for i in items.json()] == [item_id]

    deleted = await client.delete(f"/api/hosts/{host_id}", headers=auth_headers)
    assert deleted.status_code == 204
    # Cascade removes the item with the host.
    gone = await client.get(f"/api/hosts/{host_id}", headers=auth_headers)
    assert gone.status_code == 404


async def test_ingest_and_read_numeric_history(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    host_id = await _create_host(client, auth_headers)
    item_id = await _create_item(client, auth_headers, host_id)

    for v in (120, 250.5, 90):
        resp = await client.post(
            f"/api/hosts/{host_id}/items/{item_id}/values",
            headers=auth_headers,
            json={"value": v},
        )
        assert resp.status_code == 201, resp.text

    history = await client.get(f"/api/hosts/{host_id}/items/{item_id}/values", headers=auth_headers)
    assert history.status_code == 200
    rows = history.json()
    assert len(rows) == 3
    # Newest first; numeric values land in value_num.
    assert [r["value_num"] for r in rows] == [90.0, 250.5, 120.0]
    assert all(r["value_text"] is None for r in rows)


async def test_ingest_text_value_for_text_item(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    host_id = await _create_host(client, auth_headers)
    item_id = await _create_item(client, auth_headers, host_id, key="state", value_type="text")
    resp = await client.post(
        f"/api/hosts/{host_id}/items/{item_id}/values",
        headers=auth_headers,
        json={"value": "running"},
    )
    assert resp.status_code == 201
    assert resp.json()["value_text"] == "running"
    assert resp.json()["value_num"] is None


async def test_numeric_item_rejects_text_value(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    host_id = await _create_host(client, auth_headers)
    item_id = await _create_item(client, auth_headers, host_id)
    resp = await client.post(
        f"/api/hosts/{host_id}/items/{item_id}/values",
        headers=auth_headers,
        json={"value": "not-a-number"},
    )
    assert resp.status_code == 422


async def test_other_users_host_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any
) -> None:
    from app.core.schemas.user import UserCreate
    from app.core.services.user_service import UserService

    other = await UserService(session).create_local(
        UserCreate(email="carol@example.com", password="carol-secret-password", full_name="Carol")
    )
    host = Host(name="carol-host", owner_id=other.id)
    session.add(host)
    await session.commit()
    await session.refresh(host)

    resp = await client.get(f"/api/hosts/{host.id}", headers=auth_headers)
    assert resp.status_code == 404


async def test_record_value_routing_service(session: Any, user: Any) -> None:
    host = Host(name="svc-host", owner_id=user.id)
    session.add(host)
    await session.commit()
    await session.refresh(host)
    item = Item(host_id=host.id, key="cpu", name="CPU", value_type=ItemValueType.FLOAT, interval=60)
    session.add(item)
    await session.commit()
    await session.refresh(item)

    svc = ItemService(session)
    sample = await svc.record_value(item, 42.0, datetime.now(UTC))
    assert sample.value_num == 42.0
    assert sample.value_text is None

    with pytest.raises(ValueError):
        await svc.record_value(item, "boom")
