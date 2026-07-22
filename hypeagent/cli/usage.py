"""CLI usage commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hypeagent.config.loader import ConfigError, load_config
from hypeagent.db.connection import Database, resolve_db_path
from hypeagent.db.repositories.usage import UsageRepository

usage_app = typer.Typer(
    help="Inspect and reset LLM usage stored in SQLite.",
    no_args_is_help=True,
)


def _load_budget_caps(config_path: Path) -> tuple[float, float]:
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        typer.secho(f"✗ hypeagent.yaml: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    return config.budgets.llm_daily_usd, config.budgets.llm_total_usd


@usage_app.command("print")
def usage_print(ctx: typer.Context) -> None:
    """Print daily and total LLM spend plus action/run counts."""
    ctx_obj = ctx.obj or {}
    config_path = ctx_obj.get("config", Path("hypeagent.yaml"))
    db_path = resolve_db_path(ctx_obj.get("db"))

    daily_cap, total_cap = _load_budget_caps(config_path)

    with Database(db_path) as db:
        repo = UsageRepository(db)
        output = repo.format_print(
            db_path=db_path,
            daily_cap=daily_cap,
            total_cap=total_cap,
        )
    typer.echo(output)


@usage_app.command("reset")
def usage_reset(
    ctx: typer.Context,
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Required to reset budget totals"),
    ] = False,
    clear_usage: Annotated[
        bool,
        typer.Option(
            "--clear-usage",
            help="Also delete all rows from llm_usage",
        ),
    ] = False,
) -> None:
    """Reset budget totals (and optionally llm_usage history)."""
    if not confirm:
        typer.secho(
            "Refusing to reset without --confirm.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    ctx_obj = ctx.obj or {}
    db_path = resolve_db_path(ctx_obj.get("db"))

    with Database(db_path) as db:
        UsageRepository(db).reset(clear_llm_usage=clear_usage)

    scope = "budget totals and llm_usage" if clear_usage else "budget totals"
    typer.echo(f"Reset {scope} in {db_path}.")
