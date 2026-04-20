from typing import Any

import pytest

from app.core.models.user import AuthProvider
from app.core.schemas.user import UserCreate
from app.core.services.user_service import UserService


async def test_create_local_persists_and_normalizes_email(session: Any) -> None:
    service = UserService(session)
    user = await service.create_local(
        UserCreate(
            email="Bob@Example.COM",
            password="bob-secret-password",
            full_name="Bob",
        )
    )
    assert user.email == "bob@example.com"
    assert user.auth_provider == AuthProvider.LOCAL
    assert user.password_hash is not None
    assert user.password_hash != "bob-secret-password"


async def test_get_by_email_is_case_insensitive(session: Any) -> None:
    service = UserService(session)
    await service.create_local(
        UserCreate(email="carol@example.com", password="carol-long-password")
    )
    assert (await service.get_by_email("CAROL@EXAMPLE.COM")) is not None


async def test_authenticate_local_success_and_failure(session: Any) -> None:
    service = UserService(session)
    await service.create_local(UserCreate(email="dan@example.com", password="dan-secret-password"))

    ok = await service.authenticate_local("dan@example.com", "dan-secret-password")
    assert ok is not None

    wrong = await service.authenticate_local("dan@example.com", "not-the-password")
    assert wrong is None

    unknown = await service.authenticate_local("ghost@example.com", "whatever")
    assert unknown is None


async def test_upsert_oidc_creates_then_updates(session: Any) -> None:
    service = UserService(session)
    first = await service.upsert_oidc(
        subject="sub-123", email="OIDC@example.com", full_name="First"
    )
    assert first.email == "oidc@example.com"
    assert first.auth_provider == AuthProvider.OIDC
    assert first.oidc_subject == "sub-123"

    second = await service.upsert_oidc(
        subject="sub-123", email="oidc-renamed@example.com", full_name="Renamed"
    )
    assert second.id == first.id
    assert second.email == "oidc-renamed@example.com"
    assert second.full_name == "Renamed"


async def test_short_password_rejected_at_schema_level() -> None:
    with pytest.raises(ValueError):
        UserCreate(email="x@example.com", password="short")
