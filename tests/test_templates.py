"""Item templates: CRUD, item definitions, and applying them to a host."""

from __future__ import annotations

from typing import Any

import httpx


async def _create_template(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/templates", headers=headers, json={"name": "linux-server", "description": "base"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_item(
    client: httpx.AsyncClient, headers: dict[str, str], template_id: str, key: str
) -> None:
    resp = await client.post(
        f"/api/templates/{template_id}/items",
        headers=headers,
        json={"key": key, "name": key, "value_type": "float", "units": "%"},
    )
    assert resp.status_code == 201, resp.text


async def _create_host(client: httpx.AsyncClient, headers: dict[str, str], name: str) -> str:
    resp = await client.post("/api/hosts", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_template_crud_and_items(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    template_id = await _create_template(client, auth_headers)

    listed = await client.get("/api/templates", headers=auth_headers)
    assert [t["id"] for t in listed.json()] == [template_id]

    await _add_item(client, auth_headers, template_id, "system.cpu.util")
    await _add_item(client, auth_headers, template_id, "system.mem.used_pct")
    items = await client.get(f"/api/templates/{template_id}/items", headers=auth_headers)
    assert {i["key"] for i in items.json()} == {"system.cpu.util", "system.mem.used_pct"}

    deleted = await client.delete(f"/api/templates/{template_id}", headers=auth_headers)
    assert deleted.status_code == 204


async def test_apply_template_to_host_is_idempotent(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    template_id = await _create_template(client, auth_headers)
    await _add_item(client, auth_headers, template_id, "system.cpu.util")
    await _add_item(client, auth_headers, template_id, "system.mem.used_pct")
    host_id = await _create_host(client, auth_headers, "web-01")

    first = await client.post(
        f"/api/templates/{template_id}/apply", headers=auth_headers, json={"host_id": host_id}
    )
    assert first.status_code == 200
    assert first.json() == {"created": 2, "skipped": 0}

    # The host now has both items.
    items = await client.get(f"/api/hosts/{host_id}/items", headers=auth_headers)
    assert {i["key"] for i in items.json()} == {"system.cpu.util", "system.mem.used_pct"}

    # Re-applying creates nothing new.
    again = await client.post(
        f"/api/templates/{template_id}/apply", headers=auth_headers, json={"host_id": host_id}
    )
    assert again.json() == {"created": 0, "skipped": 2}


async def test_apply_to_unowned_host_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any
) -> None:
    from app.core.models.host import Host
    from app.core.schemas.user import UserCreate
    from app.core.services.user_service import UserService

    template_id = await _create_template(client, auth_headers)
    other = await UserService(session).create_local(
        UserCreate(email="dave@example.com", password="dave-secret-password", full_name="Dave")
    )
    host = Host(name="daves-host", owner_id=other.id)
    session.add(host)
    await session.commit()
    await session.refresh(host)

    resp = await client.post(
        f"/api/templates/{template_id}/apply",
        headers=auth_headers,
        json={"host_id": str(host.id)},
    )
    assert resp.status_code == 404


async def test_other_users_template_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any
) -> None:
    from app.core.models.template import Template
    from app.core.schemas.user import UserCreate
    from app.core.services.user_service import UserService

    other = await UserService(session).create_local(
        UserCreate(email="erin@example.com", password="erin-secret-password", full_name="Erin")
    )
    template = Template(name="erins-template", owner_id=other.id)
    session.add(template)
    await session.commit()
    await session.refresh(template)

    resp = await client.get(f"/api/templates/{template.id}", headers=auth_headers)
    assert resp.status_code == 404
