from __future__ import annotations

import asyncio
import re
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from pysnmp.hlapi.v3arch.asyncio import (  # type: ignore[import-untyped]
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

from app.core.config import get_settings
from app.core.models.monitor import Monitor, MonitorType
from app.core.models.monitor_result import ProbeStatus
from app.core.security.ssrf import BlockedTargetError, assert_target_allowed

DEFAULT_TIMEOUT_SECONDS = 10.0


async def _egress_guard(host: str | None) -> ProbeOutcome | None:
    """`None` if the target is allowed, else a DOWN outcome (egress policy)."""
    try:
        await assert_target_allowed(host or "")
    except BlockedTargetError:
        return ProbeOutcome(ProbeStatus.DOWN, None, "target blocked by egress policy")
    return None


SSL_EXPIRY_WARNING_DAYS = 14
DEFAULT_SNMP_COMMUNITY = "public"
DEFAULT_SNMP_OID = "1.3.6.1.2.1.1.3.0"  # sysUpTime
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
        case MonitorType.SNMP:
            return await _probe_snmp(monitor.url)
        case _:
            return ProbeOutcome(
                status=ProbeStatus.DOWN,
                latency_ms=None,
                error=f"Probe type '{monitor.type.value}' not implemented",
            )


async def _probe_http(url: str) -> ProbeOutcome:
    if (blocked := await _egress_guard(httpx.URL(url).host)) is not None:
        return blocked
    # When the egress guard is on, don't auto-follow redirects either — a 30x could
    # otherwise bounce the request to an internal address the guard just rejected.
    follow_redirects = not get_settings().ssrf_block_private
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=follow_redirects,
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
    if (blocked := await _egress_guard(host)) is not None:
        return blocked
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
    if (blocked := await _egress_guard(host)) is not None:
        return blocked
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
    if (blocked := await _egress_guard(target)) is not None:
        return blocked

    try:
        proc = await asyncio.create_subprocess_exec(
            "ping",
            "-c",
            "1",
            "-W",
            str(int(DEFAULT_TIMEOUT_SECONDS)),
            "--",  # end of options: a target starting with '-' can't be read as a flag
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


class SnmpError(Exception):
    pass


async def _snmp_get(host: str, port: int, community: str, oid: str) -> str:
    """One-shot SNMPv2c GET. Returns the value's string form; raises on failure.
    Isolated so the probe orchestration around it stays unit-testable."""
    target = await UdpTransportTarget.create(
        (host, port), timeout=DEFAULT_TIMEOUT_SECONDS, retries=0
    )
    error_indication, error_status, error_index, var_binds = await get_cmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),
        target,
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    if error_indication:
        raise SnmpError(str(error_indication))
    if error_status:
        raise SnmpError(f"{error_status.prettyPrint()} at {error_index or '?'}")
    return str(var_binds[0][1].prettyPrint())


async def _probe_snmp(url: str) -> ProbeOutcome:
    target = _parse_snmp_target(url)
    if target is None:
        return ProbeOutcome(
            ProbeStatus.DOWN,
            None,
            f"invalid snmp target: {url!r} (expected snmp://[community@]host[:port]/OID)",
        )
    host, port, community, oid = target
    if (blocked := await _egress_guard(host)) is not None:
        return blocked
    start = time.perf_counter()
    try:
        async with asyncio.timeout(DEFAULT_TIMEOUT_SECONDS + 2):
            await _snmp_get(host, port, community, oid)
    except (SnmpError, OSError, TimeoutError) as exc:
        return ProbeOutcome(ProbeStatus.DOWN, None, f"snmp error: {exc}")
    latency_ms = int((time.perf_counter() - start) * 1000)
    return ProbeOutcome(ProbeStatus.UP, latency_ms, None)


def _parse_snmp_target(raw: str) -> tuple[str, int, str, str] | None:
    """Parse `snmp://[community@]host[:port]/OID` (community/port/OID optional)."""
    candidate = raw.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"snmp://{candidate}"
    parsed = urlparse(candidate)
    if parsed.hostname is None:
        return None
    oid = parsed.path.lstrip("/") or DEFAULT_SNMP_OID
    return parsed.hostname, parsed.port or 161, parsed.username or DEFAULT_SNMP_COMMUNITY, oid


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
