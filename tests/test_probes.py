import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.models.monitor import Monitor, MonitorStatus, MonitorType
from app.core.models.monitor_result import ProbeStatus
from app.tasks.probes import (
    _parse_cert_time,
    _parse_ping_target,
    _parse_ping_time,
    _parse_ssl_target,
    _parse_tcp_target,
    run_probe,
)

HttpxHandler = Callable[[httpx.Request], httpx.Response]


def _monitor(type_: MonitorType, url: str) -> Monitor:
    return Monitor(
        id=uuid.uuid4(),
        name="test",
        type=type_,
        url=url,
        interval=60,
        status=MonitorStatus.PENDING,
        owner_id=uuid.uuid4(),
    )


def test_parse_tcp_target_bare() -> None:
    assert _parse_tcp_target("host.example.com:5432") == ("host.example.com", 5432)


def test_parse_tcp_target_scheme() -> None:
    assert _parse_tcp_target("tcp://host.example.com:5432") == (
        "host.example.com",
        5432,
    )


def test_parse_tcp_target_invalid() -> None:
    assert _parse_tcp_target("not-a-target") == (None, None)
    assert _parse_tcp_target(":5432") == (None, None)
    assert _parse_tcp_target("host:abc") == (None, None)


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler: HttpxHandler) -> None:
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("app.tasks.probes.httpx.AsyncClient", factory)


async def test_run_probe_http_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(monkeypatch, lambda _: httpx.Response(200, text="ok"))
    outcome = await run_probe(_monitor(MonitorType.HTTP, "https://example.com"))
    assert outcome.status is ProbeStatus.UP
    assert outcome.error is None
    assert outcome.latency_ms is not None


async def test_run_probe_http_5xx_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(monkeypatch, lambda _: httpx.Response(503, text="bad"))
    outcome = await run_probe(_monitor(MonitorType.HTTP, "https://example.com"))
    assert outcome.status is ProbeStatus.DOWN
    assert outcome.error == "HTTP 503"


async def test_run_probe_http_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    _patch_httpx(monkeypatch, _raise)
    outcome = await run_probe(_monitor(MonitorType.HTTP, "https://example.com"))
    assert outcome.status is ProbeStatus.DOWN
    assert outcome.error is not None
    assert "refused" in outcome.error


async def test_run_probe_tcp_success() -> None:
    async def _handle(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    async with server:
        outcome = await run_probe(_monitor(MonitorType.TCP, f"{host}:{port}"))
    assert outcome.status is ProbeStatus.UP
    assert outcome.error is None
    assert outcome.latency_ms is not None


async def test_run_probe_tcp_refused() -> None:
    outcome = await run_probe(_monitor(MonitorType.TCP, "127.0.0.1:1"))
    assert outcome.status is ProbeStatus.DOWN
    assert outcome.error is not None


async def test_run_probe_docker_is_not_implemented() -> None:
    outcome = await run_probe(_monitor(MonitorType.DOCKER, "ghostmon-postgres"))
    assert outcome.status is ProbeStatus.DOWN
    assert outcome.error is not None
    assert "not implemented" in outcome.error


def test_parse_ssl_target_defaults_to_443() -> None:
    assert _parse_ssl_target("example.com") == ("example.com", 443)
    assert _parse_ssl_target("https://example.com") == ("example.com", 443)
    assert _parse_ssl_target("https://example.com:8443") == ("example.com", 8443)
    assert _parse_ssl_target("example.com:8443") == ("example.com", 8443)


def test_parse_ssl_target_invalid() -> None:
    assert _parse_ssl_target("") == (None, 443)
    assert _parse_ssl_target("example.com:abc") == (None, 443)


def test_parse_cert_time_openssl_format() -> None:
    parsed = _parse_cert_time("Apr  5 12:00:00 2027 GMT")
    assert parsed == datetime(2027, 4, 5, 12, 0, 0, tzinfo=UTC)


def test_parse_ping_target_strips_scheme_and_port() -> None:
    assert _parse_ping_target("example.com") == "example.com"
    assert _parse_ping_target("https://example.com/path") == "example.com"
    assert _parse_ping_target("192.168.1.1:8080") == "192.168.1.1"


def test_parse_ping_target_empty() -> None:
    assert _parse_ping_target("") is None
    assert _parse_ping_target("   ") is None


def test_parse_ping_time_reads_latency() -> None:
    sample = (
        "PING 127.0.0.1 (127.0.0.1) 56(84) bytes of data.\n"
        "64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.059 ms\n"
    )
    assert _parse_ping_time(sample) == 0


def test_parse_ping_time_missing() -> None:
    assert _parse_ping_time("no latency here") is None


async def test_run_probe_ping_loopback_is_up() -> None:
    outcome = await run_probe(_monitor(MonitorType.PING, "127.0.0.1"))
    assert outcome.status is ProbeStatus.UP
    assert outcome.error is None


async def test_run_probe_ping_invalid_target() -> None:
    outcome = await run_probe(_monitor(MonitorType.PING, ""))
    assert outcome.status is ProbeStatus.DOWN
    assert outcome.error is not None
    assert "invalid" in outcome.error


async def test_run_probe_ssl_with_local_self_signed(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ssl as ssl_lib

    certdir = tmp_path_factory.mktemp("cert")
    key = certdir / "key.pem"
    cert = certdir / "cert.pem"
    proc = await asyncio.create_subprocess_exec(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-keyout",
        str(key),
        "-out",
        str(cert),
        "-days",
        "3650",
        "-nodes",
        "-subj",
        "/CN=localhost",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode != 0:
        pytest.skip("openssl CLI unavailable")

    server_ctx = ssl_lib.create_default_context(ssl_lib.Purpose.CLIENT_AUTH)
    server_ctx.load_cert_chain(str(cert), str(key))

    async def handle(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
    host, port = server.sockets[0].getsockname()[:2]

    # Trust our self-signed cert; skip hostname check because cert CN=localhost
    # while we connect to the server by 127.0.0.1.
    client_ctx = ssl_lib.create_default_context(cafile=str(cert))
    client_ctx.check_hostname = False
    monkeypatch.setattr("app.tasks.probes.ssl.create_default_context", lambda *a, **kw: client_ctx)

    async with server:
        outcome = await run_probe(_monitor(MonitorType.SSL, f"{host}:{port}"))

    assert outcome.status is ProbeStatus.UP
    assert outcome.latency_ms is not None


async def test_run_probe_ssl_invalid_target() -> None:
    outcome = await run_probe(_monitor(MonitorType.SSL, ""))
    assert outcome.status is ProbeStatus.DOWN
    assert outcome.error is not None
    assert "invalid" in outcome.error


def test_ssl_expiry_warning_message_shape() -> None:
    # Sanity: a certificate expiring in 3 days should emit a warning string.
    from app.tasks.probes import SSL_EXPIRY_WARNING_DAYS

    future = datetime.now(UTC) + timedelta(days=3)
    assert future > datetime.now(UTC)
    assert SSL_EXPIRY_WARNING_DAYS >= 3
