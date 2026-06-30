from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.models.discovery import DiscoveryMethod

# Cap the scan size so a typo (e.g. a /8) can't launch millions of probes.
MAX_SCAN_HOSTS = 1024


class DiscoveryRuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    cidr: str = Field(min_length=1, max_length=64)
    method: DiscoveryMethod = DiscoveryMethod.PING
    port: int | None = Field(default=None, ge=1, le=65535)
    template_id: uuid.UUID | None = None
    interval_seconds: int = Field(default=3600, ge=60, le=604800)
    is_enabled: bool = True

    @model_validator(mode="after")
    def _validate(self) -> DiscoveryRuleBase:
        try:
            network = ipaddress.ip_network(self.cidr, strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid CIDR: {exc}") from exc
        hosts = (
            network.num_addresses
            if network.prefixlen >= network.max_prefixlen - 1
            else sum(1 for _ in network.hosts())
        )
        if hosts > MAX_SCAN_HOSTS:
            raise ValueError(f"CIDR covers {hosts} hosts; max is {MAX_SCAN_HOSTS}")
        if self.method is DiscoveryMethod.TCP and self.port is None:
            raise ValueError("port is required for TCP discovery")
        return self


class DiscoveryRuleCreate(DiscoveryRuleBase):
    pass


class DiscoveryRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    cidr: str
    method: DiscoveryMethod
    port: int | None
    template_id: uuid.UUID | None
    interval_seconds: int
    is_enabled: bool
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime
