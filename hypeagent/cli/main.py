"""Typer CLI root application."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hypeagent import __version__
from hypeagent.cli.validate import run_validate

app = typer.Typer(
    name="hypeagent",
    help="LLM-powered persona agents for social platform seeding.",
    no_args_is_help=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to hypeagent.yaml"),
    ] = Path("hypeagent.yaml"),
    secrets: Annotated[
        Path,
        typer.Option("--secrets", "-s", help="Path to secrets.local.yaml"),
    ] = Path("secrets.local.yaml"),
    db: Annotated[
        Path | None,
        typer.Option("--db", help="Path to SQLite database"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging"),
    ] = False,
) -> None:
    """Global options are stored on context for subcommands."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = config
    ctx.obj["secrets"] = secrets
    ctx.obj["db"] = db
    ctx.obj["verbose"] = verbose


@app.command("version")
def version_cmd() -> None:
    """Print package version."""
    typer.echo(__version__)


@app.command("validate")
def validate_cmd(ctx: typer.Context) -> None:
    """Parse config and secrets; validate schema and account references."""
    ctx_obj = ctx.obj or {}
    config_path = ctx_obj.get("config", Path("hypeagent.yaml"))
    secrets_path = ctx_obj.get("secrets", Path("secrets.local.yaml"))
    run_validate(config_path, secrets_path)
