from __future__ import annotations

from heapq import heappop, heappush
from itertools import count
from typing import Iterable


Point = tuple[int, int]
WAREHOUSE_WIDTH = 24
WAREHOUSE_HEIGHT = 16

DEFAULT_OBSTACLES: frozenset[Point] = frozenset(
    (x, y)
    for start_x in (6, 13)
    for start_y in (1, 6, 11)
    for x in range(start_x, start_x + 4)
    for y in range(start_y, start_y + 4)
)


def find_path(
    start: Point,
    goal: Point,
    obstacles: Iterable[Point] = DEFAULT_OBSTACLES,
    width: int = WAREHOUSE_WIDTH,
    height: int = WAREHOUSE_HEIGHT,
) -> list[Point] | None:
    """Return the shortest four-directional A* route, including both endpoints."""
    blocked = set(obstacles)
    for point, label in ((start, "start"), (goal, "goal")):
        x, y = point
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"{label} position is outside the warehouse grid.")
        if point in blocked:
            raise ValueError(f"{label} position is blocked by an obstacle.")

    if start == goal:
        return [start]

    frontier: list[tuple[int, int, Point]] = []
    sequence = count()
    heappush(frontier, (_heuristic(start, goal), next(sequence), start))
    came_from: dict[Point, Point] = {}
    cost_so_far = {start: 0}

    while frontier:
        _, _, current = heappop(frontier)
        if current == goal:
            return _reconstruct_path(came_from, start, goal)

        for neighbor in _neighbors(current, width, height):
            if neighbor in blocked:
                continue
            new_cost = cost_so_far[current] + 1
            if new_cost >= cost_so_far.get(neighbor, width * height + 1):
                continue
            cost_so_far[neighbor] = new_cost
            came_from[neighbor] = current
            priority = new_cost + _heuristic(neighbor, goal)
            heappush(frontier, (priority, next(sequence), neighbor))

    return None


def _neighbors(point: Point, width: int, height: int) -> tuple[Point, ...]:
    x, y = point
    return tuple(
        candidate
        for candidate in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
        if 0 <= candidate[0] < width and 0 <= candidate[1] < height
    )


def _heuristic(start: Point, goal: Point) -> int:
    return abs(start[0] - goal[0]) + abs(start[1] - goal[1])


def _reconstruct_path(
    came_from: dict[Point, Point],
    start: Point,
    goal: Point,
) -> list[Point]:
    path = [goal]
    while path[-1] != start:
        path.append(came_from[path[-1]])
    path.reverse()
    return path
