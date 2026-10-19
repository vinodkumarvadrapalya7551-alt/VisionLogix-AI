import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from visionlogix.marker_history import (
    MarkerHistoryStore,
    MarkerHistoryUnavailable,
)


class MarkerHistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.store = MarkerHistoryStore(
            Path(self.temp_directory.name) / "history.sqlite3"
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_saves_marker_details_and_delivery_status(self):
        state = {
            "robots": [
                {
                    "marker_id": 40,
                    "zone_id": "2",
                    "zone_name": "Zone B",
                    "status": "moving",
                    "created_at": "2026-10-16T02:00:00+00:00",
                    "started_at": "2026-10-16T02:00:01+00:00",
                    "delivered_at": None,
                }
            ]
        }
        detections = [
            {
                "marker_id": 40,
                "center_x": 120,
                "center_y": 80,
                "side_pixels": 47.5,
            }
        ]

        self.store.sync_warehouse(state, detections)
        result = self.store.list_records()

        self.assertEqual(result["total"], 1)
        self.assertEqual(
            result["records"][0],
            {
                "record_id": "default:40",
                "marker_id": 40,
                "zone_id": "2",
                "zone_name": "Zone B",
                "center_x": 120,
                "center_y": 80,
                "side_pixels": 47.5,
                "status": "moving",
                "detected_at": "2026-10-16T02:00:00+00:00",
                "started_at": "2026-10-16T02:00:01+00:00",
                "completed_at": None,
            },
        )

        state["robots"][0]["status"] = "delivered"
        state["robots"][0]["delivered_at"] = "2026-10-16T02:00:08+00:00"
        self.store.sync_warehouse(state, [])
        result = self.store.list_records()

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["status"], "delivered")
        self.assertEqual(
            result["records"][0]["completed_at"],
            "2026-10-16T02:00:08+00:00",
        )

    def test_repeated_camera_frames_do_not_duplicate_delivery_records(self):
        state = {
            "robots": [
                {
                    "marker_id": 7,
                    "zone_id": "1",
                    "zone_name": "Zone A",
                    "status": "moving",
                    "created_at": "2026-10-16T02:00:00+00:00",
                    "started_at": None,
                    "delivered_at": None,
                }
            ]
        }
        detection = [{"marker_id": 7, "center_x": 20, "center_y": 30}]

        self.store.sync_warehouse(state, detection)
        self.store.sync_warehouse(state, detection)
        result = self.store.list_records()

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["marker_id"], 7)

    def test_same_marker_in_a_new_run_creates_a_new_history_record(self):
        state = {
            "robots": [
                {
                    "marker_id": 7,
                    "zone_id": "1",
                    "zone_name": "Zone A",
                    "status": "moving",
                    "created_at": "2026-10-16T02:00:00+00:00",
                    "started_at": None,
                    "delivered_at": None,
                }
            ]
        }

        self.store.sync_warehouse(state, [], "first-run")
        self.store.sync_warehouse(state, [], "second-run")

        result = self.store.list_records()
        self.assertEqual(result["total"], 2)
        self.assertEqual(
            {record["record_id"] for record in result["records"]},
            {"first-run:7", "second-run:7"},
        )

    def test_marker_id_document_deduplicates_frames_but_keeps_unmapped_scans(self):
        detections = [{"marker_id": 99, "center_x": 20, "center_y": 30}]

        self.store.sync_scanned_markers(detections, "first-run")
        self.store.sync_scanned_markers(detections, "first-run")
        self.store.sync_scanned_markers(detections, "second-run")

        document = self.store.marker_id_document()
        self.assertIn("Total scan records: 2", document)
        self.assertEqual(document.count("99 | 20, 30 |"), 2)

    def test_records_survive_a_new_store_instance(self):
        state = {
            "robots": [
                {
                    "marker_id": 70,
                    "zone_id": "3",
                    "zone_name": "Zone C",
                    "status": "queued",
                    "created_at": "2026-10-16T02:00:00+00:00",
                    "started_at": None,
                    "delivered_at": None,
                }
            ]
        }
        self.store.sync_warehouse(state, [])

        restored = MarkerHistoryStore(self.store.path)

        self.assertEqual(restored.list_records()["records"][0]["marker_id"], 70)

    def test_vercel_requires_a_persistent_database_url(self):
        cloud_store = MarkerHistoryStore(
            Path("unused.sqlite3"),
            require_database_url=True,
        )

        with self.assertRaisesRegex(
            MarkerHistoryUnavailable,
            "DATABASE_URL",
        ):
            cloud_store.list_records()

    def test_postgres_connection_decodes_credentials_and_enforces_tls(self):
        connection = MagicMock()
        driver = SimpleNamespace(
            dbapi=SimpleNamespace(connect=MagicMock(return_value=connection), Error=Exception)
        )
        store = MarkerHistoryStore(
            Path("unused.sqlite3"),
            database_url=(
                "postgresql://user%40example:pass%2Fword@db.example.test/"
                "warehouse?sslmode=require"
            ),
        )

        with patch.dict(sys.modules, {"pg8000": driver}):
            with store._connection() as opened:
                self.assertIs(opened, connection)

        kwargs = driver.dbapi.connect.call_args.kwargs
        self.assertEqual(kwargs["user"], "user@example")
        self.assertEqual(kwargs["password"], "pass/word")
        self.assertEqual(kwargs["host"], "db.example.test")
        self.assertEqual(kwargs["database"], "warehouse")
        self.assertEqual(kwargs["timeout"], 5)
        self.assertIsNotNone(kwargs["ssl_context"])
        connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
