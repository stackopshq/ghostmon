import asyncio
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from app.core.db.session import get_session_context
from app.core.models.user import User
from app.core.schemas.user import UserCreate
from app.core.services.user_service import UserService

app = typer.Typer(help="Manage users.", no_args_is_help=True)
console = Console()


async def _create(email: str, password: str, full_name: str | None, superuser: bool) -> int:
    try:
        payload = UserCreate(email=email, password=password, full_name=full_name)
    except ValidationError as exc:
        console.print(f"[red]Invalid input:[/red] {exc.errors()[0]['msg']}")
        return 2

    async with get_session_context() as session:
        service = UserService(session)
        existing = await service.get_by_email(payload.email)
        if existing is not None:
            console.print(f"[red]User already exists:[/red] {payload.email}")
            return 1
        user = await service.create_local(payload)
        if superuser:
            user.is_superuser = True
            await session.commit()
            await session.refresh(user)

    console.print(f"[green]Created user[/green] {user.email} ([dim]{user.id}[/dim])")
    if user.is_superuser:
        console.print("[yellow]superuser=true[/yellow]")
    return 0


async def _list() -> int:
    async with get_session_context() as session:
        stmt = select(User).order_by(User.created_at.desc())
        result = await session.execute(stmt)
        users = list(result.scalars().all())

    if not users:
        console.print("[yellow]No users found.[/yellow]")
        return 0

    table = Table(title="GhostMonitor — Users", show_lines=False)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Email")
    table.add_column("Full name")
    table.add_column("Provider")
    table.add_column("Active", justify="center")
    table.add_column("Super", justify="center")

    for u in users:
        table.add_row(
            str(u.id),
            u.email,
            u.full_name or "-",
            u.auth_provider.value,
            "yes" if u.is_active else "no",
            "yes" if u.is_superuser else "no",
        )
    console.print(table)
    return 0


@app.command("create")
def create_user(
    email: Annotated[str, typer.Option("--email", "-e", prompt=True)],
    full_name: Annotated[
        str | None,
        typer.Option("--full-name", "-n", help="Display name (optional)."),
    ] = None,
    superuser: Annotated[
        bool,
        typer.Option("--superuser", "-s", help="Grant superuser privileges."),
    ] = False,
    password: Annotated[
        str,
        typer.Option(
            "--password",
            prompt=True,
            hide_input=True,
            confirmation_prompt=True,
            help="Password (min 12 chars). Prompted if not provided.",
        ),
    ] = "",
) -> None:
    """Create a local (password-authenticated) user."""
    code = asyncio.run(_create(email, password, full_name, superuser))
    raise typer.Exit(code=code)


@app.command("list")
def list_users() -> None:
    """List all users."""
    code = asyncio.run(_list())
    raise typer.Exit(code=code)
