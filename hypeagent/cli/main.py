"""Typer CLI root application."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hypeagent import __version__
from hypeagent.cli.cron_print import run_cron_print
from hypeagent.cli.dry_run import run_dry_run
from hypeagent.cli.run import register_run_command
from hypeagent.cli.usage import usage_app
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


app.add_typer(usage_app, name="usage")


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


@app.command("dry-run")
def dry_run_cmd(ctx: typer.Context) -> None:
    """Propose actions without publishing (default mode)."""
    run_dry_run(ctx)


@app.command("cron-print")
def cron_print_cmd(
    ctx: typer.Context,
    times: Annotated[
        str,
        typer.Option("--times", help="Comma-separated run times (HH:MM)"),
    ] = "09:00",
    timezone: Annotated[
        str,
        typer.Option("--timezone", help="IANA timezone for CRON_TZ"),
    ] = "UTC",
    project_dir: Annotated[
        Path | None,
        typer.Option("--project-dir", help="Project directory for cd in crontab"),
    ] = None,
    log_file: Annotated[
        Path,
        typer.Option("--log-file", help="Cron log file path (relative to project-dir)"),
    ] = Path("logs/cron.log"),
    mode: Annotated[
        str,
        typer.Option("--mode", help="Run mode passed to hypeagent run"),
    ] = "auto",
) -> None:
    """Print suggested crontab lines for scheduled runs."""
    ctx_obj = ctx.obj or {}
    config_path = ctx_obj.get("config", Path("hypeagent.yaml"))
    secrets_path = ctx_obj.get("secrets", Path("secrets.local.yaml"))
    resolved_project = project_dir or Path.cwd()
    run_cron_print(
        times=times,
        timezone=timezone,
        project_dir=resolved_project.resolve(),
        config_path=config_path,
        secrets_path=secrets_path,
        log_file=log_file,
        mode=mode,
    )


register_run_command(app)
