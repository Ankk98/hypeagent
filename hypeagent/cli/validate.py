"""CLI validation command."""

from __future__ import annotations

from pathlib import Path

import typer

from hypeagent.config.loader import ConfigError, load_config
from hypeagent.config.secrets import SecretsError, load_secrets, validate_account_refs
from hypeagent.platforms.registry import ConnectorLoadError, load_connector


def run_validate(config_path: Path, secrets_path: Path) -> None:
    """Validate configuration and secrets; raise typer.Exit on failure."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        typer.secho(f"✗ hypeagent.yaml: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("✓ hypeagent.yaml schema valid")

    try:
        secrets = load_secrets(secrets_path)
    except SecretsError as exc:
        typer.secho(f"✗ secrets.local.yaml: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    account_count = len(secrets.accounts)
    suffix = "s" if account_count != 1 else ""
    typer.echo(f"✓ secrets.local.yaml loaded ({account_count} account{suffix})")

    try:
        connector_cls = load_connector(config.platform.connector)
    except ConnectorLoadError as exc:
        typer.secho(f"✗ connector: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"✓ connector {connector_cls.name!r} importable")

    account_errors = validate_account_refs(config.personas, secrets)
    if account_errors:
        for message in account_errors:
            typer.secho(f"✗ {message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo("✓ personas reference valid accounts")
    typer.echo(
        f"✓ budgets: daily=${config.budgets.llm_daily_usd:.2f} "
        f"total=${config.budgets.llm_total_usd:.2f}"
    )
    typer.echo("Ready.")
