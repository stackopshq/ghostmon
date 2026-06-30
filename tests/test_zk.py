"""Zero-knowledge private items: crypto interop, opaque server storage, and CLI."""

from __future__ import annotations

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from typer.testing import CliRunner

from app.cli.main import app
from app.core.security.zk import (
    _derive_argon2id,
    decrypt,
    decrypt_with_passphrase,
    encrypt,
    encrypt_with_passphrase,
    generate_key,
    is_passphrase_token,
)

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


# ── Passphrase mode (Argon2id, ghostbit-aligned) ────────────────────────────


def test_argon2id_reference_vector() -> None:
    # Locks the Argon2id parameters so they never drift from ghostbit's e2e.js /
    # hash-wasm — a drift would silently break cross-tool decryption.
    key = _derive_argon2id("hunter2", b"0123456789abcdef")
    assert key.hex() == "9d4c62adf54ad88fef393e9fda5cb6c12823c19d68ab04cb0a6adca43ca389c0"


def test_passphrase_roundtrip_and_wrong_password() -> None:
    token = encrypt_with_passphrase("correct horse", "secret reading")
    assert is_passphrase_token(token)
    assert token.startswith("a2.")
    assert len(token.split(".")) == 3
    assert decrypt_with_passphrase("correct horse", token) == "secret reading"
    with pytest.raises(InvalidTag):
        decrypt_with_passphrase("wrong password", token)


def test_zk_cli_passphrase_roundtrip() -> None:
    enc = runner.invoke(app, ["zk", "encrypt", "--password", "pw123", "topsecret"])
    assert enc.exit_code == 0, enc.output
    token = enc.output.strip()
    assert token.startswith("a2.")

    dec = runner.invoke(app, ["zk", "decrypt", "--password", "pw123", token])
    assert dec.exit_code == 0
    assert dec.output.strip() == "topsecret"


def test_zk_cli_requires_exactly_one_mode() -> None:
    # Neither key nor password.
    none = runner.invoke(app, ["zk", "encrypt", "x"])
    assert none.exit_code != 0
    # Both at once.
    both = runner.invoke(app, ["zk", "encrypt", "--key", generate_key(), "--password", "p", "x"])
    assert both.exit_code != 0
