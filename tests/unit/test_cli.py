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
    assert "✓ connector 'reddit' importable" in result.stdout
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
