from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.session import Base
from app.core.models.mixins import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.core.models.monitor import Monitor


class Severity(enum.StrEnum):
    """Problem severity, ordered from least to most urgent (definition order is
    the rank, used for severity-based alert routing)."""

    INFO = "info"
    WARNING = "warning"
    AVERAGE = "average"
    HIGH = "high"
    DISASTER = "disaster"

    @property
    def rank(self) -> int:
        return list(Severity).index(self)


class TriggerMetric(enum.StrEnum):
    """The collected signal a trigger evaluates. Intentionally a single value for
    now (the universally-available probe metric); the enum is the extension point
    for TLS days-to-expiry, HTTP status, agent metrics, etc."""

    LATENCY_MS = "latency_ms"


class TriggerOperator(enum.StrEnum):
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"


class TriggerState(enum.StrEnum):
    OK = "ok"
    PROBLEM = "problem"


class Trigger(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "triggers"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    metric: Mapped[TriggerMetric] = mapped_column(
        Enum(TriggerMetric, name="trigger_metric"), nullable=False
    )
    operator: Mapped[TriggerOperator] = mapped_column(
        Enum(TriggerOperator, name="trigger_operator"), nullable=False
    )
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="alert_severity"), nullable=False
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    state: Mapped[TriggerState] = mapped_column(
        Enum(TriggerState, name="trigger_state"),
        nullable=False,
        default=TriggerState.OK,
        # Native enums store the member *name*; server_default must match (OK, not ok).
        server_default="OK",
    )
    state_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    monitor: Mapped[Monitor] = relationship(back_populates="triggers", lazy="noload")
