from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.models.monitor import MonitorStatus, MonitorType
from app.core.models.trigger import (
    Severity,
    TriggerMetric,
    TriggerOperator,
    TriggerState,
)


@dataclass(slots=True)
class AlertEvent:
    monitor_id: uuid.UUID
    monitor_name: str
    monitor_type: MonitorType
    monitor_url: str
    previous_status: MonitorStatus
    new_status: MonitorStatus
    latency_ms: int | None
    error: str | None
    timestamp: datetime

    @property
    def is_recovery(self) -> bool:
        return self.new_status == MonitorStatus.UP

    @property
    def severity(self) -> Severity:
        # Availability: going DOWN is urgent, recovering is informational.
        return Severity.INFO if self.is_recovery else Severity.HIGH

    def payload(self) -> dict[str, Any]:
        return {
            "event": "status_change",
            "severity": self.severity.value,
            "monitor": {
                "id": str(self.monitor_id),
                "name": self.monitor_name,
                "type": self.monitor_type.value,
                "url": self.monitor_url,
            },
            "previous_status": self.previous_status.value,
            "status": self.new_status.value,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(slots=True)
class TriggerAlertEvent:
    """A trigger crossing (or clearing) its threshold. Carries only the data an
    alert needs — no host internals beyond the monitor's public identity."""

    monitor_id: uuid.UUID
    monitor_name: str
    monitor_type: MonitorType
    monitor_url: str
    trigger_name: str
    severity: Severity
    metric: TriggerMetric | None
    operator: TriggerOperator
    threshold: float
    value: float
    new_state: TriggerState
    timestamp: datetime

    @property
    def is_recovery(self) -> bool:
        return self.new_state == TriggerState.OK

    def payload(self) -> dict[str, Any]:
        return {
            "event": "trigger",
            "severity": self.severity.value,
            "state": self.new_state.value,
            "monitor": {
                "id": str(self.monitor_id),
                "name": self.monitor_name,
                "type": self.monitor_type.value,
                "url": self.monitor_url,
            },
            "trigger": {
                "name": self.trigger_name,
                "metric": self.metric.value if self.metric else None,
                "operator": self.operator.value,
                "threshold": self.threshold,
                "value": self.value,
            },
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(slots=True)
class ItemTriggerAlertEvent:
    """An item trigger crossing its threshold. Routed through the host's channels."""

    host_id: uuid.UUID
    host_name: str
    item_key: str
    item_name: str
    trigger_name: str
    severity: Severity
    operator: TriggerOperator
    threshold: float
    value: float
    new_state: TriggerState
    timestamp: datetime

    @property
    def is_recovery(self) -> bool:
        return self.new_state == TriggerState.OK

    def payload(self) -> dict[str, Any]:
        return {
            "event": "item_trigger",
            "severity": self.severity.value,
            "state": self.new_state.value,
            "host": {"id": str(self.host_id), "name": self.host_name},
            "item": {"key": self.item_key, "name": self.item_name},
            "trigger": {
                "name": self.trigger_name,
                "operator": self.operator.value,
                "threshold": self.threshold,
                "value": self.value,
            },
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(slots=True)
class EscalationAlertEvent:
    """A scheduled escalation step notifying a specific channel about a problem that
    is still open and unacknowledged."""

    problem_id: uuid.UUID
    subject: str
    trigger_name: str
    severity: Severity
    step_order: int
    value: float | None
    started_at: datetime
    timestamp: datetime
    # When set, this step is an auto-remediation action (not a plain notification).
    action_command: str | None = None

    @property
    def is_recovery(self) -> bool:
        return False

    @property
    def is_remediation(self) -> bool:
        return self.action_command is not None

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "event": "remediation" if self.is_remediation else "escalation",
            "severity": self.severity.value,
            "step": self.step_order,
            "subject": self.subject,
            "trigger": {"name": self.trigger_name, "value": self.value},
            "problem_id": str(self.problem_id),
            "started_at": self.started_at.isoformat(),
            "timestamp": self.timestamp.isoformat(),
        }
        if self.action_command is not None:
            body["action"] = {"command": self.action_command}
        return body
