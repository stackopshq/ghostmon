"""Reference agent: metric parsers, the no-token guard, and the push round."""

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from app.agent.metrics import (
    Sample,
    collect,
    disk_used_percent,
    parse_loadavg,
    parse_mem_used_percent,
)
from app.cli.main import app

runner = CliRunner()

_MEMINFO = """MemTotal:       8000000 kB
MemFree:         1000000 kB
MemAvailable:    2000000 kB
Buffers:          100000 kB
"""


def test_parse_loadavg() -> None:
    assert parse_loadavg("0.42 0.50 0.55 1/234 5678") == 0.42


def test_parse_mem_used_percent() -> None:
    # used = total - available = 8_000_000 - 2_000_000 = 6_000_000 → 75%
    assert parse_mem_used_percent(_MEMINFO) == 75.0


def test_parse_mem_used_percent_handles_empty() -> None:
    assert parse_mem_used_percent("") == 0.0


def test_disk_used_percent_in_range() -> None:
    pct = disk_used_percent("/")
    assert 0.0 <= pct <= 100.0


def test_collect_returns_samples() -> None:
    samples = collect()
    assert all(isinstance(s, Sample) for s in samples)
    assert any(s.key == "system.load1" for s in samples)


def test_run_requires_token() -> None:
    result = runner.invoke(
        app, ["agent", "run", "--host", "web-01"], env={"GHOSTMON_INGEST_TOKEN": ""}
    )
    assert result.exit_code == 2


def test_push_round_posts_each_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cli.commands import agent

    monkeypatch.setattr(
        agent,
        "collect",
        lambda: [Sample("system.load1", 0.5), Sample("system.mem.used_pct", 75.0, "%")],
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    agent._push_round(client, "http://x/api/ingest", "gmi_token", "web-01")

    assert len(seen) == 2
    body = json.loads(seen[0].content)
    assert body == {"host": "web-01", "key": "system.load1", "value": 0.5, "units": None}
    assert seen[0].headers["X-Ingest-Token"] == "gmi_token"
