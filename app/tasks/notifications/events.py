from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.models.monitor import MonitorStatus, MonitorType


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

    def payload(self) -> dict[str, Any]:
        return {
            "event": "status_change",
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
