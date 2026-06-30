"""Hardening from the pentest: CSRF origin-check, cookie Secure, is_active on the
web cookie surface, and constant-time login paths."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.services.user_service import UserService


async def test_csrf_blocks_cross_origin_unsafe_request(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login",
        data={"username": "a@b.io", "password": "whatever-1234"},
        headers={"origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert "cross-origin" in resp.text.lower()


async def test_csrf_allows_request_without_origin(client: httpx.AsyncClient) -> None:
    # Non-browser clients (agent, curl) omit Origin and must not be blocked.
    resp = await client.post(
        "/api/auth/login",
        data={"username": "a@b.io", "password": "whatever-1234"},
    )
    assert resp.status_code != 403  # reaches auth (401 for bad creds), not CSRF-blocked


def test_cookie_secure_follows_environment() -> None:
    key = "x" * 16
    assert Settings(app_secret_key=key, app_env="development").cookie_secure is False
    assert Settings(app_secret_key=key, app_env="production").cookie_secure is True
    assert Settings(app_secret_key=key, app_env="staging").cookie_secure is True


async def test_deactivated_user_loses_web_access(
    web_client: httpx.AsyncClient, session: Any, user: Any
) -> None:
    # web_client is authenticated as `user`; deactivating must revoke web access now.
    home = await web_client.get("/hosts")
    assert home.status_code == 200

    user.is_active = False
    session.add(user)
    await session.commit()

    after = await web_client.get("/hosts")
    assert after.status_code == 303
    assert "/login" in after.headers.get("location", "")


async def test_authenticate_local_rejects_unknown_wrong_and_inactive(
    session: Any, user: Any
) -> None:
    svc = UserService(session)
    # Unknown email exercises the dummy-verify (timing-equalising) path without error.
    assert await svc.authenticate_local("nobody@example.com", "some-password-12") is None
    assert await svc.authenticate_local(user.email, "wrong-password-12") is None
    assert await svc.authenticate_local(user.email, "alice-secret-password") is not None

    user.is_active = False
    await session.commit()
    assert await svc.authenticate_local(user.email, "alice-secret-password") is None
