"""OIDC SSO flow: login redirect, callback provisioning, claim/error handling.

The IdP is faked by patching the auth route's settings (to enable OIDC) and its
OIDC provider (to script `authorize_redirect` / `authorize_access_token`), so the
route logic — user provisioning, cookie, claim and error handling — is exercised
without a live identity provider.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.routes import auth as auth_module
from app.core.config import get_settings
from app.core.models.user import AuthProvider, User


class _FakeClient:
    def __init__(self, token: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self._token = token or {}
        self._error = error

    async def authorize_redirect(self, request: Any, redirect_uri: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"https://idp.example/authorize?redirect_uri={redirect_uri}", status_code=302
        )

    async def authorize_access_token(self, request: Any) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return self._token


class _FakeProvider:
    def __init__(self, client: _FakeClient) -> None:
        self._client = client

    @property
    def client(self) -> _FakeClient:
        return self._client


@pytest.fixture
def enable_oidc(monkeypatch: pytest.MonkeyPatch) -> None:
    enabled = get_settings().model_copy(update={"oidc_enabled": True})
    monkeypatch.setattr(auth_module, "get_settings", lambda: enabled)


def _patch_provider(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    monkeypatch.setattr(auth_module, "get_oidc_provider", lambda: _FakeProvider(client))


async def test_oidc_login_redirects_to_provider(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, enable_oidc: None
) -> None:
    _patch_provider(monkeypatch, _FakeClient())
    resp = await client.get("/api/auth/oidc/login")
    assert resp.status_code in (302, 303, 307)
    assert "idp.example/authorize" in resp.headers["location"]


async def test_oidc_callback_provisions_user_and_sets_cookie(
    client: httpx.AsyncClient,
    session: Any,
    monkeypatch: pytest.MonkeyPatch,
    enable_oidc: None,
) -> None:
    token = {"userinfo": {"sub": "idp-sub-123", "email": "Sso@X.io", "name": "SSO User"}}
    _patch_provider(monkeypatch, _FakeClient(token=token))

    resp = await client.get("/api/auth/oidc/callback")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert "ghostmon_session=" in resp.headers.get("set-cookie", "")

    user = (
        await session.execute(select(User).where(User.oidc_subject == "idp-sub-123"))
    ).scalar_one()
    assert user.email == "sso@x.io"  # normalised
    assert user.auth_provider == AuthProvider.OIDC
    assert user.password_hash is None  # SSO-only account


async def test_oidc_callback_rejects_missing_email(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, enable_oidc: None
) -> None:
    _patch_provider(monkeypatch, _FakeClient(token={"userinfo": {"sub": "no-email"}}))
    resp = await client.get("/api/auth/oidc/callback")
    assert resp.status_code == 400


async def test_oidc_callback_does_not_leak_internal_errors(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, enable_oidc: None
) -> None:
    _patch_provider(monkeypatch, _FakeClient(error=RuntimeError("nonce mismatch leak-secret-xyz")))
    resp = await client.get("/api/auth/oidc/callback")
    assert resp.status_code == 401
    assert "leak-secret-xyz" not in resp.text


async def test_login_page_shows_sso_button_when_enabled(
    web_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes.web import auth as web_auth

    enabled = get_settings().model_copy(update={"oidc_enabled": True})
    monkeypatch.setattr(web_auth, "get_settings", lambda: enabled)
    page = await web_client.get("/login")
    assert page.status_code == 200
    assert "/api/auth/oidc/login" in page.text
