from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pathfinding import (
    DEFAULT_OBSTACLES,
    Point,
    WAREHOUSE_HEIGHT,
    WAREHOUSE_WIDTH,
    find_path,
)


ZONE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "1",
        "name": "Zone A",
        "first_marker_id": 1,
        "last_marker_id": 32,
        "target": (22, 2),
        "color": "#55b98a",
    },
    {
        "id": "2",
        "name": "Zone B",
        "first_marker_id": 33,
        "last_marker_id": 64,
        "target": (22, 7),
        "color": "#5d9bd1",
    },
    {
        "id": "3",
        "name": "Zone C",
        "first_marker_id": 65,
        "last_marker_id": 96,
        "target": (22, 12),
        "color": "#d65353",
    },
)


def zone_for_marker(marker_id: int) -> dict[str, Any] | None:
    for zone in ZONE_DEFINITIONS:
        if zone["first_marker_id"] <= marker_id <= zone["last_marker_id"]:
            return zone
    return None


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class DeliveryRobot:
    marker_id: int
    zone: dict[str, Any]
    route: list[Point]
    status: str = "queued"
    route_index: int = 0
    created_at: str = field(default_factory=_utc_timestamp)
    started_at: str | None = None
    delivered_at: str | None = None

    @property
    def position(self) -> Point | None:
        if not self.route:
            return None
        return self.route[self.route_index]

    def as_dict(self, queue_position: int | None = None) -> dict[str, Any]:
        if self.status == "delivered":
            progress = 1.0
        elif len(self.route) > 1:
            progress = self.route_index / (len(self.route) - 1)
        else:
            progress = 0.0

        return {
            "robot_id": self.marker_id,
            "marker_id": self.marker_id,
            "zone_id": self.zone["id"],
            "zone_name": self.zone["name"],
            "status": self.status,
            "position": list(self.position) if self.position is not None else None,
            "destination": list(self.zone["target"]),
            "route": [list(point) for point in self.route],
            "route_index": self.route_index,
            "progress": round(progress, 3),
            "queue_position": queue_position,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "delivered_at": self.delivered_at,
        }


