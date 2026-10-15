import tempfile
import unittest
from pathlib import Path

from visionlogix.state_store import AppStateStore


class AppStateStoreTests(unittest.TestCase):
    def test_saved_state_is_available_from_a_new_store_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            first_store = AppStateStore(path)
            first_store.save("detections", [{"marker_id": 7, "center_x": 30}])

            second_store = AppStateStore(path)

            self.assertEqual(
                second_store.load("detections"),
                [{"marker_id": 7, "center_x": 30}],
            )

    def test_missing_state_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AppStateStore(Path(directory) / "state.sqlite3")

            self.assertIsNone(store.load("warehouse"))


if __name__ == "__main__":
    unittest.main()
