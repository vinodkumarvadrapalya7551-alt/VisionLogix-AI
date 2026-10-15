from __future__ import annotations

import platform
import threading
import time
from typing import Any

import cv2

from visionlogix.detector import MarkerDetector


def open_camera(camera_index: int) -> tuple[cv2.VideoCapture | None, str]:
    if platform.system() == "Windows":
        capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if capture.isOpened():
            return capture, "DirectShow"
        capture.release()

    capture = cv2.VideoCapture(camera_index)
    if capture.isOpened():
        return capture, "default"
    capture.release()
    return None, "default"


class CameraService:
    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self.detector = MarkerDetector()
        self._lock = threading.Lock()
        self._frame_changed = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._startup_event = threading.Event()
        self._capture: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._jpeg: bytes | None = None
        self._frame_id = 0
        self._detections: list[dict[str, Any]] = []
        self._status: dict[str, Any] = {
            "running": False,
            "message": "Camera is not connected.",
            "camera_index": camera_index,
            "fps": 0.0,
            "frame_width": 0,
            "frame_height": 0,
            "marker_count": 0,
        }

    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._status["running"]:
                    return True, "Camera is already running."
                return False, str(self._status["message"])

            self._stop_event.clear()
            self._startup_event.clear()
            self._jpeg = None
            self._frame_id = 0
            self._detections = []
            self._status.update(
                running=False,
                starting=True,
                message="Opening camera and waiting for the first frame.",
                fps=0.0,
                frame_width=0,
                frame_height=0,
                marker_count=0,
            )
            self._thread = threading.Thread(
                target=self._read_frames,
                name="visionlogix-camera",
                daemon=True,
            )
            self._thread.start()

        if not self._startup_event.wait(timeout=8):
            self._stop_event.set()
            with self._lock:
                self._status.update(
                    running=False,
                    starting=False,
                    message="Camera did not produce a frame within 8 seconds. Check camera access and try again.",
                )
                self._frame_changed.notify_all()
                return False, str(self._status["message"])

        with self._lock:
            running = bool(self._status["running"])
            return running, str(self._status["message"])

    def stop(self) -> None:
        self._stop_event.set()
        with self._frame_changed:
            self._frame_changed.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        with self._lock:
            self._jpeg = None
            self._detections = []
            self._status.update(
                running=False,
                starting=False,
                message="Camera stopped.",
                fps=0.0,
                marker_count=0,
            )
            self._frame_changed.notify_all()
            if thread is None or not thread.is_alive():
                self._thread = None

    def _read_frames(self) -> None:
        failed_reads = 0
        frame_count = 0
        interval_start = time.monotonic()
        fps = 0.0
        capture: cv2.VideoCapture | None = None
        try:
            capture, backend = open_camera(self.camera_index)
            if capture is None:
                with self._lock:
                    message = (
                        f"Could not open camera {self.camera_index}. Check that it is "
                        "connected, not in use by another app, and allowed in system settings."
                    )
                    self._status.update(running=False, message=message)
                    self._startup_event.set()
                return

            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            capture.set(cv2.CAP_PROP_FPS, 30)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            with self._lock:
                self._capture = capture
                self._status["message"] = f"Camera opened with {backend}; waiting for frames."

            while not self._stop_event.is_set():
                success, frame = capture.read()
                if not success:
                    failed_reads += 1
                    if failed_reads >= 10:
                        with self._lock:
                            self._status.update(
                                running=False,
                                starting=False,
                                message="Camera stopped delivering frames. Check the connection and try again.",
                            )
                            self._startup_event.set()
                            self._frame_changed.notify_all()
                        break
                    self._stop_event.wait(0.05)
                    continue

                failed_reads = 0
                detections, annotated = self.detector.detect(frame)
                encoded_ok, encoded = cv2.imencode(
                    ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 82]
                )
                if not encoded_ok:
                    with self._lock:
                        self._status.update(
                            running=False,
                            starting=False,
                            message="OpenCV could not encode a camera frame.",
                        )
                        self._startup_event.set()
                        self._frame_changed.notify_all()
                    break

                frame_count += 1
                now = time.monotonic()
                elapsed = now - interval_start
                if elapsed >= 1:
                    fps = frame_count / elapsed
                    frame_count = 0
                    interval_start = now

                with self._frame_changed:
                    if self._stop_event.is_set():
                        break
                    self._jpeg = encoded.tobytes()
                    self._frame_id += 1
                    self._detections = [detection.as_dict() for detection in detections]
                    self._status.update(
                        running=True,
                        starting=False,
                        message=f"Camera connected using {backend}. Looking for ArUco markers.",
                        fps=round(fps, 1),
                        frame_width=int(frame.shape[1]),
                        frame_height=int(frame.shape[0]),
                        marker_count=len(detections),
                    )
                    self._startup_event.set()
                    self._frame_changed.notify_all()
        finally:
            if capture is not None:
                capture.release()
            with self._frame_changed:
                self._capture = None
                if self._status["running"] and self._stop_event.is_set():
                    self._status.update(running=False, starting=False, message="Camera stopped.")
                elif self._status["running"]:
                    self._status.update(running=False, starting=False, message="Camera feed ended.")
                else:
                    self._status["starting"] = False
                self._startup_event.set()
                self._frame_changed.notify_all()

    def status(self) -> dict[str, Any]:
        with self._lock:
            status = self._status.copy()
            status["detections"] = [detection.copy() for detection in self._detections]
            return status

    def detections(self) -> list[dict[str, Any]]:
        with self._lock:
            return [detection.copy() for detection in self._detections]

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def wait_for_frame(
        self,
        after_frame_id: int,
        timeout: float = 2.0,
    ) -> tuple[int, bytes | None, bool]:
        with self._frame_changed:
            self._frame_changed.wait_for(
                lambda: self._frame_id > after_frame_id or not self._status["running"],
                timeout=timeout,
            )
            return self._frame_id, self._jpeg, bool(self._status["running"])
