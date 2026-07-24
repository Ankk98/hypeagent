"""CLI validation command."""

from __future__ import annotations

from pathlib import Path

import typer

from hypeagent.config.engagement import validate_engagement_against_capabilities
from hypeagent.config.loader import ConfigError, load_config
from hypeagent.config.schema import HypeagentConfig
from hypeagent.config.secrets import SecretsError, load_secrets, validate_account_refs
from hypeagent.config.secrets_schema import Secrets
from hypeagent.knowledge.tools import validate_tools
from hypeagent.platforms.base import PlatformConnector
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

    if config.knowledge.tools:
        tool_errors = validate_tools(config.knowledge.tools)
        if tool_errors:
            for message in tool_errors:
                typer.secho(f"✗ {message}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        tool_names = ", ".join(tool.name for tool in config.knowledge.tools)
        typer.echo(f"✓ tools: {tool_names} importable")

    account_errors = validate_account_refs(config.personas, secrets)
    if account_errors:
        for message in account_errors:
            typer.secho(f"✗ {message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo("✓ personas reference valid accounts")

    engagement_errors = _validate_engagement(config, connector_cls, secrets)
    if engagement_errors:
        for message in engagement_errors:
            typer.secho(f"✗ {message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if config.reactions_requested():
        typer.echo("✓ engagement reactions compatible with connector capabilities")

    typer.echo(
        f"✓ budgets: daily=${config.budgets.llm_daily_usd:.2f} "
        f"total=${config.budgets.llm_total_usd:.2f}"
    )
    typer.echo("Ready.")


def _validate_engagement(
    config: HypeagentConfig,
    connector_cls: type[PlatformConnector],
    secrets: Secrets,
) -> list[str]:
    if not config.reactions_requested():
        return []

    first_agent = config.run.agents[0]
    account = secrets.accounts[config.personas[first_agent].account]
    connector = connector_cls(config.platform, account, config.http)
    try:
        caps = connector.capabilities()
    finally:
        close = getattr(connector, "close", None)
        if callable(close):
            close()
    return validate_engagement_against_capabilities(config, caps)
