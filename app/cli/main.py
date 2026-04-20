import typer

from app import __version__
from app.cli.commands import monitor as monitor_cmd

app = typer.Typer(
    name="ghostmon",
    help="GhostMonitor CLI — self-hosted monitoring.",
    no_args_is_help=True,
    add_completion=True,
)

app.add_typer(monitor_cmd.app, name="monitor")


@app.command("version")
def version() -> None:
    """Print the installed GhostMonitor version."""
    typer.echo(f"ghostmon {__version__}")


if __name__ == "__main__":
    app()
