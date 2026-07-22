"""CLI live run command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hypeagent.cli.run_common import execute_run
from hypeagent.models.run import RunMode


def run_live(
    ctx: typer.Context,
    mode: RunMode,
) -> None:
    """Run agents and publish actions according to --mode."""
    if mode == RunMode.DRY_RUN:
        typer.secho(
            "Use 'hypeagent dry-run' for dry-run mode.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=1)

    ctx_obj = ctx.obj or {}
    execute_run(
        config_path=ctx_obj.get("config", Path("hypeagent.yaml")),
        secrets_path=ctx_obj.get("secrets", Path("secrets.local.yaml")),
        db_path=ctx_obj.get("db"),
        verbose=bool(ctx_obj.get("verbose")),
        mode=mode,
    )


def register_run_command(app: typer.Typer) -> None:
    """Register `hypeagent run` with --mode on the root app."""

    @app.command("run")
    def run_cmd(
        ctx: typer.Context,
        mode: Annotated[
            RunMode,
            typer.Option(
                "--mode",
                "-m",
                help="Publish mode: approve (prompt) or auto (no prompt).",
            ),
        ] = RunMode.APPROVE,
    ) -> None:
        """Run agents and publish with --mode approve or auto."""
        run_live(ctx, mode)
