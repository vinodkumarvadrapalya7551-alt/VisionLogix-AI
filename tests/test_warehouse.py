import unittest

from pathfinding import DEFAULT_OBSTACLES, find_path
from warehouse import WarehouseService, zone_for_marker


class PathfindingTests(unittest.TestCase):
    def test_finds_shortest_route_around_shelves(self):
        route = find_path((1, 3), (22, 2))

        self.assertIsNotNone(route)
        self.assertEqual(route[0], (1, 3))
        self.assertEqual(route[-1], (22, 2))
        self.assertEqual(len(route), 27)
        self.assertFalse(any(point in DEFAULT_OBSTACLES for point in route))
        self.assertTrue(all(
            abs(left[0] - right[0]) + abs(left[1] - right[1]) == 1
            for left, right in zip(route, route[1:])
        ))

    def test_returns_none_when_goal_is_enclosed(self):
        obstacles = {(1, 0), (1, 2), (0, 1), (2, 1)}

        self.assertIsNone(find_path((0, 0), (1, 1), obstacles, width=3, height=3))

    def test_rejects_out_of_bounds_and_blocked_positions(self):
        with self.assertRaises(ValueError):
            find_path((-1, 0), (2, 2), width=3, height=3)
        with self.assertRaises(ValueError):
            find_path((0, 0), (2, 2), {(0, 0)}, width=3, height=3)


class WarehouseServiceTests(unittest.TestCase):
    def test_marker_id_ranges_select_the_configured_zone(self):
        self.assertEqual(zone_for_marker(1)["id"], "1")
        self.assertEqual(zone_for_marker(32)["id"], "1")
        self.assertEqual(zone_for_marker(33)["id"], "2")
        self.assertEqual(zone_for_marker(64)["id"], "2")
        self.assertEqual(zone_for_marker(65)["id"], "3")
        self.assertEqual(zone_for_marker(96)["id"], "3")
        self.assertIsNone(zone_for_marker(0))
        self.assertIsNone(zone_for_marker(97))

    def test_detection_creates_a_robot_and_advances_its_delivery(self):
        warehouse = WarehouseService(step_seconds=0.1)
        warehouse.observe_detections([{"marker_id": 1}], now=10.0)
        first = warehouse.snapshot(now=10.0)

        self.assertEqual(first["summary"]["moving"], 1)
        robot = first["robots"][0]
        self.assertEqual(robot["robot_id"], 1)
        self.assertEqual(robot["zone_id"], "1")
        self.assertEqual(robot["position"], robot["route"][0])

        warehouse.snapshot(now=10.1)
        moved = warehouse.snapshot(now=10.2)["robots"][0]
        self.assertNotEqual(moved["position"], robot["position"])

        delivered = warehouse.snapshot(now=100.0)
        self.assertEqual(delivered["summary"]["delivered"], 1)
        self.assertEqual(delivered["robots"][0]["status"], "delivered")

    def test_same_marker_does_not_create_duplicate_deliveries(self):
        warehouse = WarehouseService()
        detection = [{"marker_id": 20}]
        warehouse.observe_detections(detection, now=1.0)
        warehouse.observe_detections(detection, now=2.0)

        state = warehouse.snapshot(now=2.0)
        self.assertEqual(state["summary"]["total"], 1)

    def test_multiple_robots_are_queued_to_avoid_route_collisions(self):
        warehouse = WarehouseService()
        warehouse.observe_detections(
            [{"marker_id": 2}, {"marker_id": 18}], now=1.0
        )

        state = warehouse.snapshot(now=1.0)
        self.assertEqual(state["summary"]["moving"], 1)
        self.assertEqual(state["summary"]["queued"], 1)
        self.assertEqual(
            [robot["queue_position"] for robot in state["robots"]],
            [None, 1],
        )

    def test_id_zero_is_not_a_robot_delivery_trigger(self):
        warehouse = WarehouseService()
        warehouse.observe_detections([{"marker_id": 0}], now=1.0)

        state = warehouse.snapshot(now=1.0)
        self.assertEqual(state["summary"]["total"], 0)
        self.assertEqual(state["visible_marker_ids"], [])

    def test_marker_96_triggers_a_zone_3_delivery(self):
        warehouse = WarehouseService()
        warehouse.observe_detections([{"marker_id": 96}], now=1.0)

        robot = warehouse.snapshot(now=1.0)["robots"][0]

        self.assertEqual(robot["marker_id"], 96)
        self.assertEqual(robot["zone_id"], "3")
        self.assertEqual(robot["zone_name"], "Zone C")

    def test_restores_saved_delivery_progress(self):
        original = WarehouseService(step_seconds=0.1)
        original.observe_detections([{"marker_id": 1}], now=10.0)
        original.snapshot(now=10.1)
        saved = original.snapshot(now=10.1)

        restored = WarehouseService(step_seconds=0.1)
        restored.restore(saved)
        restored_state = restored.snapshot()

        self.assertEqual(restored_state["robots"], saved["robots"])
        self.assertEqual(restored_state["visible_marker_ids"], [1])


if __name__ == "__main__":
    unittest.main()
