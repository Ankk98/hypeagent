"""SQLite schema migrations."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  model TEXT NOT NULL,
  tokens_in INTEGER NOT NULL,
  tokens_out INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  config_name TEXT NOT NULL,
  mode TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  agents_total INTEGER NOT NULL,
  actions_proposed INTEGER NOT NULL DEFAULT 0,
  actions_published INTEGER NOT NULL DEFAULT 0,
  llm_cost_usd REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposed_actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  action_type TEXT NOT NULL,
  content_id TEXT NOT NULL,
  content_preview TEXT NOT NULL,
  parent_comment_id TEXT,
  parent_preview TEXT,
  draft_text TEXT NOT NULL,
  published INTEGER NOT NULL DEFAULT 0,
  platform_comment_id TEXT,
  created_at TEXT NOT NULL,
  payload_json TEXT,
  target_kind TEXT,
  target_id TEXT,
  FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS agent_short_memory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL,
  content_id TEXT NOT NULL,
  action_type TEXT NOT NULL,
  text_preview TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_agent ON agent_short_memory(agent_id, created_at DESC);

CREATE TABLE IF NOT EXISTS budget_totals (
  key TEXT PRIMARY KEY,
  cost_usd REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
"""


def current_version(conn: sqlite3.Connection) -> int:
    """Return applied schema version, or 0 if not initialized."""
    try:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Add ActionSpec payload / target columns to proposed_actions."""
    existing = _column_names(conn, "proposed_actions")
    for column, decl in (
        ("payload_json", "TEXT"),
        ("target_kind", "TEXT"),
        ("target_id", "TEXT"),
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE proposed_actions ADD COLUMN {column} {decl}")
    conn.commit()


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending migrations."""
    version = current_version(conn)
    if version < 1:
        conn.executescript(SCHEMA_V1)
        _set_version(conn, 1)
        version = 1
    if version < 2:
        # Fresh installs already have v2 columns in SCHEMA_V1; ALTER is a no-op then.
        _migrate_v2(conn)
        _set_version(conn, 2)
