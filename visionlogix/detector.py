from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np


DICTIONARY_ID = cv2.aruco.DICT_4X4_100
MAX_MARKER_ID = 96
MARKER_COUNT = MAX_MARKER_ID + 1


@dataclass(frozen=True)
class MarkerDetection:
    marker_id: int
    center_x: int
    center_y: int
    side_pixels: float
    area_pixels: float
    corners: tuple[tuple[int, int], ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class MarkerDetector:
    """Detect and identify printable 4x4 ArUco markers."""

    def __init__(self) -> None:
        self.dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARY_ID)
        parameters = cv2.aruco.DetectorParameters()
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.detector = cv2.aruco.ArucoDetector(self.dictionary, parameters)

    def detect(self, frame: np.ndarray) -> tuple[list[MarkerDetection], np.ndarray]:
        annotated = frame.copy()
        marker_corners, marker_ids, _ = self.detector.detectMarkers(frame)
        if marker_ids is None:
            return [], annotated

        cv2.aruco.drawDetectedMarkers(annotated, marker_corners, marker_ids)
        detections: list[MarkerDetection] = []
        for corners_array, marker_id_array in zip(marker_corners, marker_ids):
            points = corners_array.reshape(4, 2)
            center = points.mean(axis=0)
            edges = np.roll(points, -1, axis=0) - points
            side_pixels = float(np.linalg.norm(edges, axis=1).mean())
            x = points[:, 0]
            y = points[:, 1]
            area_pixels = float(
                abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2
            )
            detection = MarkerDetection(
                marker_id=int(marker_id_array[0]),
                center_x=round(float(center[0])),
                center_y=round(float(center[1])),
                side_pixels=round(side_pixels, 1),
                area_pixels=round(area_pixels, 1),
                corners=tuple((round(float(px)), round(float(py))) for px, py in points),
            )
            detections.append(detection)
            cv2.putText(
                annotated,
                f"ID {detection.marker_id} ({detection.side_pixels:.0f}px)",
                (detection.center_x - 50, detection.center_y - 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (40, 220, 90),
                2,
                cv2.LINE_AA,
            )

        detections.sort(key=lambda item: item.marker_id)
        return detections, annotated


def create_marker_png(marker_id: int, pixels: int = 600) -> bytes:
    if not 0 <= marker_id < MARKER_COUNT:
        raise ValueError(f"Marker ID must be between 0 and {MARKER_COUNT - 1}.")

    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARY_ID)
    marker = cv2.aruco.generateImageMarker(dictionary, marker_id, pixels, borderBits=1)
    success, encoded = cv2.imencode(".png", marker)
    if not success:
        raise RuntimeError("OpenCV could not encode the marker image.")
    return encoded.tobytes()
