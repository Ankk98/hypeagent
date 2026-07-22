"""CLI integration tests."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from hypeagent.cli.main import app

runner = CliRunner()
EXAMPLE_CONFIG = Path("examples/reddit/hypeagent.yaml")
EXAMPLE_SECRETS = Path("examples/reddit/secrets.example.yaml")
FIXTURES = Path("tests/fixtures")


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "1.0.0"


def test_validate_example_passes() -> None:
    result = runner.invoke(
        app,
        [
            "--config",
            str(EXAMPLE_CONFIG),
            "--secrets",
            str(EXAMPLE_SECRETS),
            "validate",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "✓ hypeagent.yaml schema valid" in result.stdout
    assert "✓ personas reference valid accounts" in result.stdout
    assert "Ready." in result.stdout


def test_validate_rejects_missing_account_ref() -> None:
    result = runner.invoke(
        app,
        [
            "--config",
            str(FIXTURES / "config_bad_account.yaml"),
            "--secrets",
            str(EXAMPLE_SECRETS),
            "validate",
        ],
    )
    assert result.exit_code == 1
    assert "unknown account" in result.stderr.lower() or "unknown account" in result.stdout.lower()
