"""Zero-knowledge crypto for private items.

The wire format is interoperable with the browser's Web Crypto API so values can
be encrypted client-side (browser/agent), stored as opaque ciphertext the server
can never read, and decrypted only by whoever holds the key.

Two modes, both AES-256-GCM (matching the ghost-suite / ghostbit model):

- Random key: ``token = base64url(nonce[12] || ct || tag[16])``; the key
  (base64url of 32 bytes) lives in the URL fragment, never sent to the server.
- Passphrase: ``token = "a2." + base64url(salt[16]) + "." + base64url(nonce||ct)``;
  the AES key is derived from a passphrase via **Argon2id** with the same
  parameters ghostbit uses, so the server never sees the passphrase or the key.

The server NEVER sees the key or passphrase; these helpers exist for the reference
CLI and tests. The server stores and returns the token verbatim.
"""

from __future__ import annotations

import base64
import os

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12
_SALT_LEN = 16
_PASSPHRASE_PREFIX = "a2"

# Argon2id parameters — MUST match ghostbit's e2e.js / CLI so a token encrypted by
# one decrypts in the other. (parallelism 1, iterations 2, memory 19456 KiB, 32-byte key.)
_ARGON2_TIME_COST = 2
_ARGON2_MEMORY_KIB = 19_456
_ARGON2_PARALLELISM = 1
_ARGON2_HASH_LEN = 32


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def generate_key() -> str:
    """A fresh 256-bit key as an unpadded base64url string."""
    return _b64url_encode(os.urandom(32))


def encrypt(key_b64: str, plaintext: str) -> str:
    key = _b64url_decode(key_b64)
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _b64url_encode(nonce + ciphertext)


def decrypt(key_b64: str, token: str) -> str:
    key = _b64url_decode(key_b64)
    raw = _b64url_decode(token)
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")


def _derive_argon2id(passphrase: str, salt: bytes) -> bytes:
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=_ARGON2_TIME_COST,
        memory_cost=_ARGON2_MEMORY_KIB,
        parallelism=_ARGON2_PARALLELISM,
        hash_len=_ARGON2_HASH_LEN,
        type=Type.ID,
    )


def is_passphrase_token(token: str) -> bool:
    return token.startswith(_PASSPHRASE_PREFIX + ".")


def encrypt_with_passphrase(passphrase: str, plaintext: str) -> str:
    salt = os.urandom(_SALT_LEN)
    key = _derive_argon2id(passphrase, salt)
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return f"{_PASSPHRASE_PREFIX}.{_b64url_encode(salt)}.{_b64url_encode(nonce + ciphertext)}"


def decrypt_with_passphrase(passphrase: str, token: str) -> str:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _PASSPHRASE_PREFIX:
        raise ValueError("not an argon2id passphrase token")
    salt = _b64url_decode(parts[1])
    raw = _b64url_decode(parts[2])
    key = _derive_argon2id(passphrase, salt)
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
