"""Shared CLI logic for dry-run and live run commands."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer

from hypeagent.agent.approval import ApprovalQuitError
from hypeagent.agent.loop import AgentRunner
from hypeagent.config.loader import ConfigError, load_config
from hypeagent.config.schema import HypeagentConfig
from hypeagent.config.secrets import SecretsError, load_secrets, validate_account_refs
from hypeagent.config.secrets_schema import Secrets
from hypeagent.db.connection import Database, resolve_db_path
from hypeagent.llm.budget import BudgetExceededError
from hypeagent.models.run import RunMode, RunResult
from hypeagent.platforms.base import PlatformError


def _setup_logging(verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
        force=True,
    )
    return logging.getLogger("hypeagent")


def _load_run_inputs(
    config_path: Path,
    secrets_path: Path,
) -> tuple[HypeagentConfig, Secrets]:
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        typer.secho(f"✗ hypeagent.yaml: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    try:
        secrets = load_secrets(secrets_path)
    except SecretsError as exc:
        typer.secho(f"✗ secrets.local.yaml: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    account_errors = validate_account_refs(config.personas, secrets)
    if account_errors:
        for message in account_errors:
            typer.secho(f"✗ {message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    return config, secrets


def _exit_code_for_result(result: RunResult) -> int:
    if result.status == "budget_exceeded":
        return 2
    if any("Platform" in err or "platform" in err for err in result.errors):
        return 3
    if result.status == "failed" and result.errors:
        return 5
    return 0


def execute_run(
    *,
    config_path: Path,
    secrets_path: Path,
    db_path: Path | None,
    verbose: bool,
    mode: RunMode,
) -> None:
    """Load config, run agents, and exit with the appropriate status code."""
    config, secrets = _load_run_inputs(config_path, secrets_path)
    logger = _setup_logging(verbose)
    resolved_db = resolve_db_path(db_path)
    base_dir = config_path.resolve().parent

    try:
        with Database(resolved_db) as db:
            runner = AgentRunner(
                config,
                secrets,
                db,
                base_dir=base_dir,
                logger=logger,
            )
            result = runner.run_all(mode)
    except ApprovalQuitError:
        raise typer.Exit(code=4) from None
    except BudgetExceededError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    except PlatformError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc

    typer.echo(
        f"Run {result.run_id}: {result.status} "
        f"({len(result.proposed_actions)} proposed, "
        f"{len(result.published_actions)} published)"
    )
    raise typer.Exit(code=_exit_code_for_result(result))
