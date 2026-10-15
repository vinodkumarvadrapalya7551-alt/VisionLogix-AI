from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


class AppStateStore:
    """Persist the latest application snapshots in a local SQLite database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )

    def load(self, key: str) -> Any | None:
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT value FROM app_state WHERE key = ?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row is not None else None

    def save(self, key: str, value: Any) -> None:
        serialized = json.dumps(value, separators=(",", ":"))
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO app_state (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    WHERE app_state.value != excluded.value
                    """,
                    (key, serialized),
                )

    def clear(self, key: str) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute("DELETE FROM app_state WHERE key = ?", (key,))
