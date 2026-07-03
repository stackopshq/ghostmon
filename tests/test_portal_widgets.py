"""Portal resource-server + bento widget endpoints.

Two layers:
- `GhostAuthValidator` in isolation — real RS256/Ed25519 tokens verified against
  an injected JWKS (no network), plus aud/iss/exp rejection.
- The `/api/v1/widgets/*` routes end to end over the ASGI app against a live
  Postgres, with the validator monkeypatched to trust our test keys — proving
  the token gate, the entitlement gate, and the per-user scoping/SQL.
"""

from __future__ import annotations

from typing import Any

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet, OKPKey, RSAKey

from app.api.deps import portal as portal_dep
from app.core.models.monitor import Monitor, MonitorStatus, MonitorType
from app.core.models.monitor_result import MonitorResult, ProbeStatus
from app.core.security.resource_server import GhostAuthValidator, TokenValidationError
from app.core.services.user_service import UserService

ISS = "https://idp.ghost.local"
AUD = "ghostmon"
ENTITLEMENT = "ghostsuite:ghostmon"

_RSA = RSAKey.generate_key(2048, parameters={"kid": "r1"}, private=True)
_ED = OKPKey.generate_key("Ed25519", parameters={"kid": "e1"}, private=True)
_PUBLIC_JWKS = KeySet([_RSA, _ED]).as_dict(private=False)


def _token(*, alg: str = "RS256", kid: str = "r1", key: Any = _RSA, **overrides: Any) -> str:
    claims: dict[str, Any] = {
        "iss": ISS,
        "aud": AUD,
        "sub": "portal-user",
        "exp": 9_999_999_999,
        "iat": 1,
        "scope": f"openid {ENTITLEMENT}",
        **overrides,
    }
    return jwt.encode({"alg": alg, "kid": kid}, claims, key, algorithms=[alg])


def _validator() -> GhostAuthValidator:
    v = GhostAuthValidator(issuer=ISS, audience=AUD)
    # Inject the JWKS so verify() does no network I/O.
    v._jwks = KeySet.import_key_set(_PUBLIC_JWKS)
    v._jwks_expiry = 9_999_999_999.0
    return v


# ── Validator unit tests (no DB, no network) ───────────────────────────────


async def test_validator_accepts_rs256() -> None:
    claims = await _validator().verify(_token(alg="RS256", kid="r1", key=_RSA))
    assert claims["sub"] == "portal-user"


async def test_validator_accepts_eddsa() -> None:
    # GhostAuth realms may sign with Ed25519 — must validate (python-jose can't).
    claims = await _validator().verify(_token(alg="EdDSA", kid="e1", key=_ED, sub="ed"))
    assert claims["sub"] == "ed"


async def test_validator_rejects_wrong_audience() -> None:
    with pytest.raises(TokenValidationError):
        await _validator().verify(_token(aud="someone-else"))


async def test_validator_rejects_wrong_issuer() -> None:
    with pytest.raises(TokenValidationError):
        await _validator().verify(_token(iss="https://evil"))


async def test_validator_rejects_expired() -> None:
    with pytest.raises(TokenValidationError):
        await _validator().verify(_token(exp=1))


async def test_validator_rejects_garbage() -> None:
    with pytest.raises(TokenValidationError):
        await _validator().verify("not-a-jwt")


# ── Route integration tests (live Postgres) ────────────────────────────────


@pytest.fixture(autouse=True)
def _trust_test_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(portal_dep, "get_ghostauth_validator", _validator)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_monitors(session: Any, owner_id: Any, statuses: list[MonitorStatus]) -> list[Any]:
    monitors = []
    for i, st in enumerate(statuses):
        m = Monitor(
            name=f"mon-{i}",
            type=MonitorType.HTTP,
            url="https://example.com",
            status=st,
            owner_id=owner_id,
        )
        session.add(m)
        monitors.append(m)
    await session.commit()
    for m in monitors:
        await session.refresh(m)
    return monitors


async def test_wellknown_manifest_is_public(client: Any) -> None:
    resp = await client.get("/.well-known/ghostapp.yaml")
    assert resp.status_code == 200
    assert "id: ghostmon" in resp.text
    assert "ghostsuite:ghostmon" in resp.text


async def test_uptime_widget_counts_user_monitors(client: Any, session: Any) -> None:
    user = await UserService(session).upsert_oidc("portal-user", "u@ghost.local", None)
    await _seed_monitors(
        session,
        user.id,
        [MonitorStatus.UP, MonitorStatus.UP, MonitorStatus.DOWN, MonitorStatus.PAUSED],
    )
    resp = await client.get("/api/v1/widgets/uptime", headers=_bearer(_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == "2/3"  # paused excluded from the total
    assert body["trend"] == "down"


async def test_latency_widget_returns_points(client: Any, session: Any) -> None:
    user = await UserService(session).upsert_oidc("portal-user", "u@ghost.local", None)
    (monitor,) = await _seed_monitors(session, user.id, [MonitorStatus.UP])
    for ms in (120, 90, 150):
        session.add(MonitorResult(monitor_id=monitor.id, status=ProbeStatus.UP, latency_ms=ms))
    await session.commit()
    resp = await client.get("/api/v1/widgets/latency", headers=_bearer(_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["variant"] == "line" and body["unit"] == "ms"
    assert sorted(body["points"]) == [90.0, 120.0, 150.0]


async def test_widget_requires_a_token(client: Any) -> None:
    resp = await client.get("/api/v1/widgets/uptime")
    assert resp.status_code == 401


async def test_widget_requires_entitlement(client: Any) -> None:
    # Valid token but missing ghostsuite:ghostmon in scope/groups.
    resp = await client.get("/api/v1/widgets/uptime", headers=_bearer(_token(scope="openid")))
    assert resp.status_code == 403


async def test_widget_unknown_subject_is_empty(client: Any) -> None:
    # Valid, entitled token whose subject was never linked to a local user.
    resp = await client.get("/api/v1/widgets/uptime", headers=_bearer(_token(sub="ghost")))
    assert resp.status_code == 200
    assert resp.json()["value"] == "—"
