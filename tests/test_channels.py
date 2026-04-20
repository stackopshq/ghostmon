from typing import Any

import httpx


async def _create_webhook(
    client: httpx.AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    payload = {
        "name": "ops-webhook",
        "is_enabled": True,
        "config": {
            "type": "webhook",
            "url": "https://hooks.example.com/incoming",
        },
    }
    payload.update(overrides)
    response = await client.post("/api/channels", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def test_create_email_channel(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/channels",
        headers=auth_headers,
        json={
            "name": "oncall-email",
            "config": {"type": "email", "to": "oncall@example.com"},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "email"
    assert body["config"]["to"] == "oncall@example.com"
    assert body["is_enabled"] is True


async def test_create_webhook_channel_with_secret(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/channels",
        headers=auth_headers,
        json={
            "name": "signed-hook",
            "config": {
                "type": "webhook",
                "url": "https://hooks.example.com/x",
                "secret": "supersecret",
            },
        },
    )
    assert response.status_code == 201
    assert response.json()["config"]["secret"] == "supersecret"


async def test_webhook_secret_minimum_length(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/channels",
        headers=auth_headers,
        json={
            "name": "short",
            "config": {
                "type": "webhook",
                "url": "https://hooks.example.com/x",
                "secret": "tooshor",
            },
        },
    )
    assert response.status_code == 422


async def test_email_requires_valid_address(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/channels",
        headers=auth_headers,
        json={"name": "bad", "config": {"type": "email", "to": "not-an-email"}},
    )
    assert response.status_code == 422


async def test_webhook_requires_url(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/channels",
        headers=auth_headers,
        json={"name": "noop", "config": {"type": "webhook"}},
    )
    assert response.status_code == 422


async def test_channel_name_must_be_unique_per_owner(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create_webhook(client, auth_headers, name="dup")
    second = await client.post(
        "/api/channels",
        headers=auth_headers,
        json={
            "name": "dup",
            "config": {"type": "webhook", "url": "https://b.example.com"},
        },
    )
    assert second.status_code == 409


async def test_list_get_patch_delete_channel(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create_webhook(client, auth_headers, name="wh")

    listed = await client.get("/api/channels", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    got = await client.get(f"/api/channels/{created['id']}", headers=auth_headers)
    assert got.status_code == 200

    patched = await client.patch(
        f"/api/channels/{created['id']}",
        json={"is_enabled": False, "name": "wh-disabled"},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["is_enabled"] is False
    assert body["name"] == "wh-disabled"

    deleted = await client.delete(f"/api/channels/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    gone = await client.get(f"/api/channels/{created['id']}", headers=auth_headers)
    assert gone.status_code == 404


async def test_channel_isolation_between_users(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any
) -> None:
    from app.core.schemas.user import UserCreate
    from app.core.services.user_service import UserService

    created = await _create_webhook(client, auth_headers, name="alice-hook")

    await UserService(session).create_local(
        UserCreate(email="eve@example.com", password="eve-password-value"),
    )
    login = await client.post(
        "/api/auth/login",
        data={"username": "eve@example.com", "password": "eve-password-value"},
    )
    eve_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/api/channels", headers=eve_headers)).json() == []
    assert (
        await client.get(f"/api/channels/{created['id']}", headers=eve_headers)
    ).status_code == 404


async def test_attach_detach_channel_to_monitor(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    mon = await client.post(
        "/api/monitors",
        headers=auth_headers,
        json={
            "name": "with-channel",
            "type": "http",
            "url": "https://example.com",
            "interval": 60,
        },
    )
    assert mon.status_code == 201
    monitor_id = mon.json()["id"]

    channel = await _create_webhook(client, auth_headers, name="attached")
    channel_id = channel["id"]

    attach = await client.post(
        f"/api/monitors/{monitor_id}/channels",
        json={"channel_id": channel_id},
        headers=auth_headers,
    )
    assert attach.status_code == 204

    # Idempotent: re-attach is not an error.
    reattach = await client.post(
        f"/api/monitors/{monitor_id}/channels",
        json={"channel_id": channel_id},
        headers=auth_headers,
    )
    assert reattach.status_code == 204

    listed = await client.get(f"/api/monitors/{monitor_id}/channels", headers=auth_headers)
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [channel_id]

    detach = await client.delete(
        f"/api/monitors/{monitor_id}/channels/{channel_id}", headers=auth_headers
    )
    assert detach.status_code == 204

    after_detach = await client.get(f"/api/monitors/{monitor_id}/channels", headers=auth_headers)
    assert after_detach.json() == []


async def test_attach_unknown_channel_returns_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    mon = await client.post(
        "/api/monitors",
        headers=auth_headers,
        json={
            "name": "x",
            "type": "http",
            "url": "https://example.com",
            "interval": 60,
        },
    )
    monitor_id = mon.json()["id"]
    response = await client.post(
        f"/api/monitors/{monitor_id}/channels",
        json={"channel_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers,
    )
    assert response.status_code == 404
