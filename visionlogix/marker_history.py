from __future__ import annotations

import os
import ssl
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit


class MarkerHistoryUnavailable(RuntimeError):
    """Raised when the configured marker-history database cannot be reached."""


class MarkerHistoryStore:
    """Persist one record per assigned marker delivery."""

    def __init__(
        self,
        path: Path,
        database_url: str | None = None,
        require_database_url: bool = False,
    ) -> None:
        self.path = path
        self.database_url = database_url
        self.require_database_url = require_database_url
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._synced_state: dict[str, tuple[str, str | None, str | None]] = {}
        if not self.database_url and not self.require_database_url:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        if self.require_database_url and not self.database_url:
            raise MarkerHistoryUnavailable(
                "Configure DATABASE_URL with the Neon Postgres connection string "
                "to enable persistent marker history on Vercel."
            )

        if self.database_url:
            try:
                from pg8000 import dbapi
            except ImportError as exc:
                raise MarkerHistoryUnavailable(
                    "The PostgreSQL driver is missing. Install project requirements."
                ) from exc
            try:
                parsed_url = urlsplit(self.database_url)
                if (
                    parsed_url.scheme not in {"postgres", "postgresql"}
                    or not parsed_url.hostname
                    or not parsed_url.username
                    or not parsed_url.path.strip("/")
                ):
                    raise ValueError("DATABASE_URL must be a PostgreSQL URL.")
                connection = dbapi.connect(
                    user=unquote(parsed_url.username),
                    password=unquote(parsed_url.password or ""),
                    host=parsed_url.hostname,
                    port=parsed_url.port or 5432,
                    database=unquote(parsed_url.path.lstrip("/")),
                    timeout=5,
                    ssl_context=ssl.create_default_context(),
                )
                try:
                    with connection:
                        yield connection
                finally:
                    connection.close()
            except (dbapi.Error, OSError, ValueError) as exc:
                raise MarkerHistoryUnavailable(
                    "The marker-history database is unavailable. Check DATABASE_URL "
                    "and the Neon database status."
                ) from exc
            return

        try:
            with closing(sqlite3.connect(self.path, timeout=5)) as connection:
                with connection:
                    yield connection
        except sqlite3.Error as exc:
            raise MarkerHistoryUnavailable(
                "The local marker-history database is unavailable."
            ) from exc

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS marker_records (
                        record_id TEXT PRIMARY KEY,
                        marker_id INTEGER NOT NULL,
                        zone_id TEXT NOT NULL,
                        zone_name TEXT NOT NULL,
                        center_x INTEGER,
                        center_y INTEGER,
                        side_pixels REAL,
                        status TEXT NOT NULL,
                        detected_at TEXT NOT NULL,
                        started_at TEXT,
                        completed_at TEXT,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS marker_records_detected_at
                    ON marker_records (detected_at)
                    """
                )
            self._schema_ready = True

    def sync_warehouse(
        self,
        warehouse_state: dict[str, Any],
        detections: list[dict[str, Any]],
        run_id: str = "default",
    ) -> None:
        self._ensure_schema()
        detection_by_id = {
            item["marker_id"]: item
            for item in detections
            if isinstance(item, dict)
            and isinstance(item.get("marker_id"), int)
            and not isinstance(item.get("marker_id"), bool)
        }
        pending_cache: dict[str, tuple[str, str | None, str | None]] = {}
        placeholder = "%s" if self.database_url else "?"
        with self._sync_lock:
            with self._connection() as connection:
                for robot in warehouse_state.get("robots", []):
                    if not isinstance(robot, dict):
                        continue
                    marker_id = robot.get("marker_id")
                    created_at = robot.get("created_at")
                    if (
                        isinstance(marker_id, bool)
                        or not isinstance(marker_id, int)
                        or not isinstance(created_at, str)
                    ):
                        continue

                    record_id = f"{run_id}:{marker_id}"
                    status = str(robot.get("status", "unknown"))
                    started_at = robot.get("started_at")
                    completed_at = robot.get("delivered_at")
                    synced = (status, started_at, completed_at)
                    if self._synced_state.get(record_id) == synced:
                        continue

                    detection = detection_by_id.get(marker_id, {})
                    center_x = detection.get("center_x")
                    center_y = detection.get("center_y")
                    side_pixels = detection.get("side_pixels")
                    if isinstance(center_x, bool) or not isinstance(center_x, int):
                        center_x = None
                    if isinstance(center_y, bool) or not isinstance(center_y, int):
                        center_y = None
                    if isinstance(side_pixels, bool) or not isinstance(
                        side_pixels, (int, float)
                    ):
                        side_pixels = None

                    connection.execute(
                        f"""
                        INSERT INTO marker_records (
                            record_id, marker_id, zone_id, zone_name,
                            center_x, center_y, side_pixels, status, detected_at,
                            started_at, completed_at, updated_at
                        )
                        VALUES ({", ".join([placeholder] * 12)})
                        ON CONFLICT(record_id) DO UPDATE SET
                            status = CASE
                                WHEN marker_records.status IN ('delivered', 'blocked')
                                    THEN marker_records.status
                                ELSE excluded.status
                            END,
                            started_at = COALESCE(
                                marker_records.started_at, excluded.started_at
                            ),
                            completed_at = COALESCE(
                                marker_records.completed_at, excluded.completed_at
                            ),
                            updated_at = excluded.updated_at
                        """,
                        (
                            record_id,
                            marker_id,
                            str(robot.get("zone_id", "")),
                            str(robot.get("zone_name", "")),
                            center_x,
                            center_y,
                            side_pixels,
                            status,
                            created_at,
                            started_at,
                            completed_at,
                            datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                        ),
                    )
                    pending_cache[record_id] = synced
            self._synced_state.update(pending_cache)

    def list_records(self, limit: int = 100) -> dict[str, Any]:
        self._ensure_schema()
        bounded_limit = min(max(limit, 1), 500)
        placeholder = "%s" if self.database_url else "?"
        with self._connection() as connection:
            count_cursor = connection.execute(
                "SELECT COUNT(*) FROM marker_records"
            )
            total = int(count_cursor.fetchone()[0])
            cursor = connection.execute(
                f"""
                SELECT record_id, marker_id, zone_id, zone_name, center_x,
                       center_y, side_pixels, status, detected_at, started_at,
                       completed_at
                FROM marker_records
                ORDER BY detected_at DESC, record_id DESC
                LIMIT {placeholder}
                """,
                (bounded_limit,),
            )
            columns = [column[0] for column in cursor.description]
            records = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return {"records": records, "total": total}
