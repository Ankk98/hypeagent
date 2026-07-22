"""Run and proposed-action persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from hypeagent.db.connection import Database
from hypeagent.models.action import ProposedAction


@dataclass(frozen=True)
class StoredProposedAction:
    """Proposed action row loaded from SQLite."""

    id: int
    run_id: str
    agent_id: str
    action_type: str
    content_id: str
    content_preview: str
    parent_comment_id: str | None
    parent_preview: str | None
    draft_text: str
    published: bool
    platform_comment_id: str | None
    created_at: str


class RunsRepository:
    """Persist runs and proposed actions (§8)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def start_run(
        self,
        *,
        run_id: str,
        config_name: str,
        mode: str,
        agents_total: int,
        started_at: str | None = None,
    ) -> None:
        """Insert a running row for a CLI invocation."""
        timestamp = started_at or self._utc_now_iso()
        self._db.conn.execute(
            """
            INSERT INTO runs (
              run_id, config_name, mode, started_at, agents_total, status
            ) VALUES (?, ?, ?, ?, ?, 'running')
            """,
            (run_id, config_name, mode, timestamp, agents_total),
        )
        self._db.conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        actions_proposed: int,
        actions_published: int,
        llm_cost_usd: float,
        status: str,
        finished_at: str | None = None,
    ) -> None:
        """Update a run row when the invocation completes."""
        timestamp = finished_at or self._utc_now_iso()
        self._db.conn.execute(
            """
            UPDATE runs SET
              finished_at = ?,
              actions_proposed = ?,
              actions_published = ?,
              llm_cost_usd = ?,
              status = ?
            WHERE run_id = ?
            """,
            (
                timestamp,
                actions_proposed,
                actions_published,
                llm_cost_usd,
                status,
                run_id,
            ),
        )
        self._db.conn.commit()

    def get_run_llm_cost(self, run_id: str) -> float:
        """Sum LLM spend recorded for a run."""
        row = self._db.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM llm_usage WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row is not None
        return float(row["total"])

    def save_proposed(self, proposed: ProposedAction) -> int:
        """Insert a proposed action and return its row id."""
        created_at = proposed.created_at.isoformat().replace("+00:00", "Z")
        cursor = self._db.conn.execute(
            """
            INSERT INTO proposed_actions (
              run_id, agent_id, action_type, content_id, content_preview,
              parent_comment_id, parent_preview, draft_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposed.run_id,
                proposed.agent_id,
                proposed.action_type.value,
                proposed.content_id,
                proposed.content_body_preview,
                proposed.parent_comment_id,
                proposed.parent_comment_preview,
                proposed.draft_text,
                created_at,
            ),
        )
        self._db.conn.commit()
        row_id = cursor.lastrowid
        assert row_id is not None
        return int(row_id)

    def mark_published(self, action_id: int, platform_comment_id: str) -> None:
        """Mark a proposed action as published."""
        self._db.conn.execute(
            """
            UPDATE proposed_actions
            SET published = 1, platform_comment_id = ?
            WHERE id = ?
            """,
            (platform_comment_id, action_id),
        )
        self._db.conn.commit()

    def get_proposed_for_run(self, run_id: str) -> list[StoredProposedAction]:
        """Return all proposed actions for a run, oldest first."""
        rows = self._db.conn.execute(
            """
            SELECT
              id, run_id, agent_id, action_type, content_id, content_preview,
              parent_comment_id, parent_preview, draft_text, published,
              platform_comment_id, created_at
            FROM proposed_actions
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            StoredProposedAction(
                id=int(row["id"]),
                run_id=str(row["run_id"]),
                agent_id=str(row["agent_id"]),
                action_type=str(row["action_type"]),
                content_id=str(row["content_id"]),
                content_preview=str(row["content_preview"]),
                parent_comment_id=row["parent_comment_id"],
                parent_preview=row["parent_preview"],
                draft_text=str(row["draft_text"]),
                published=bool(row["published"]),
                platform_comment_id=row["platform_comment_id"],
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    @staticmethod
    def preview_text(text: str, max_len: int = 200) -> str:
        """First N characters for approval UI and DB previews."""
        stripped = text.strip()
        if len(stripped) <= max_len:
            return stripped
        if max_len <= 3:
            return stripped[:max_len]
        return stripped[: max_len - 3].rstrip() + "..."
