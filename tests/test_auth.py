from typing import Any

import httpx


async def test_login_returns_jwt(client: httpx.AsyncClient, user: Any) -> None:
    response = await client.post(
        "/api/auth/login",
        data={"username": "alice@example.com", "password": "alice-secret-password"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] == 3600


async def test_login_wrong_password_returns_401(client: httpx.AsyncClient, user: Any) -> None:
    response = await client.post(
        "/api/auth/login",
        data={"username": "alice@example.com", "password": "wrong-password-value"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_login_unknown_user_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/auth/login",
        data={"username": "ghost@example.com", "password": "whatever-long-pass"},
    )
    assert response.status_code == 401


async def test_login_email_case_insensitive(client: httpx.AsyncClient, user: Any) -> None:
    response = await client.post(
        "/api/auth/login",
        data={"username": "ALICE@EXAMPLE.COM", "password": "alice-secret-password"},
    )
    assert response.status_code == 200


async def test_me_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


async def test_me_returns_profile(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["full_name"] == "Alice"
    assert body["auth_provider"] == "local"
    assert body["is_active"] is True


async def test_me_with_garbage_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


async def test_oidc_routes_404_when_disabled(client: httpx.AsyncClient) -> None:
    login = await client.get("/api/auth/oidc/login")
    callback = await client.get("/api/auth/oidc/callback")
    assert login.status_code == 404
    assert callback.status_code == 404
