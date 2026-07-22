"""CLI dry-run command (default run mode)."""

from __future__ import annotations

from pathlib import Path

import typer

from hypeagent.cli.run_common import execute_run
from hypeagent.models.run import RunMode


def run_dry_run(ctx: typer.Context) -> None:
    """Propose actions without publishing to the platform."""
    ctx_obj = ctx.obj or {}
    execute_run(
        config_path=ctx_obj.get("config", Path("hypeagent.yaml")),
        secrets_path=ctx_obj.get("secrets", Path("secrets.local.yaml")),
        db_path=ctx_obj.get("db"),
        verbose=bool(ctx_obj.get("verbose")),
        mode=RunMode.DRY_RUN,
    )
