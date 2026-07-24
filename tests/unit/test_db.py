"""Unit tests for SQLite schema, usage repository, and budget guard."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hypeagent.config.schema import BudgetConfig
from hypeagent.db.connection import Database
from hypeagent.db.migrations import SCHEMA_VERSION, current_version, migrate
from hypeagent.db.repositories.usage import UsageRepository
from hypeagent.llm.budget import BudgetExceededError, BudgetGuard

FIXTURES = Path(__file__).parent.parent / "fixtures"
EXAMPLE_CONFIG = Path("examples/reddit/hypeagent.yaml")


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def database(db_path: Path) -> Database:
    db = Database(db_path)
    yield db
    db.close()


@pytest.fixture
def usage_repo(database: Database) -> UsageRepository:
    return UsageRepository(database)


class TestMigrations:
    def test_applies_schema_on_connect(self, database: Database) -> None:
        assert current_version(database.conn) == SCHEMA_VERSION
        tables = {
            row[0]
            for row in database.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert tables >= {
            "schema_version",
            "llm_usage",
            "runs",
            "proposed_actions",
            "agent_short_memory",
            "budget_totals",
        }

    def test_idempotent_migration(self, database: Database) -> None:
        migrate(database.conn)
        assert current_version(database.conn) == SCHEMA_VERSION

    def test_proposed_actions_has_payload_columns(self, database: Database) -> None:
        columns = {
            row[1]
            for row in database.conn.execute("PRAGMA table_info(proposed_actions)").fetchall()
        }
        assert {"payload_json", "target_kind", "target_id"} <= columns

    def test_upgrades_v1_database(self, tmp_path: Path) -> None:
        import sqlite3

        from hypeagent.db.migrations import SCHEMA_V1, _set_version

        path = tmp_path / "legacy.db"
        conn = sqlite3.connect(path)
        # Simulate a v1 schema without payload columns.
        legacy_v1 = SCHEMA_V1.replace(
            "  created_at TEXT NOT NULL,\n"
            "  payload_json TEXT,\n"
            "  target_kind TEXT,\n"
            "  target_id TEXT,\n",
            "  created_at TEXT NOT NULL,\n",
        )
        conn.executescript(legacy_v1)
        _set_version(conn, 1)
        conn.close()

        with Database(path) as db:
            assert current_version(db.conn) == 2
            columns = {
                row[1]
                for row in db.conn.execute("PRAGMA table_info(proposed_actions)").fetchall()
            }
            assert {"payload_json", "target_kind", "target_id"} <= columns


class TestUsageRepository:
    def test_record_and_read_costs(self, usage_repo: UsageRepository) -> None:
        usage_repo.record_llm_usage(
            run_id="run1",
            agent_id="alice",
            model="openai/gpt-4o-mini",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.42,
        )
        assert usage_repo.get_daily_cost() == pytest.approx(0.42)
        assert usage_repo.get_total_cost() == pytest.approx(0.42)

    def test_usage_persists_across_connections(self, db_path: Path) -> None:
        with Database(db_path) as db:
            UsageRepository(db).record_llm_usage(
                run_id="run1",
                agent_id="alice",
                model="openai/gpt-4o-mini",
                tokens_in=10,
                tokens_out=5,
                cost_usd=0.10,
            )

        with Database(db_path) as db:
            repo = UsageRepository(db)
            assert repo.get_total_cost() == pytest.approx(0.10)

    def test_reset_clears_totals(self, usage_repo: UsageRepository, database: Database) -> None:
        usage_repo.record_llm_usage(
            run_id="run1",
            agent_id="alice",
            model="openai/gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            cost_usd=1.00,
        )
        usage_repo.reset()
        assert usage_repo.get_daily_cost() == 0.0
        assert usage_repo.get_total_cost() == 0.0
        row = database.conn.execute("SELECT COUNT(*) AS n FROM llm_usage").fetchone()
        assert row is not None
        assert int(row["n"]) == 1

    def test_reset_with_clear_usage(self, usage_repo: UsageRepository, database: Database) -> None:
        usage_repo.record_llm_usage(
            run_id="run1",
            agent_id="alice",
            model="openai/gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            cost_usd=1.00,
        )
        usage_repo.reset(clear_llm_usage=True)
        row = database.conn.execute("SELECT COUNT(*) AS n FROM llm_usage").fetchone()
        assert row is not None
        assert int(row["n"]) == 0

    def test_format_print_includes_caps(self, usage_repo: UsageRepository, db_path: Path) -> None:
        usage_repo.record_llm_usage(
            run_id="run1",
            agent_id="alice",
            model="openai/gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.42,
        )
        output = usage_repo.format_print(
            db_path=db_path,
            daily_cap=2.00,
            total_cap=50.00,
        )
        assert "LLM usage" in output
        assert "$0.42 / $2.00 daily cap" in output
        assert "$0.42 / $50.00 total cap" in output
        assert "0 proposed, 0 published" in output

    def test_action_and_run_counts(self, usage_repo: UsageRepository, database: Database) -> None:
        today = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        database.conn.execute(
            """
            INSERT INTO runs (
              run_id, config_name, mode, started_at, agents_total, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("run1", "test", "dry_run", today, 1, "completed"),
        )
        database.conn.execute(
            """
            INSERT INTO proposed_actions (
              run_id, agent_id, action_type, content_id, content_preview,
              draft_text, published, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("run1", "alice", "reply", "c1", "preview", "draft", 1, today),
        )
        database.conn.commit()

        proposed, published = usage_repo.get_action_counts_today()
        assert proposed == 1
        assert published == 1
        runs_today, runs_all = usage_repo.get_run_counts()
        assert runs_today == 1
        assert runs_all == 1


class TestBudgetGuard:
    def test_allows_under_cap(self, usage_repo: UsageRepository) -> None:
        budgets = BudgetConfig(llm_daily_usd=2.0, llm_total_usd=50.0)
        guard = BudgetGuard(budgets, usage_repo)
        guard.check()

    def test_raises_when_daily_cap_reached(self, usage_repo: UsageRepository) -> None:
        usage_repo.record_llm_usage(
            run_id="run1",
            agent_id="alice",
            model="openai/gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            cost_usd=2.00,
        )
        budgets = BudgetConfig(llm_daily_usd=2.0, llm_total_usd=50.0)
        guard = BudgetGuard(budgets, usage_repo)
        with pytest.raises(BudgetExceededError, match="Daily"):
            guard.check()

    def test_raises_when_total_cap_reached(self, usage_repo: UsageRepository) -> None:
        usage_repo.record_llm_usage(
            run_id="run1",
            agent_id="alice",
            model="openai/gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            cost_usd=50.00,
            created_at="2020-01-01T00:00:00Z",
        )
        budgets = BudgetConfig(llm_daily_usd=2.0, llm_total_usd=50.0)
        guard = BudgetGuard(budgets, usage_repo)
        with pytest.raises(BudgetExceededError, match="Total"):
            guard.check()
