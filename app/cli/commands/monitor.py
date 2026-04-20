import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from app.core.db.session import get_session_context
from app.core.services.monitor_service import MonitorService
from app.core.services.user_service import UserService

app = typer.Typer(help="Manage monitors.", no_args_is_help=True)
console = Console()


async def _list(owner_email: str | None) -> int:
    async with get_session_context() as session:
        if owner_email is None:
            from sqlalchemy import select

            from app.core.models.monitor import Monitor

            stmt = select(Monitor).order_by(Monitor.created_at.desc())
            result = await session.execute(stmt)
            monitors = list(result.scalars().all())
        else:
            user = await UserService(session).get_by_email(owner_email)
            if user is None:
                console.print(f"[red]User not found:[/red] {owner_email}")
                return 1
            monitors = list(await MonitorService(session).list_for_owner(user.id))

    table = Table(title="GhostMonitor — Monitors", show_lines=False)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("URL")
    table.add_column("Interval", justify="right")
    table.add_column("Status")

    for m in monitors:
        table.add_row(
            str(m.id),
            m.name,
            m.type.value,
            m.url,
            f"{m.interval}s",
            m.status.value,
        )

    if not monitors:
        console.print("[yellow]No monitors found.[/yellow]")
    else:
        console.print(table)
    return 0


@app.command("list")
def list_monitors(
    owner: Annotated[
        str | None,
        typer.Option(
            "--owner",
            "-o",
            help="Filter by owner email. Omit for all monitors (admin view).",
        ),
    ] = None,
) -> None:
    """List monitors."""
    code = asyncio.run(_list(owner))
    raise typer.Exit(code=code)
