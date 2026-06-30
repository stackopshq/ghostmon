"""Zero-knowledge crypto for private items.

The wire format is interoperable with the browser's Web Crypto API so values can
be encrypted client-side (browser/agent), stored as opaque ciphertext the server
can never read, and decrypted only by whoever holds the key.

Format: AES-256-GCM. Token = base64url(nonce[12] || ciphertext || tag[16]).
Key = base64url(32 random bytes). Both base64url are unpadded.

The server NEVER sees the key; these helpers exist for the reference CLI and for
tests. The server stores and returns the token verbatim.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12


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
