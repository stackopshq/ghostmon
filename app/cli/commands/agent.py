from __future__ import annotations

import time
from typing import Annotated

import httpx
import typer
from rich.console import Console

from app.agent.metrics import Sample, collect

app = typer.Typer(help="Reference metric-collection agent.", no_args_is_help=True)
console = Console()


def _push_round(client: httpx.Client, endpoint: str, token: str, host: str) -> None:
    for sample in collect():
        try:
            response = client.post(
                endpoint,
                headers={"X-Ingest-Token": token},
                json={
                    "host": host,
                    "key": sample.key,
                    "value": sample.value,
                    "units": sample.units,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            console.print(f"[yellow]push failed[/yellow] {sample.key}: {exc}")
        else:
            console.print(f"[green]→[/green] {sample.key} = {_fmt(sample)}")


def _fmt(sample: Sample) -> str:
    return f"{sample.value}{' ' + sample.units if sample.units else ''}"


@app.command("run")
def run(
    host: Annotated[str, typer.Option("--host", help="Target host name in GhostMonitor.")],
    url: Annotated[str, typer.Option("--url", envvar="GHOSTMON_URL")] = "http://localhost:8000",
    token: Annotated[
        str,
        typer.Option("--token", envvar="GHOSTMON_INGEST_TOKEN", help="Ingest token (gmi_…)."),
    ] = "",
    interval: Annotated[int, typer.Option("--interval", min=1)] = 30,
    once: Annotated[
        bool, typer.Option("--once", help="Collect and push a single round, then exit.")
    ] = False,
) -> None:
    """Collect system metrics (load, memory, disk) and push them to /api/ingest.

    The target `host` must already exist in GhostMonitor; items are auto-created
    on first push. Provide the token via --token or the GHOSTMON_INGEST_TOKEN env.
    """
    if not token:
        console.print("[red]No ingest token[/red] — set --token or GHOSTMON_INGEST_TOKEN.")
        raise typer.Exit(code=2)
    endpoint = f"{url.rstrip('/')}/api/ingest"
    with httpx.Client(timeout=10) as client:
        while True:
            _push_round(client, endpoint, token, host)
            if once:
                break
            time.sleep(interval)
