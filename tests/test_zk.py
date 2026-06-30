"""Zero-knowledge private items: crypto interop, opaque server storage, and CLI."""

from __future__ import annotations

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from typer.testing import CliRunner

from app.cli.main import app
from app.core.security.zk import decrypt, encrypt, generate_key

runner = CliRunner()


def test_crypto_roundtrip_and_wrong_key() -> None:
    key = generate_key()
    token = encrypt(key, "cpu=42; very-private")
    assert token != "cpu=42; very-private"
    assert decrypt(key, token) == "cpu=42; very-private"
    # A different key cannot decrypt (AES-GCM auth tag fails).
    with pytest.raises(InvalidTag):
        decrypt(generate_key(), token)


def test_generate_key_is_unique_b64url() -> None:
    a, b = generate_key(), generate_key()
    assert a != b
    assert "=" not in a and "/" not in a and "+" not in a


async def test_server_stores_private_value_opaque(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    host = await client.post("/api/hosts", headers=auth_headers, json={"name": "vault"})
    host_id = host.json()["id"]
    created = await client.post(
        f"/api/hosts/{host_id}/items",
        headers=auth_headers,
        json={"key": "secret.metric", "name": "Secret", "value_type": "text", "is_private": True},
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_private"] is True
    item_id = created.json()["id"]

    # The client pushes ciphertext; the server stores it verbatim, never as a number.
    token = encrypt(generate_key(), "1234.5")
    pushed = await client.post(
        f"/api/hosts/{host_id}/items/{item_id}/values",
        headers=auth_headers,
        json={"value": token},
    )
    assert pushed.status_code == 201
    assert pushed.json()["value_text"] == token
    assert pushed.json()["value_num"] is None

    history = await client.get(f"/api/hosts/{host_id}/items/{item_id}/values", headers=auth_headers)
    assert [r["value_text"] for r in history.json()] == [token]


def test_zk_cli_roundtrip() -> None:
    key = runner.invoke(app, ["zk", "genkey"]).output.strip()
    assert key

    enc = runner.invoke(app, ["zk", "encrypt", "--key", key, "topsecret"])
    assert enc.exit_code == 0
    token = enc.output.strip()

    dec = runner.invoke(app, ["zk", "decrypt", "--key", key, token])
    assert dec.exit_code == 0
    assert dec.output.strip() == "topsecret"
