"""Host metric collection for the reference agent.

Reads Linux `/proc` and `statvfs` directly — no third-party dependency, nothing
leaves the host but the samples the agent pushes. Pure parsers are split out so
they are unit-testable without touching the real filesystem.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

# (idle, total) jiffy counters read from /proc/stat.
CpuTimes = tuple[int, int]


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


def read_cpu_times(text: str) -> CpuTimes:
    """(idle, total) jiffies from the aggregate `cpu` line of /proc/stat."""
    nums = [int(x) for x in text.splitlines()[0].split()[1:]]
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)  # idle + iowait
    return idle, sum(nums)


def cpu_used_percent(prev: CpuTimes, cur: CpuTimes) -> float:
    """Busy-CPU percentage from two /proc/stat readings."""
    idle_delta = cur[0] - prev[0]
    total_delta = cur[1] - prev[1]
    if total_delta <= 0:
        return 0.0
    return round(100.0 * (1 - idle_delta / total_delta), 2)


def sample_cpu_percent(interval: float = 0.2) -> float | None:
    """Sample CPU busy % by reading /proc/stat twice `interval` seconds apart."""
    try:
        prev = read_cpu_times(Path("/proc/stat").read_text())
        time.sleep(interval)
        cur = read_cpu_times(Path("/proc/stat").read_text())
    except OSError:
        return None
    return cpu_used_percent(prev, cur)


def collect() -> list[Sample]:
    """Collect the system samples available on this host."""
    samples: list[Sample] = []
    cpu = sample_cpu_percent()
    if cpu is not None:
        samples.append(Sample("system.cpu.used_pct", cpu, "%"))
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
