"""Optional SSRF egress guard.

A monitoring tool legitimately reaches internal hosts, so this is OFF by default
(`SSRF_BLOCK_PRIVATE=false`). Turn it on for multi-tenant deployments to stop an
authenticated user pointing a probe or webhook at loopback, RFC1918, link-local
(incl. the cloud metadata endpoint 169.254.169.254) or other reserved ranges.

DNS is resolved so a hostname that maps to an internal IP is caught too.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

from app.core.config import get_settings


class BlockedTargetError(Exception):
    """Raised when egress policy forbids reaching a target host."""


def _is_internal_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def host_is_blocked(host: str) -> bool:
    """True if `host` is (or resolves to) an internal/reserved address."""
    try:
        return _is_internal_ip(ipaddress.ip_address(host))  # literal IP
    except ValueError:
        pass
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except (OSError, UnicodeError):
        return False  # can't resolve → the connection will simply fail on its own
    for info in infos:
        try:
            if _is_internal_ip(ipaddress.ip_address(info[4][0])):
                return True
        except ValueError:
            continue
    return False


async def assert_target_allowed(host: str) -> None:
    """Raise `BlockedTargetError` when the egress guard is enabled and `host` is
    internal. A no-op when the guard is disabled (the default)."""
    if not host:
        return
    if get_settings().ssrf_block_private and await host_is_blocked(host):
        raise BlockedTargetError(host)