class WarehouseService:
    """Connect newly observed ArUco robot IDs to queued warehouse deliveries."""

    def __init__(self, step_seconds: float = 0.35) -> None:
        self.step_seconds = max(0.02, step_seconds)
        self._lock = threading.RLock()
        self._robots: dict[int, DeliveryRobot] = {}
        self._active_marker_id: int | None = None
        self._next_step_at: float | None = None
        self._visible_marker_ids: set[int] = set()

    def observe_detections(
        self,
        detections: list[dict[str, Any]],
        now: float | None = None,
    ) -> None:
        current_time = time.monotonic() if now is None else now
        marker_ids = {
            marker_id
            for detection in detections
            if isinstance(detection, dict)
            and isinstance((marker_id := detection.get("marker_id")), int)
            and 1 <= marker_id <= 96
        }

        with self._lock:
            self._advance(current_time)
            self._visible_marker_ids = marker_ids
            for marker_id in sorted(marker_ids):
                if marker_id in self._robots:
                    continue
                zone = zone_for_marker(marker_id)
                if zone is None:
                    continue
                start = (1, (marker_id - 1) % (WAREHOUSE_HEIGHT - 2) + 1)
                route = find_path(start, zone["target"])
                if route is None:
                    robot = DeliveryRobot(marker_id, zone, [], status="blocked")
                else:
                    robot = DeliveryRobot(marker_id, zone, route)
                self._robots[marker_id] = robot

            self._dispatch_next(current_time)

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            self._advance(current_time)
            queued_ids = [
                marker_id
                for marker_id, robot in self._robots.items()
                if robot.status == "queued"
            ]
            robots = []
            for marker_id, robot in self._robots.items():
                queue_position = (
                    queued_ids.index(marker_id) + 1
                    if marker_id in queued_ids
                    else None
                )
                robots.append(robot.as_dict(queue_position))

            counts = {
                status: sum(robot.status == status for robot in self._robots.values())
                for status in ("queued", "moving", "delivered", "blocked")
            }
            return {
                "grid": {
                    "width": WAREHOUSE_WIDTH,
                    "height": WAREHOUSE_HEIGHT,
                    "obstacles": [list(point) for point in sorted(DEFAULT_OBSTACLES)],
                },
                "zones": [
                    {
                        **zone,
                        "target": list(zone["target"]),
                    }
                    for zone in ZONE_DEFINITIONS
                ],
                "visible_marker_ids": sorted(self._visible_marker_ids),
                "robots": robots,
                "summary": {
                    "total": len(robots),
                    **counts,
                },
                "message": self._status_message(counts),
            }

    def restore(self, state: dict[str, Any]) -> None:
        robots: dict[int, DeliveryRobot] = {}
        active_marker_id: int | None = None
        for saved_robot in state["robots"]:
            marker_id = saved_robot["marker_id"]
            zone = zone_for_marker(marker_id)
            if zone is None:
                raise ValueError(f"Unsupported saved robot marker ID: {marker_id}")
            route = [tuple(point) for point in saved_robot["route"]]
            route_index = saved_robot["route_index"]
            status = saved_robot["status"]
            if status not in {"queued", "moving", "delivered", "blocked"}:
                raise ValueError(f"Unsupported saved robot status: {status}")
            if route and not 0 <= route_index < len(route):
                raise ValueError(f"Invalid saved route index for robot {marker_id}")
            if status == "moving":
                if active_marker_id is not None:
                    raise ValueError("Saved warehouse state has multiple moving robots.")
                active_marker_id = marker_id
            robots[marker_id] = DeliveryRobot(
                marker_id=marker_id,
                zone=zone,
                route=route,
                status=status,
                route_index=route_index,
                created_at=saved_robot["created_at"],
                started_at=saved_robot["started_at"],
                delivered_at=saved_robot["delivered_at"],
            )

        visible_marker_ids = set(state["visible_marker_ids"])
        with self._lock:
            self._robots = robots
            self._visible_marker_ids = visible_marker_ids
            self._active_marker_id = active_marker_id
            self._next_step_at = (
                time.monotonic() + self.step_seconds
                if active_marker_id is not None
                else None
            )

    def reset(self) -> None:
        with self._lock:
            self._robots.clear()
            self._visible_marker_ids.clear()
            self._active_marker_id = None
            self._next_step_at = None

    def _dispatch_next(self, now: float) -> None:
        if self._active_marker_id is not None:
            return
        for marker_id, robot in self._robots.items():
            if robot.status != "queued":
                continue
            robot.status = "moving"
            robot.started_at = _utc_timestamp()
            self._active_marker_id = marker_id
            self._next_step_at = now + self.step_seconds
            return

    def _advance(self, now: float) -> None:
        self._dispatch_next(now)
        while (
            self._active_marker_id is not None
            and self._next_step_at is not None
            and now >= self._next_step_at
        ):
            robot = self._robots[self._active_marker_id]
            if robot.route_index < len(robot.route) - 1:
                robot.route_index += 1
            if robot.route_index >= len(robot.route) - 1:
                robot.status = "delivered"
                robot.delivered_at = _utc_timestamp()
                self._active_marker_id = None
                self._next_step_at = None
                self._dispatch_next(now)
            else:
                self._next_step_at += self.step_seconds

    @staticmethod
    def _status_message(counts: dict[str, int]) -> str:
        if counts["moving"]:
            return "Robot is following its planned aisle-safe route."
        if counts["queued"]:
            return "Deliveries are queued for the shared warehouse aisle."
        if counts["delivered"]:
            return "All detected robots have completed their deliveries."
        return "Waiting for a robot marker (IDs 1–96)."
