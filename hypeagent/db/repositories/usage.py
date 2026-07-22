"""LLM usage and budget totals persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hypeagent.db.connection import Database


@dataclass(frozen=True)
class LastRunInfo:
    started_at: str
    mode: str
    status: str


class UsageRepository:
    """Record and query LLM usage, budget totals, and run statistics."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _today_prefix() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    @staticmethod
    def _daily_key(date_prefix: str | None = None) -> str:
        prefix = date_prefix or datetime.now(UTC).strftime("%Y-%m-%d")
        return f"daily:{prefix}"

    def get_daily_cost(self, *, date_prefix: str | None = None) -> float:
        row = self._db.conn.execute(
            "SELECT cost_usd FROM budget_totals WHERE key = ?",
            (self._daily_key(date_prefix),),
        ).fetchone()
        return float(row["cost_usd"]) if row else 0.0

    def get_total_cost(self) -> float:
        row = self._db.conn.execute(
            "SELECT cost_usd FROM budget_totals WHERE key = 'total'",
        ).fetchone()
        return float(row["cost_usd"]) if row else 0.0

    def record_llm_usage(
        self,
        *,
        run_id: str,
        agent_id: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        created_at: str | None = None,
    ) -> None:
        """Insert an LLM usage row and update materialized budget totals."""
        timestamp = created_at or self._utc_now_iso()
        self._db.conn.execute(
            """
            INSERT INTO llm_usage (
              run_id, agent_id, model, tokens_in, tokens_out, cost_usd, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, agent_id, model, tokens_in, tokens_out, cost_usd, timestamp),
        )
        self._increment_budget_totals(timestamp, cost_usd)
        self._db.conn.commit()

    def _increment_budget_totals(self, updated_at: str, cost_usd: float) -> None:
        date_prefix = updated_at[:10]
        for key in (self._daily_key(date_prefix), "total"):
            self._db.conn.execute(
                """
                INSERT INTO budget_totals (key, cost_usd, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  cost_usd = budget_totals.cost_usd + excluded.cost_usd,
                  updated_at = excluded.updated_at
                """,
                (key, cost_usd, updated_at),
            )

    def get_action_counts_today(self) -> tuple[int, int]:
        """Return (proposed, published) action counts for today (UTC)."""
        prefix = self._today_prefix()
        row = self._db.conn.execute(
            """
            SELECT
              COUNT(*) AS proposed,
              COALESCE(SUM(published), 0) AS published
            FROM proposed_actions
            WHERE created_at LIKE ?
            """,
            (f"{prefix}%",),
        ).fetchone()
        assert row is not None
        return int(row["proposed"]), int(row["published"])

    def get_run_counts(self) -> tuple[int, int]:
        """Return (completed today, completed all time) run counts."""
        prefix = self._today_prefix()
        row = self._db.conn.execute(
            """
            SELECT
              SUM(CASE WHEN started_at LIKE ? AND status = 'completed' THEN 1 ELSE 0 END)
                AS completed_today,
              SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_all
            FROM runs
            """,
            (f"{prefix}%",),
        ).fetchone()
        assert row is not None
        return int(row["completed_today"] or 0), int(row["completed_all"] or 0)

    def get_last_run(self) -> LastRunInfo | None:
        row = self._db.conn.execute(
            """
            SELECT started_at, mode, status
            FROM runs
            ORDER BY started_at DESC
            LIMIT 1
            """,
        ).fetchone()
        if row is None:
            return None
        return LastRunInfo(
            started_at=str(row["started_at"]),
            mode=str(row["mode"]),
            status=str(row["status"]),
        )

    def reset(self, *, clear_llm_usage: bool = False) -> None:
        """Clear budget totals and optionally all llm_usage rows."""
        self._db.conn.execute("DELETE FROM budget_totals")
        if clear_llm_usage:
            self._db.conn.execute("DELETE FROM llm_usage")
        self._db.conn.commit()

    def format_print(
        self,
        *,
        db_path: Path,
        daily_cap: float,
        total_cap: float,
    ) -> str:
        """Format usage summary for `hypeagent usage print`."""
        today = self._today_prefix()
        daily_cost = self.get_daily_cost()
        total_cost = self.get_total_cost()
        proposed_today, published_today = self.get_action_counts_today()
        runs_today, runs_all = self.get_run_counts()
        last_run = self.get_last_run()

        lines = [
            f"LLM usage ({db_path})",
            f"  Today ({today}):  ${daily_cost:.2f} / ${daily_cap:.2f} daily cap",
            f"  All time:            ${total_cost:.2f} / ${total_cap:.2f} total cap",
            "",
            "Actions",
            f"  Today:  {proposed_today} proposed, {published_today} published",
            f"  Runs:   {runs_today} completed today, {runs_all} all time",
        ]
        if last_run is not None:
            lines.append(
                f"\nLast run: {last_run.started_at} mode={last_run.mode} status={last_run.status}"
            )
        return "\n".join(lines)
