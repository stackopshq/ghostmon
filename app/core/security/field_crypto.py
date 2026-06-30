"""Authenticated encryption for sensitive fields at rest.

Monitoring secrets (webhook signing secrets, SNMP communities) are stored
encrypted so a database dump leaks nothing usable — a privacy guarantee Zabbix
does not give. The key is derived from APP_SECRET_KEY via HKDF, so no extra
secret to manage; rotating APP_SECRET_KEY rotates this key (re-enter secrets).
"""

from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

_PREFIX = "enc:v1:"

# Placeholder returned by read schemas in place of an encrypted secret. If it is
# submitted back on update, services treat it as "keep the existing value".
REDACTED = "__redacted__"


@lru_cache
def _fernet() -> Fernet:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"ghostmon.field-crypto.v1",
        info=b"ghostmon-field-secrets",
    ).derive(get_settings().app_secret_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def is_encrypted(value: str) -> bool:
    return value.startswith(_PREFIX)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret; idempotent (already-encrypted values pass through)."""
    if is_encrypted(plaintext):
        return plaintext
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt_secret(value: str) -> str:
    """Decrypt a value produced by `encrypt_secret`. Plaintext (un-prefixed) and
    undecryptable values are returned unchanged, so a key change degrades to
    'secret no longer works' rather than a crash."""
    if not is_encrypted(value):
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX) :].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return value
