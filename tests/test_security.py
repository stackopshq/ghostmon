"""Security headers: a strict CSP (with wasm-unsafe-eval + a per-request nonce)."""

from __future__ import annotations

import re

import httpx


async def test_csp_and_security_headers_on_a_page(web_client: httpx.AsyncClient) -> None:
    resp = await web_client.get("/login")
    assert resp.status_code == 200

    csp = resp.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "'wasm-unsafe-eval'" in csp  # lets the Argon2 wasm run for ZK passphrase mode
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp

    # The nonce in the header admits exactly the inline theme script in the page.
    match = re.search(r"'nonce-([^']+)'", csp)
    assert match is not None
    assert f'nonce="{match.group(1)}"' in resp.text

    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "geolocation=()" in resp.headers["permissions-policy"]


async def test_csp_nonce_is_per_request(web_client: httpx.AsyncClient) -> None:
    a = (await web_client.get("/login")).headers["content-security-policy"]
    b = (await web_client.get("/login")).headers["content-security-policy"]
    assert a != b  # a fresh nonce each request


async def test_docs_are_exempt_from_csp(web_client: httpx.AsyncClient) -> None:
    resp = await web_client.get("/docs")
    assert resp.status_code == 200
    # Swagger UI needs inline scripts/CDN; the app CSP must not be imposed on it.
    assert "content-security-policy" not in resp.headers
    # …but the cheap hardening headers still apply.
    assert resp.headers["x-content-type-options"] == "nosniff"
