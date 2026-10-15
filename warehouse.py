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


def _utc_timestamp(value: datetime | None = None) -> str:
    timestamp = value or datetime.now(timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return (
        timestamp.replace(tzinfo=timezone.utc)
        if timestamp.tzinfo is None
        else timestamp.astimezone(timezone.utc)
    )


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

    def as_dict(
        self,
        queue_position: int | None = None,
        step_progress: float = 0.0,
    ) -> dict[str, Any]:
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
            "step_progress": round(step_progress, 3),
            "progress": round(progress, 3),
            "queue_position": queue_position,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "delivered_at": self.delivered_at,
        }


class WarehouseService:
    """Connect newly observed ArUco robot IDs to queued warehouse deliveries."""

    def __init__(self, step_seconds: float = 0.12) -> None:
        self.step_seconds = max(0.02, step_seconds)
        self._lock = threading.RLock()
        self._robots: dict[int, DeliveryRobot] = {}
        self._active_marker_id: int | None = None
        self._next_step_at: float | None = None
        self._visible_marker_ids: set[int] = set()
        self._session_started_at: str | None = None
        self._dynamic_obstacles: set[Point] = set()
        self._reroutes: list[dict[str, Any]] = []

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
            and not isinstance(marker_id, bool)
            and 1 <= marker_id <= 96
        }

        with self._lock:
            self._advance(current_time)
            self._visible_marker_ids = marker_ids
            if marker_ids and self._session_started_at is None:
                self._session_started_at = _utc_timestamp()
            for marker_id in sorted(marker_ids):
                if marker_id in self._robots:
                    continue
                zone = zone_for_marker(marker_id)
                if zone is None:
                    continue
                start = (1, (marker_id - 1) % (WAREHOUSE_HEIGHT - 2) + 1)
                blocked = DEFAULT_OBSTACLES | self._dynamic_obstacles
                route = (
                    None
                    if start in blocked or zone["target"] in blocked
                    else find_path(start, zone["target"], blocked)
                )
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
                step_progress = 0.0
                if (
                    robot.status == "moving"
                    and self._next_step_at is not None
                ):
                    step_progress = min(
                        1.0,
                        max(
                            0.0,
                            1.0
                            - (self._next_step_at - current_time)
                            / self.step_seconds,
                        ),
                    )
                robots.append(robot.as_dict(queue_position, step_progress))

            counts = {
                status: sum(robot.status == status for robot in self._robots.values())
                for status in ("queued", "moving", "delivered", "blocked")
            }
            return {
                "grid": {
                    "width": WAREHOUSE_WIDTH,
                    "height": WAREHOUSE_HEIGHT,
                    "obstacles": [
                        list(point)
                        for point in sorted(DEFAULT_OBSTACLES | self._dynamic_obstacles)
                    ],
                },
                "static_obstacles": [
                    list(point) for point in sorted(DEFAULT_OBSTACLES)
                ],
                "zones": [
                    {
                        **zone,
                        "target": list(zone["target"]),
                    }
                    for zone in ZONE_DEFINITIONS
                ],
                "visible_marker_ids": sorted(self._visible_marker_ids),
                "session_started_at": self._session_started_at,
                "step_seconds": self.step_seconds,
                "dynamic_obstacles": [
                    list(point) for point in sorted(self._dynamic_obstacles)
                ],
                "robots": robots,
                "summary": {
                    "total": len(robots),
                    **counts,
                },
                "metrics": self._metrics(datetime.now(timezone.utc)),
                "reroutes": list(self._reroutes),
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
                started_at=saved_robot.get("started_at"),
                delivered_at=saved_robot.get("delivered_at"),
            )

        visible_marker_ids = set(state.get("visible_marker_ids", []))
        dynamic_obstacles = {
            tuple(point) for point in state.get("dynamic_obstacles", [])
        }
        reroutes = list(state.get("reroutes", []))
        session_started_at = state.get("session_started_at") or min(
            (robot.created_at for robot in robots.values()),
            default=None,
        )
        with self._lock:
            self._robots = robots
            self._visible_marker_ids = visible_marker_ids
            self._dynamic_obstacles = dynamic_obstacles
            self._reroutes = reroutes
            self._session_started_at = session_started_at
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
            self._session_started_at = None
            self._dynamic_obstacles.clear()
            self._reroutes.clear()

    def set_dynamic_obstacles(
        self,
        obstacles: set[Point],
        reason: str,
        now: float | None = None,
    ) -> bool:
        current_time = time.monotonic() if now is None else now
        blocked = set(DEFAULT_OBSTACLES) | obstacles
        with self._lock:
            self._advance(current_time)
            self._dynamic_obstacles = set(obstacles - set(DEFAULT_OBSTACLES))
            if self._active_marker_id is None:
                return False

            robot = self._robots[self._active_marker_id]
            current_position = robot.position
            if current_position is None:
                return False

            remaining_route = robot.route[robot.route_index + 1 :]
            occupied = self._blocked_cells(exclude_marker_id=robot.marker_id)
            blocked |= occupied
            if not any(point in blocked for point in remaining_route):
                return False

            replacement = None
            if current_position not in blocked and robot.zone["target"] not in blocked:
                replacement = find_path(
                    current_position,
                    robot.zone["target"],
                    blocked,
                )

            if replacement is None:
                robot.status = "blocked"
                self._active_marker_id = None
                self._next_step_at = None
                self._dispatch_next(current_time)
                return False

            original_route = robot.route[robot.route_index :]
            self._reroutes.append(
                {
                    "marker_id": robot.marker_id,
                    "timestamp": _utc_timestamp(),
                    "reason": reason,
                    "original_route": [list(point) for point in original_route],
                    "replacement_route": [list(point) for point in replacement],
                }
            )
            robot.route = replacement
            robot.route_index = 0
            self._next_step_at = current_time + self.step_seconds
            return True

    def metrics_snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        with self._lock:
            self._advance(time.monotonic())
            return self._metrics(now or datetime.now(timezone.utc))

    def _metrics(self, now: datetime) -> dict[str, Any]:
        current = now.astimezone(timezone.utc)
        session_started_at = _parse_timestamp(self._session_started_at)
        observation_seconds = (
            max(0.0, (current - session_started_at).total_seconds())
            if session_started_at is not None
            else 0.0
        )
        completed = [
            robot
            for robot in self._robots.values()
            if robot.status == "delivered"
        ]
        evaluated = [
            robot
            for robot in self._robots.values()
            if zone_for_marker(robot.marker_id) is not None
        ]
        mis_sorted = sum(
            robot.zone["id"] != zone_for_marker(robot.marker_id)["id"]
            for robot in evaluated
        )
        delivery_durations = []
        for robot in completed:
            started_at = _parse_timestamp(robot.started_at)
            delivered_at = _parse_timestamp(robot.delivered_at)
            if started_at is None or delivered_at is None:
                continue
            duration = (delivered_at - started_at).total_seconds()
            if duration >= 0:
                delivery_durations.append(duration)

        return {
            "session_started_at": self._session_started_at,
            "observation_seconds": round(observation_seconds, 3),
            "delivery_attempts": len(evaluated),
            "completed_deliveries": len(completed),
            "failed_deliveries": sum(
                robot.status == "blocked" for robot in evaluated
            ),
            "blocked_routes": sum(
                robot.status == "blocked" for robot in evaluated
            ),
            "packages_per_minute": (
                round(len(completed) / (observation_seconds / 60), 3)
                if observation_seconds > 0
                else None
            ),
            "evaluated_assignments": len(evaluated),
            "mis_sorts": mis_sorted,
            "mis_sort_rate_percent": (
                round(mis_sorted / len(evaluated) * 100, 2)
                if evaluated
                else None
            ),
            "reroutes": len(self._reroutes),
            "average_delivery_seconds": (
                round(sum(delivery_durations) / len(delivery_durations), 3)
                if delivery_durations
                else None
            ),
            "simulation_only": True,
        }

    def _dispatch_next(self, now: float) -> None:
        if self._active_marker_id is not None:
            return
        for marker_id, robot in self._robots.items():
            if robot.status != "queued":
                continue
            start = (1, (marker_id - 1) % (WAREHOUSE_HEIGHT - 2) + 1)
            blocked = (
                DEFAULT_OBSTACLES
                | self._dynamic_obstacles
                | self._blocked_cells(exclude_marker_id=marker_id)
            )
            route = (
                None
                if start in blocked or robot.zone["target"] in blocked
                else find_path(start, robot.zone["target"], blocked)
            )
            if route is None:
                robot.status = "blocked"
                robot.route = []
                continue
            robot.route = route
            robot.route_index = 0
            robot.status = "moving"
            robot.started_at = _utc_timestamp()
            self._active_marker_id = marker_id
            self._next_step_at = now + self.step_seconds
            return

    def _blocked_cells(self, exclude_marker_id: int) -> set[Point]:
        return {
            robot.position
            for marker_id, robot in self._robots.items()
            if marker_id != exclude_marker_id
            and robot.status == "blocked"
            and robot.position is not None
        }

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
