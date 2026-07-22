"""SQLite-backed per-persona short-term memory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from hypeagent.db.connection import Database


@dataclass(frozen=True)
class AgentMemoryEntry:
    agent_id: str
    content_id: str
    action_type: str
    text_preview: str
    created_at: str


class AgentMemoryRepository:
    """Record and query agent short-term memory (§8)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def record(
        self,
        *,
        agent_id: str,
        content_id: str,
        action_type: str,
        text_preview: str,
        created_at: str | None = None,
    ) -> None:
        """Insert a short-term memory row for a persona."""
        preview = text_preview[:200]
        timestamp = created_at or self._utc_now_iso()
        self._db.conn.execute(
            """
            INSERT INTO agent_short_memory (
              agent_id, content_id, action_type, text_preview, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (agent_id, content_id, action_type, preview, timestamp),
        )
        self._db.conn.commit()

    def get_recent(self, agent_id: str, *, limit: int = 10) -> list[AgentMemoryEntry]:
        """Return the most recent memory entries for a persona."""
        rows = self._db.conn.execute(
            """
            SELECT agent_id, content_id, action_type, text_preview, created_at
            FROM agent_short_memory
            WHERE agent_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (agent_id, limit),
        ).fetchall()
        return [
            AgentMemoryEntry(
                agent_id=str(row["agent_id"]),
                content_id=str(row["content_id"]),
                action_type=str(row["action_type"]),
                text_preview=str(row["text_preview"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]
