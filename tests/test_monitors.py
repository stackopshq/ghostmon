from typing import Any, cast

import httpx


async def _create_monitor(
    client: httpx.AsyncClient, auth_headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    payload = {
        "name": "example",
        "type": "http",
        "url": "https://example.com",
        "interval": 60,
    }
    payload.update(overrides)
    response = await client.post("/api/monitors", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


async def test_list_empty_for_new_user(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/monitors", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_create_monitor(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await _create_monitor(client, auth_headers, name="my-http")
    assert created["name"] == "my-http"
    assert created["type"] == "http"
    assert created["status"] == "pending"
    assert "id" in created
    assert "owner_id" in created


async def test_list_returns_created_monitors(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create_monitor(client, auth_headers, name="one")
    await _create_monitor(client, auth_headers, name="two")
    response = await client.get("/api/monitors", headers=auth_headers)
    names = {m["name"] for m in response.json()}
    assert names == {"one", "two"}


async def test_get_monitor_by_id(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await _create_monitor(client, auth_headers)
    response = await client.get(f"/api/monitors/{created['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_unknown_returns_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(
        "/api/monitors/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_update_monitor(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await _create_monitor(client, auth_headers, name="old-name")
    response = await client.patch(
        f"/api/monitors/{created['id']}",
        json={"name": "new-name", "status": "paused"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "new-name"
    assert body["status"] == "paused"
    # Unchanged fields remain
    assert body["url"] == "https://example.com"


async def test_delete_monitor(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await _create_monitor(client, auth_headers)
    delete = await client.delete(f"/api/monitors/{created['id']}", headers=auth_headers)
    assert delete.status_code == 204

    follow_up = await client.get(f"/api/monitors/{created['id']}", headers=auth_headers)
    assert follow_up.status_code == 404


async def test_create_without_auth_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/monitors",
        json={"name": "x", "type": "http", "url": "https://a.b", "interval": 60},
    )
    assert response.status_code == 401


async def test_invalid_type_returns_422(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/monitors",
        headers=auth_headers,
        json={"name": "x", "type": "bogus", "url": "https://a.b", "interval": 60},
    )
    assert response.status_code == 422


async def test_user_cannot_access_other_users_monitor(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any
) -> None:
    created = await _create_monitor(client, auth_headers, name="alice-mon")

    # Create a second user directly, then log in.
    from app.core.schemas.user import UserCreate
    from app.core.services.user_service import UserService

    await UserService(session).create_local(
        UserCreate(
            email="eve@example.com",
            password="eve-secret-password",
            full_name="Eve",
        )
    )
    login = await client.post(
        "/api/auth/login",
        data={"username": "eve@example.com", "password": "eve-secret-password"},
    )
    eve_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Eve sees 404 on all ownership-protected verbs.
    assert (
        await client.get(f"/api/monitors/{created['id']}", headers=eve_headers)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/monitors/{created['id']}",
            json={"name": "pwned"},
            headers=eve_headers,
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/monitors/{created['id']}", headers=eve_headers)
    ).status_code == 404

    # Eve's list is empty, Alice's monitor is intact.
    assert (await client.get("/api/monitors", headers=eve_headers)).json() == []
    alice_view = await client.get(f"/api/monitors/{created['id']}", headers=auth_headers)
    assert alice_view.status_code == 200
    assert alice_view.json()["name"] == "alice-mon"


async def test_interval_out_of_range_returns_422(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    too_small = await client.post(
        "/api/monitors",
        headers=auth_headers,
        json={"name": "x", "type": "http", "url": "https://a.b", "interval": 1},
    )
    assert too_small.status_code == 422

    too_big = await client.post(
        "/api/monitors",
        headers=auth_headers,
        json={"name": "x", "type": "http", "url": "https://a.b", "interval": 99999999},
    )
    assert too_big.status_code == 422


async def test_retries_default_values_on_create(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create_monitor(client, auth_headers)
    assert created["retries"] == 2
    assert created["retry_interval"] == 20


async def test_retries_custom_values_on_create(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create_monitor(client, auth_headers, retries=5, retry_interval=30)
    assert created["retries"] == 5
    assert created["retry_interval"] == 30


async def test_retries_out_of_range_returns_422(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    too_many = await client.post(
        "/api/monitors",
        headers=auth_headers,
        json={
            "name": "x",
            "type": "http",
            "url": "https://a.b",
            "interval": 60,
            "retries": 99,
        },
    )
    assert too_many.status_code == 422

    too_short = await client.post(
        "/api/monitors",
        headers=auth_headers,
        json={
            "name": "x",
            "type": "http",
            "url": "https://a.b",
            "interval": 60,
            "retry_interval": 1,
        },
    )
    assert too_short.status_code == 422


async def test_retries_patchable(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await _create_monitor(client, auth_headers)
    response = await client.patch(
        f"/api/monitors/{created['id']}",
        json={"retries": 0, "retry_interval": 300},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["retries"] == 0
    assert body["retry_interval"] == 300


async def test_results_endpoint_ownership_and_listing(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    session: Any,
    user: Any,
) -> None:
    from app.core.models.monitor_result import MonitorResult, ProbeStatus

    created = await _create_monitor(client, auth_headers, name="mon-with-results")
    monitor_id = created["id"]

    for status_ in (ProbeStatus.UP, ProbeStatus.DOWN, ProbeStatus.UP):
        session.add(
            MonitorResult(
                monitor_id=monitor_id,
                status=status_,
                latency_ms=42 if status_ is ProbeStatus.UP else None,
                error=None if status_ is ProbeStatus.UP else "boom",
            )
        )
    await session.commit()

    response = await client.get(
        f"/api/monitors/{monitor_id}/results?limit=10", headers=auth_headers
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 3
    # Newest first
    assert all(r["monitor_id"] == monitor_id for r in results)
    statuses = [r["status"] for r in results]
    assert set(statuses) == {"up", "down"}

    unknown_id = "00000000-0000-0000-0000-000000000000"
    not_found = await client.get(f"/api/monitors/{unknown_id}/results", headers=auth_headers)
    assert not_found.status_code == 404
