"""SQLite connection and lifecycle."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hypeagent.db.migrations import migrate

DEFAULT_DB_DIR = Path.home() / ".hypeagent"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "hypeagent.db"


class Database:
    """SQLite database with automatic schema migration on open."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        migrate(self._conn)

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def resolve_db_path(db: Path | None) -> Path:
    """Return explicit --db path or the default ~/.hypeagent/hypeagent.db."""
    return db if db is not None else DEFAULT_DB_PATH
