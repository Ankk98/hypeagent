"""CLI integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
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
    assert "✓ connector 'reddit' importable" in result.stdout
    assert "✓ tools: show_context, recent_episode importable" in result.stdout
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


def test_usage_print_empty_db(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.db"
    result = runner.invoke(
        app,
        [
            "--config",
            str(EXAMPLE_CONFIG),
            "--db",
            str(db_path),
            "usage",
            "print",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "LLM usage" in result.stdout
    assert "$0.00 / $2.00 daily cap" in result.stdout
    assert "$0.00 / $50.00 total cap" in result.stdout


def test_usage_reset_requires_confirm(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.db"
    result = runner.invoke(
        app,
        ["--db", str(db_path), "usage", "reset"],
    )
    assert result.exit_code == 1
    assert "--confirm" in result.stderr


def test_usage_reset_clears_totals(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.db"
    from hypeagent.db.connection import Database
    from hypeagent.db.repositories.usage import UsageRepository

    with Database(db_path) as db:
        UsageRepository(db).record_llm_usage(
            run_id="run1",
            agent_id="alice",
            model="openai/gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            cost_usd=1.50,
        )

    result = runner.invoke(
        app,
        ["--db", str(db_path), "usage", "reset", "--confirm"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    with Database(db_path) as db:
        repo = UsageRepository(db)
        assert repo.get_total_cost() == 0.0


def test_dry_run_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hypeagent.models.run import RunMode

    captured: dict[str, RunMode] = {}

    def fake_execute_run(**kwargs: object) -> None:
        captured["mode"] = kwargs["mode"]  # type: ignore[index]
        raise typer.Exit(code=0)

    from hypeagent.cli import dry_run as dry_run_module

    monkeypatch.setattr(dry_run_module, "execute_run", fake_execute_run)

    result = runner.invoke(
        app,
        [
            "--config",
            str(EXAMPLE_CONFIG),
            "--secrets",
            str(EXAMPLE_SECRETS),
            "--db",
            str(tmp_path / "dry.db"),
            "dry-run",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured["mode"] == RunMode.DRY_RUN


def test_run_command_auto_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hypeagent.models.run import RunMode

    captured: dict[str, RunMode] = {}

    def fake_execute_run(**kwargs: object) -> None:
        captured["mode"] = kwargs["mode"]  # type: ignore[index]
        raise typer.Exit(code=0)

    from hypeagent.cli import run as run_module

    monkeypatch.setattr(run_module, "execute_run", fake_execute_run)

    result = runner.invoke(
        app,
        [
            "--config",
            str(EXAMPLE_CONFIG),
            "--secrets",
            str(EXAMPLE_SECRETS),
            "--db",
            str(tmp_path / "run.db"),
            "run",
            "--mode",
            "auto",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured["mode"] == RunMode.AUTO


def test_run_command_rejects_dry_run_mode() -> None:
    result = runner.invoke(
        app,
        [
            "--config",
            str(EXAMPLE_CONFIG),
            "--secrets",
            str(EXAMPLE_SECRETS),
            "run",
            "--mode",
            "dry_run",
        ],
    )
    assert result.exit_code == 1
    assert "dry-run" in result.stderr.lower()


def test_cron_print_outputs_crontab_lines() -> None:
    result = runner.invoke(
        app,
        [
            "--config",
            str(EXAMPLE_CONFIG),
            "--secrets",
            str(EXAMPLE_SECRETS),
            "cron-print",
            "--times",
            "09:00,13:00,18:00,22:00",
            "--timezone",
            "Asia/Kolkata",
            "--project-dir",
            str(Path("examples/reddit").resolve()),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "# Paste into crontab -e" in result.stdout
    assert "CRON_TZ=Asia/Kolkata" in result.stdout
    assert "0 9 * * *" in result.stdout
    assert "0 13 * * *" in result.stdout
    assert "0 18 * * *" in result.stdout
    assert "0 22 * * *" in result.stdout
    assert "hypeagent run --mode auto" in result.stdout
    assert ">> logs/cron.log 2>&1" in result.stdout


def test_validate_example_from_reddit_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    reddit_dir = Path("examples/reddit").resolve()
    monkeypatch.chdir(reddit_dir)
    result = runner.invoke(
        app,
        [
            "--config",
            "hypeagent.yaml",
            "--secrets",
            "secrets.example.yaml",
            "validate",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "✓ tools: show_context, recent_episode importable" in result.stdout

