import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import cv2
import numpy as np

from app import app, warehouse
from visionlogix.camera import CameraService, open_camera
from visionlogix.marker_history import MarkerHistoryStore
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

    def test_database_page_renders_saved_marker_history_view(self):
        response = self.client.get("/database")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Saved marker records", response.data)
        self.assertIn(b"Camera image position", response.data)

    def test_warehouse_detection_is_saved_and_exposed_by_marker_records_api(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MarkerHistoryStore(Path(directory) / "history.sqlite3")
            test_warehouse = WarehouseService()
            detections = [
                {
                    "marker_id": 40,
                    "center_x": 120,
                    "center_y": 80,
                    "side_pixels": 47.5,
                }
            ]
            with (
                patch("app.marker_history", store),
                patch("app.warehouse", test_warehouse),
                patch("app.camera.detections", return_value=detections),
                patch("app.state_store.save"),
            ):
                self.client.get("/api/warehouse")
                records = self.client.get("/api/marker-records")
                self.client.get("/api/warehouse")
                repeated = self.client.get("/api/marker-records")

        self.assertEqual(records.status_code, 200)
        self.assertEqual(records.json["total"], 1)
        self.assertEqual(records.json["records"][0]["marker_id"], 40)
        self.assertEqual(records.json["records"][0]["zone_name"], "Zone B")
        self.assertEqual(records.json["records"][0]["center_x"], 120)
        self.assertEqual(repeated.json["total"], 1)

    def test_marker_records_api_reports_missing_production_database(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MarkerHistoryStore(
                Path(directory) / "unused.sqlite3",
                require_database_url=True,
            )
            with patch("app.marker_history", store):
                response = self.client.get("/api/marker-records")

        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json["error"])

    def test_marker_records_api_validates_limit(self):
        invalid = self.client.get("/api/marker-records?limit=invalid")

        self.assertEqual(invalid.status_code, 400)
        self.assertIn("integer", invalid.json["error"])

    def test_cloud_camera_page_offers_camera_and_real_marker_routing_guidance(self):
        with (
            patch.dict(app.config, {"CAMERA_ENABLED": False}),
            patch.dict(app.config, {"BROWSER_CAMERA_ENABLED": True}),
            patch("app.camera.stop"),
            patch("app.warehouse.reset"),
            patch("app.state_store.clear"),
        ):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Browser camera", response.data)
        self.assertIn(b'id="browser-camera"', response.data)
        self.assertNotIn(b"Simulate scan", response.data)
        self.assertIn(b"IDs 1", response.data)
        self.assertIn(b"Zone A", response.data)
        self.assertIn(b"Zone B", response.data)
        self.assertIn(b"Zone C", response.data)
        self.assertIn(b'data-camera-mode="browser"', response.data)

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
            history = MarkerHistoryStore(Path(directory) / "history.sqlite3")
            with (
                patch("app.camera.detections", return_value=[{"marker_id": 20}]),
                patch("app.state_store", store),
                patch("app.marker_history", history),
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

    def test_metrics_endpoint_reports_empty_session_values(self):
        with patch("app.warehouse", WarehouseService()):
            response = self.client.get("/api/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["completed_deliveries"], 0)
        self.assertIsNone(response.json["packages_per_minute"])
        self.assertIsNone(response.json["average_delivery_seconds"])
        self.assertTrue(response.json["simulation_only"])

    def test_obstacle_api_records_only_successfully_accepted_reroutes(self):
        test_warehouse = WarehouseService(step_seconds=3600)
        test_warehouse.observe_detections([{"marker_id": 7}])
        original_route = test_warehouse.snapshot()["robots"][0]["route"]
        blocked_cell = original_route[2]

        with (
            patch("app.warehouse", test_warehouse),
            patch("app.state_store.save"),
        ):
            response = self.client.post(
                "/api/warehouse/obstacles",
                json={
                    "blocked_cells": [blocked_cell],
                    "reason": "Controlled reroute test",
                },
            )
            invalid = self.client.post(
                "/api/warehouse/obstacles",
                json={"blocked_cells": [[24, 0]], "reason": "Out of bounds"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["rerouted"])
        self.assertEqual(response.json["warehouse"]["metrics"]["reroutes"], 1)
        self.assertEqual(invalid.status_code, 400)

    def test_camera_start_is_unavailable_in_cloud_demo(self):
        with patch.dict(app.config, {"CAMERA_ENABLED": False}):
            response = self.client.post("/api/camera/start")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json["running"])
        self.assertIn("unavailable", response.json["message"])

    def test_browser_camera_frame_routes_detected_marker_to_its_zone(self):
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100)
        expected_zones = {7: "Zone A", 40: "Zone B", 70: "Zone C"}

        with tempfile.TemporaryDirectory() as directory:
            history = MarkerHistoryStore(Path(directory) / "history.sqlite3")
            for marker_id, expected_zone in expected_zones.items():
                with self.subTest(marker_id=marker_id):
                    marker = cv2.aruco.generateImageMarker(
                        dictionary,
                        marker_id,
                        240,
                        borderBits=1,
                    )
                    frame = np.full((400, 400, 3), 255, dtype=np.uint8)
                    frame[80:320, 80:320] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
                    encoded, jpeg = cv2.imencode(".jpg", frame)
                    self.assertTrue(encoded)
                    detected_warehouse = WarehouseService()

                    with (
                        patch.dict(app.config, {"BROWSER_CAMERA_ENABLED": True}),
                        patch("app.warehouse", detected_warehouse),
                        patch("app.state_store.save"),
                        patch("app.marker_history", history),
                    ):
                        response = self.client.post(
                            "/api/camera/frame",
                            data=jpeg.tobytes(),
                            content_type="image/jpeg",
                        )

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        [detection["marker_id"] for detection in response.json["detections"]],
                        [marker_id],
                    )
                    robot = response.json["warehouse"]["robots"][0]
                    self.assertEqual(robot["marker_id"], marker_id)
                    self.assertEqual(robot["zone_name"], expected_zone)

            self.assertEqual(history.list_records()["total"], 3)

    def test_browser_camera_delivery_continues_when_history_database_is_unavailable(self):
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100)
        marker = cv2.aruco.generateImageMarker(dictionary, 7, 240, borderBits=1)
        frame = np.full((400, 400, 3), 255, dtype=np.uint8)
        frame[80:320, 80:320] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        encoded, jpeg = cv2.imencode(".jpg", frame)
        self.assertTrue(encoded)

        with tempfile.TemporaryDirectory() as directory:
            unavailable_history = MarkerHistoryStore(
                Path(directory) / "unused.sqlite3",
                require_database_url=True,
            )
            with (
                patch.dict(app.config, {"BROWSER_CAMERA_ENABLED": True}),
                patch("app.warehouse", WarehouseService()),
                patch("app.state_store.save"),
                patch("app.marker_history", unavailable_history),
            ):
                response = self.client.post(
                    "/api/camera/frame",
                    data=jpeg.tobytes(),
                    content_type="image/jpeg",
                )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["marker_history_saved"])
        self.assertIn("DATABASE_URL", response.json["marker_history_warning"])
        self.assertEqual(response.json["warehouse"]["robots"][0]["marker_id"], 7)

    def test_browser_camera_frame_rejects_non_jpeg_and_invalid_images(self):
        with patch.dict(app.config, {"BROWSER_CAMERA_ENABLED": True}):
            wrong_type = self.client.post(
                "/api/camera/frame",
                data=b"image",
                content_type="text/plain",
            )
            invalid_image = self.client.post(
                "/api/camera/frame",
                data=b"not an image",
                content_type="image/jpeg",
            )
            invalid_run_id = self.client.post(
                "/api/camera/frame",
                data=b"",
                content_type="image/jpeg",
                headers={"X-Run-ID": "not-a-uuid"},
            )

        self.assertEqual(wrong_type.status_code, 415)
        self.assertEqual(invalid_image.status_code, 400)
        self.assertEqual(invalid_run_id.status_code, 400)

    def test_simulated_scan_endpoint_is_removed(self):
        response = self.client.post("/api/demo/scan", json={"marker_id": 70})

        self.assertEqual(response.status_code, 404)


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
