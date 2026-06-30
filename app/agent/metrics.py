"""Host metric collection for the reference agent.

Reads Linux `/proc` and `statvfs` directly — no third-party dependency, nothing
leaves the host but the samples the agent pushes. Pure parsers are split out so
they are unit-testable without touching the real filesystem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Sample:
    key: str
    value: float
    units: str | None = None


def parse_loadavg(text: str) -> float:
    """1-minute load average from the contents of /proc/loadavg."""
    return float(text.split()[0])


def parse_mem_used_percent(text: str) -> float:
    """Used-memory percentage from the contents of /proc/meminfo."""
    fields: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if rest.strip():
            fields[key.strip()] = int(rest.strip().split()[0])  # value in kB
    total = fields.get("MemTotal", 0)
    if total <= 0:
        return 0.0
    available = fields.get("MemAvailable", fields.get("MemFree", 0))
    return round(100.0 * (total - available) / total, 2)


def disk_used_percent(path: str = "/") -> float:
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    if total <= 0:
        return 0.0
    free = st.f_bavail * st.f_frsize
    return round(100.0 * (total - free) / total, 2)


def collect() -> list[Sample]:
    """Collect the instantaneous system samples available on this host."""
    samples: list[Sample] = []
    try:
        samples.append(Sample("system.load1", parse_loadavg(Path("/proc/loadavg").read_text())))
    except OSError:
        pass
    try:
        samples.append(
            Sample(
                "system.mem.used_pct",
                parse_mem_used_percent(Path("/proc/meminfo").read_text()),
                "%",
            )
        )
    except OSError:
        pass
    try:
        samples.append(Sample("system.disk.used_pct", disk_used_percent("/"), "%"))
    except OSError:
        pass
    return samples
