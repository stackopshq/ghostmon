from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.monitor import Monitor


class AuthProvider(str, enum.Enum):
    LOCAL = "local"
    OIDC = "oidc"


class User(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    auth_provider: Mapped[AuthProvider] = mapped_column(
        Enum(AuthProvider, name="auth_provider"),
        nullable=False,
        default=AuthProvider.LOCAL,
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oidc_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    monitors: Mapped[list[Monitor]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
