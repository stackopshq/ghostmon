from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.notification_channel import NotificationChannel


class EscalationPolicy(UUIDPrimaryKey, Timestamped, Base):
    """An ordered escalation ladder applied to an owner's open, unacknowledged
    problems: each step notifies a channel after a delay. Acknowledging or
    resolving the problem stops the escalation."""

    __tablename__ = "escalation_policies"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")

    steps: Mapped[list[EscalationStep]] = relationship(
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="EscalationStep.step_order",
    )


class EscalationStep(UUIDPrimaryKey, Base):
    __tablename__ = "escalation_steps"
    __table_args__ = (
        UniqueConstraint("policy_id", "step_order", name="uq_escalation_steps_policy_order"),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("escalation_policies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 1-based position in the ladder; steps fire in ascending order.
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # Minutes after the problem opened at which this step notifies.
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    # When set, this is an auto-remediation step: instead of a plain notification it
    # POSTs a structured remediation intent (this command + the problem context) to
    # its webhook channel, for an external runbook to act on. The server never runs
    # commands itself.
    action_command: Mapped[str | None] = mapped_column(String(500), nullable=True)

    policy: Mapped[EscalationPolicy] = relationship(back_populates="steps")
    channel: Mapped[NotificationChannel] = relationship(lazy="noload")
