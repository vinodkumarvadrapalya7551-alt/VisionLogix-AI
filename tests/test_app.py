import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import cv2
import numpy as np

from app import app, warehouse
from visionlogix.camera import CameraService, open_camera
from visionlogix.state_store import AppStateStore
from warehouse import WarehouseService


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_home_page_renders_detection_and_warehouse_interface(self):
        with (
            patch("app.camera.stop") as camera_stop,
            patch("app.warehouse.reset") as warehouse_reset,
            patch("app.state_store.clear") as clear_saved_state,
        ):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"STAGE 02", response.data)
        self.assertIn(b"Detected markers", response.data)
        self.assertIn(b"Warehouse overview", response.data)
        camera_stop.assert_called_once_with()
        warehouse_reset.assert_called_once_with()
        self.assertEqual(
            clear_saved_state.call_args_list,
            [call("detections"), call("warehouse")],
        )

    def test_status_endpoint_reports_camera_initially_off(self):
        response = self.client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["running"])

    def test_status_endpoint_includes_last_saved_detections(self):
        last_detections = [{"marker_id": 7, "center_x": 30}]
        state_store = MagicMock()
        state_store.load.return_value = last_detections
        camera_status = {
            "running": False,
            "detections": [],
            "message": "Camera is not connected.",
        }

        with (
            patch("app.camera.status", return_value=camera_status),
            patch("app.state_store", state_store),
        ):
            response = self.client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["last_detections"], last_detections)

    def test_status_endpoint_saves_current_detections(self):
        detections = [{"marker_id": 7, "center_x": 30}]
        state_store = MagicMock()
        state_store.load.return_value = detections
        camera_status = {
            "running": True,
            "detections": detections,
            "message": "Camera connected.",
        }

        with (
            patch("app.camera.status", return_value=camera_status),
            patch("app.state_store", state_store),
        ):
            response = self.client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        state_store.save.assert_called_once_with("detections", detections)

    def test_favicon_endpoint_returns_the_application_icon(self):
        with self.client.get("/favicon.ico") as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/svg+xml")

    def test_marker_endpoint_returns_png_and_rejects_unsupported_id(self):
        valid = self.client.get("/api/marker/7.png")
        maximum = self.client.get("/api/marker/96.png")
        invalid = self.client.get("/api/marker/97.png")

        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.mimetype, "image/png")
        self.assertTrue(valid.data.startswith(b"\x89PNG"))
        self.assertEqual(maximum.status_code, 200)
        self.assertEqual(invalid.status_code, 400)

    def test_warehouse_endpoint_turns_a_detected_marker_into_a_delivery(self):
        warehouse.reset()
        with tempfile.TemporaryDirectory() as directory:
            store = AppStateStore(Path(directory) / "state.sqlite3")
            with (
                patch("app.camera.detections", return_value=[{"marker_id": 20}]),
                patch("app.state_store", store),
            ):
                response = self.client.get("/api/warehouse")
            restored_warehouse = WarehouseService()
            restored_warehouse.restore(store.load("warehouse"))
            restored_state = restored_warehouse.snapshot()
        warehouse.reset()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["robots"][0]["marker_id"], 20)
        self.assertEqual(response.json["robots"][0]["zone_id"], "1")
        self.assertEqual(response.json["summary"]["moving"], 1)
        self.assertEqual(restored_state["robots"][0]["marker_id"], 20)

    def test_warehouse_reset_endpoint_clears_delivery_state(self):
        warehouse.observe_detections([{"marker_id": 4}])

        with patch("app.state_store.save"):
            response = self.client.post("/api/warehouse/reset")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["summary"]["total"], 0)


class CameraBackendTests(unittest.TestCase):
    @patch("visionlogix.camera.platform.system", return_value="Windows")
    @patch("visionlogix.camera.cv2.VideoCapture")
    def test_uses_directshow_on_windows(self, video_capture, _system):
        capture = MagicMock()
        capture.isOpened.return_value = True
        video_capture.return_value = capture

        result, backend = open_camera(0)

        self.assertIs(result, capture)
        self.assertEqual(backend, "DirectShow")
        video_capture.assert_called_once_with(0, cv2.CAP_DSHOW)

    @patch("visionlogix.camera.platform.system", return_value="Windows")
    @patch("visionlogix.camera.cv2.VideoCapture")
    def test_falls_back_when_directshow_is_unavailable(self, video_capture, _system):
        directshow = MagicMock()
        directshow.isOpened.return_value = False
        default = MagicMock()
        default.isOpened.return_value = True
        video_capture.side_effect = [directshow, default]

        result, backend = open_camera(2)

        self.assertIs(result, default)
        self.assertEqual(backend, "default")
        directshow.release.assert_called_once()
        self.assertEqual(video_capture.call_args_list, [
            call(2, cv2.CAP_DSHOW),
            call(2),
        ])

    @patch("visionlogix.camera.open_camera")
    def test_camera_is_opened_read_and_released_on_worker_thread(self, mock_open):
        frame = np.full((120, 160, 3), 255, dtype=np.uint8)
        open_thread_ids = []
        read_thread_ids = []
        release_thread_ids = []
        capture = MagicMock()

        def fake_open(_index):
            open_thread_ids.append(threading.get_ident())
            return capture, "test backend"

        def fake_read():
            read_thread_ids.append(threading.get_ident())
            return True, frame

        mock_open.side_effect = fake_open
        capture.read.side_effect = fake_read
        capture.release.side_effect = lambda: release_thread_ids.append(threading.get_ident())

        service = CameraService()
        try:
            started, _ = service.start()

            self.assertTrue(started)
            self.assertTrue(read_thread_ids)
            self.assertTrue(all(
                thread_id == open_thread_ids[0]
                for thread_id in read_thread_ids
            ))
        finally:
            service.stop()

        self.assertEqual(release_thread_ids, [open_thread_ids[0]])

    @patch("visionlogix.camera.open_camera")
    def test_camera_reports_opencv_read_errors_and_releases_capture(self, mock_open):
        capture = MagicMock()
        capture.read.side_effect = cv2.error("simulated read failure")
        mock_open.return_value = capture, "test backend"
        service = CameraService()

        started, message = service.start()

        try:
            self.assertFalse(started)
            self.assertIn("OpenCV camera error", message)
            self.assertIn("simulated read failure", message)
            self.assertFalse(service.status()["starting"])
        finally:
            service.stop()

        capture.release.assert_called_once_with()

    def test_video_feed_returns_clear_error_if_camera_is_not_running(self):
        response = app.test_client().get("/video_feed")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "Camera is not ready to stream frames.")


if __name__ == "__main__":
    unittest.main()
