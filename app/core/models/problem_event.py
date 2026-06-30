from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.session import Base
from app.core.models.mixins import UUIDPrimaryKey
from app.core.models.trigger import Severity


class ProblemEvent(UUIDPrimaryKey, Base):
    """One problem occurrence: a trigger crossing into PROBLEM, optionally resolved
    and/or acknowledged. The timeline view of these is the operator's worklist.

    Identity (subject/severity) is snapshotted so the row stays meaningful for the
    trigger's lifetime, and `owner_id` scopes the timeline to its owner.
    """

    __tablename__ = "problem_events"

    trigger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("triggers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_name: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="alert_severity"), nullable=False
    )
    value: Mapped[float | None] = mapped_column(Float, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Highest escalation step already executed for this problem (0 = none yet).
    escalated_step: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
