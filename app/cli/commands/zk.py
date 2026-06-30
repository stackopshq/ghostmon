from __future__ import annotations

from typing import Annotated

import typer

from app.core.security.zk import (
    decrypt,
    decrypt_with_passphrase,
    encrypt,
    encrypt_with_passphrase,
    generate_key,
    is_passphrase_token,
)

app = typer.Typer(
    help="Zero-knowledge crypto for private items (the key never reaches the server).",
    no_args_is_help=True,
)

_KEY = Annotated[
    str | None, typer.Option("--key", "-k", envvar="GHOSTMON_ZK_KEY", help="base64url random key.")
]
_PASSPHRASE = Annotated[
    str | None,
    typer.Option("--password", "-p", envvar="GHOSTMON_ZK_PASSPHRASE", help="Argon2id passphrase."),
]


def _require_one(key: str | None, passphrase: str | None) -> None:
    if bool(key) == bool(passphrase):
        raise typer.BadParameter("provide exactly one of --key or --password")


@app.command("genkey")
def genkey() -> None:
    """Generate a random private-item key. Keep it secret — the server never sees it."""
    typer.echo(generate_key())


@app.command("encrypt")
def encrypt_cmd(
    value: Annotated[str, typer.Argument(help="Plaintext to encrypt.")],
    key: _KEY = None,
    passphrase: _PASSPHRASE = None,
) -> None:
    """Encrypt a value into a token to push to a private item's /api/ingest.

    Use --key (random key, shared via the URL fragment) or --password (Argon2id).
    """
    _require_one(key, passphrase)
    if passphrase:
        typer.echo(encrypt_with_passphrase(passphrase, value))
    else:
        typer.echo(encrypt(key or "", value))


@app.command("decrypt")
def decrypt_cmd(
    token: Annotated[str, typer.Argument(help="Token from history.")],
    key: _KEY = None,
    passphrase: _PASSPHRASE = None,
) -> None:
    """Decrypt a token read back from a private item's history."""
    _require_one(key, passphrase)
    if passphrase or is_passphrase_token(token):
        if not passphrase:
            raise typer.BadParameter("this token needs --password")
        typer.echo(decrypt_with_passphrase(passphrase, token))
    else:
        typer.echo(decrypt(key or "", token))
