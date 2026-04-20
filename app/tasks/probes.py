from __future__ import annotations

import asyncio
import re
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from app.core.models.monitor import Monitor, MonitorType
from app.core.models.monitor_result import ProbeStatus

DEFAULT_TIMEOUT_SECONDS = 10.0
SSL_EXPIRY_WARNING_DAYS = 14
_PING_TIME_RE = re.compile(r"time[=<]([\d.]+)\s*ms", re.IGNORECASE)


@dataclass(slots=True)
class ProbeOutcome:
    status: ProbeStatus
    latency_ms: int | None
    error: str | None


async def run_probe(monitor: Monitor) -> ProbeOutcome:
    match monitor.type:
        case MonitorType.HTTP:
            return await _probe_http(monitor.url)
        case MonitorType.TCP:
            return await _probe_tcp(monitor.url)
        case MonitorType.SSL:
            return await _probe_ssl(monitor.url)
        case MonitorType.PING:
            return await _probe_ping(monitor.url)
        case _:
            return ProbeOutcome(
                status=ProbeStatus.DOWN,
                latency_ms=None,
                error=f"Probe type '{monitor.type.value}' not implemented",
            )


async def _probe_http(url: str) -> ProbeOutcome:
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "GhostMonitor/0.1"},
        ) as client:
            response = await client.get(url)
    except httpx.TimeoutException:
        return ProbeOutcome(ProbeStatus.DOWN, None, "timeout")
    except httpx.HTTPError as exc:
        return ProbeOutcome(ProbeStatus.DOWN, None, f"http error: {exc}")

    latency_ms = int((time.perf_counter() - start) * 1000)
    if 200 <= response.status_code < 400:
        return ProbeOutcome(ProbeStatus.UP, latency_ms, None)
    return ProbeOutcome(
        ProbeStatus.DOWN,
        latency_ms,
        f"HTTP {response.status_code}",
    )


async def _probe_tcp(url: str) -> ProbeOutcome:
    host, port = _parse_tcp_target(url)
    if host is None or port is None:
        return ProbeOutcome(
            ProbeStatus.DOWN,
            None,
            f"invalid tcp target: {url!r} (expected host:port or tcp://host:port)",
        )
    start = time.perf_counter()
    try:
        async with asyncio.timeout(DEFAULT_TIMEOUT_SECONDS):
            reader, writer = await asyncio.open_connection(host, port)
    except TimeoutError:
        return ProbeOutcome(ProbeStatus.DOWN, None, "timeout")
    except OSError as exc:
        return ProbeOutcome(ProbeStatus.DOWN, None, f"connect error: {exc}")

    latency_ms = int((time.perf_counter() - start) * 1000)
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return ProbeOutcome(ProbeStatus.UP, latency_ms, None)


async def _probe_ssl(url: str) -> ProbeOutcome:
    host, port = _parse_ssl_target(url)
    if host is None:
        return ProbeOutcome(
            ProbeStatus.DOWN,
            None,
            f"invalid ssl target: {url!r} (expected host, host:port or https://host[:port])",
        )
    context = ssl.create_default_context()
    start = time.perf_counter()
    try:
        async with asyncio.timeout(DEFAULT_TIMEOUT_SECONDS):
            reader, writer = await asyncio.open_connection(
                host, port, ssl=context, server_hostname=host
            )
    except TimeoutError:
        return ProbeOutcome(ProbeStatus.DOWN, None, "timeout")
    except ssl.SSLError as exc:
        return ProbeOutcome(ProbeStatus.DOWN, None, f"tls error: {exc}")
    except OSError as exc:
        return ProbeOutcome(ProbeStatus.DOWN, None, f"connect error: {exc}")

    latency_ms = int((time.perf_counter() - start) * 1000)
    cert = writer.get_extra_info("peercert")
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass

    if not cert:
        return ProbeOutcome(ProbeStatus.DOWN, latency_ms, "peer did not present a certificate")
    not_after = cert.get("notAfter")
    if not not_after:
        return ProbeOutcome(ProbeStatus.DOWN, latency_ms, "certificate is missing notAfter")
    try:
        expiry = _parse_cert_time(not_after)
    except ValueError:
        return ProbeOutcome(ProbeStatus.DOWN, latency_ms, f"unparseable notAfter: {not_after!r}")

    now = datetime.now(UTC)
    delta_days = int((expiry - now).total_seconds() // 86400)
    if delta_days < 0:
        return ProbeOutcome(
            ProbeStatus.DOWN,
            latency_ms,
            f"certificate expired {-delta_days} day(s) ago",
        )
    warning = (
        f"certificate expires in {delta_days} day(s)"
        if delta_days <= SSL_EXPIRY_WARNING_DAYS
        else None
    )
    return ProbeOutcome(ProbeStatus.UP, latency_ms, warning)


async def _probe_ping(url: str) -> ProbeOutcome:
    target = _parse_ping_target(url)
    if not target:
        return ProbeOutcome(ProbeStatus.DOWN, None, f"invalid ping target: {url!r}")

    try:
        proc = await asyncio.create_subprocess_exec(
            "ping",
            "-c",
            "1",
            "-W",
            str(int(DEFAULT_TIMEOUT_SECONDS)),
            target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return ProbeOutcome(ProbeStatus.DOWN, None, "ping binary not found")

    try:
        async with asyncio.timeout(DEFAULT_TIMEOUT_SECONDS + 2):
            stdout, stderr = await proc.communicate()
    except TimeoutError:
        proc.kill()
        return ProbeOutcome(ProbeStatus.DOWN, None, "timeout")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        return ProbeOutcome(
            ProbeStatus.DOWN,
            None,
            err or f"ping exited with code {proc.returncode}",
        )

    latency_ms = _parse_ping_time(stdout.decode("utf-8", errors="replace"))
    return ProbeOutcome(ProbeStatus.UP, latency_ms, None)


def _parse_tcp_target(raw: str) -> tuple[str | None, int | None]:
    candidate = raw.strip()
    if "://" in candidate:
        parsed = urlparse(candidate)
        host = parsed.hostname
        port = parsed.port
        return host, port
    if ":" not in candidate:
        return None, None
    host, _, port_str = candidate.rpartition(":")
    if not host or not port_str.isdigit():
        return None, None
    return host, int(port_str)


def _parse_ssl_target(raw: str) -> tuple[str | None, int]:
    candidate = raw.strip()
    if "://" in candidate:
        parsed = urlparse(candidate)
        return parsed.hostname, parsed.port or 443
    if ":" in candidate:
        host, _, port_str = candidate.rpartition(":")
        if host and port_str.isdigit():
            return host, int(port_str)
        return None, 443
    return (candidate or None), 443


def _parse_ping_target(raw: str) -> str | None:
    candidate = raw.strip()
    if not candidate:
        return None
    if "://" in candidate:
        parsed = urlparse(candidate)
        return parsed.hostname
    # Strip trailing :port if present (ping doesn't accept ports).
    if ":" in candidate and candidate.rpartition(":")[2].isdigit():
        return candidate.rpartition(":")[0] or None
    return candidate


def _parse_cert_time(raw: str) -> datetime:
    # OpenSSL format, e.g. "Apr  5 12:00:00 2027 GMT"
    return datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)


def _parse_ping_time(output: str) -> int | None:
    match = _PING_TIME_RE.search(output)
    if match is None:
        return None
    try:
        return int(round(float(match.group(1))))
    except ValueError:
        return None
