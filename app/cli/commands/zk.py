from __future__ import annotations

from typing import Annotated

import typer

from app.core.security.zk import decrypt, encrypt, generate_key

app = typer.Typer(
    help="Zero-knowledge crypto for private items (the key never reaches the server).",
    no_args_is_help=True,
)

_KEY = Annotated[str, typer.Option("--key", "-k", envvar="GHOSTMON_ZK_KEY", help="base64url key.")]


@app.command("genkey")
def genkey() -> None:
    """Generate a private-item key. Keep it secret — the server never sees it."""
    typer.echo(generate_key())


@app.command("encrypt")
def encrypt_cmd(
    value: Annotated[str, typer.Argument(help="Plaintext to encrypt.")], key: _KEY
) -> None:
    """Encrypt a value into a token to push to a private item's /api/ingest."""
    typer.echo(encrypt(key, value))


@app.command("decrypt")
def decrypt_cmd(
    token: Annotated[str, typer.Argument(help="Token from history.")], key: _KEY
) -> None:
    """Decrypt a token read back from a private item's history."""
    typer.echo(decrypt(key, token))
