import unittest
from datetime import datetime, timezone

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
    def test_default_robot_movement_step_is_responsive(self):
        warehouse = WarehouseService()

        self.assertEqual(warehouse.step_seconds, 0.12)

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
        self.assertEqual(state["metrics"]["delivery_attempts"], 1)

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

    def test_metrics_handle_empty_session_without_inventing_zero_rate(self):
        metrics = WarehouseService().metrics_snapshot()

        self.assertIsNone(metrics["session_started_at"])
        self.assertEqual(metrics["completed_deliveries"], 0)
        self.assertIsNone(metrics["packages_per_minute"])
        self.assertEqual(metrics["mis_sorts"], 0)
        self.assertIsNone(metrics["mis_sort_rate_percent"])
        self.assertEqual(metrics["reroutes"], 0)
        self.assertIsNone(metrics["average_delivery_seconds"])

    def test_metrics_leave_throughput_undefined_at_zero_elapsed_time(self):
        warehouse = WarehouseService()
        warehouse.observe_detections([{"marker_id": 7}], now=10.0)
        started_at = datetime.fromisoformat(warehouse._session_started_at)

        metrics = warehouse.metrics_snapshot(started_at)

        self.assertEqual(metrics["observation_seconds"], 0)
        self.assertIsNone(metrics["packages_per_minute"])
        self.assertEqual(metrics["delivery_attempts"], 1)

    def test_metrics_calculate_throughput_duration_and_mis_sorts(self):
        warehouse = WarehouseService()
        warehouse.observe_detections([{"marker_id": 7}], now=10.0)
        robot = warehouse._robots[7]
        warehouse._active_marker_id = None
        warehouse._next_step_at = None
        robot.status = "delivered"
        robot.started_at = "2026-01-01T00:00:05+00:00"
        robot.delivered_at = "2026-01-01T00:00:08.500000+00:00"
        robot.zone = zone_for_marker(40)
        warehouse._session_started_at = "2026-01-01T00:00:00+00:00"

        metrics = warehouse.metrics_snapshot(
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
        )

        self.assertEqual(metrics["completed_deliveries"], 1)
        self.assertEqual(metrics["delivery_attempts"], 1)
        self.assertEqual(metrics["failed_deliveries"], 0)
        self.assertEqual(metrics["packages_per_minute"], 1.0)
        self.assertEqual(metrics["evaluated_assignments"], 1)
        self.assertEqual(metrics["mis_sorts"], 1)
        self.assertEqual(metrics["mis_sort_rate_percent"], 100.0)
        self.assertEqual(metrics["average_delivery_seconds"], 3.5)
        self.assertTrue(metrics["simulation_only"])

    def test_successful_reroute_records_both_routes_and_reason(self):
        warehouse = WarehouseService(step_seconds=0.1)
        warehouse.observe_detections([{"marker_id": 7}], now=10.0)
        robot_before = warehouse.snapshot(now=10.0)["robots"][0]
        blocked_cell = tuple(robot_before["route"][2])

        rerouted = warehouse.set_dynamic_obstacles(
            {blocked_cell},
            "Temporary aisle obstruction",
            now=10.01,
        )
        state = warehouse.snapshot(now=10.01)
        robot_after = state["robots"][0]

        self.assertTrue(rerouted)
        self.assertEqual(state["metrics"]["reroutes"], 1)
        self.assertEqual(state["reroutes"][0]["reason"], "Temporary aisle obstruction")
        self.assertEqual(
            state["reroutes"][0]["original_route"],
            robot_before["route"][robot_before["route_index"] :],
        )
        self.assertEqual(state["reroutes"][0]["replacement_route"], robot_after["route"])
        self.assertNotEqual(robot_before["route"], robot_after["route"])
        self.assertFalse(any(blocked_cell == tuple(point) for point in robot_after["route"]))
        self.assertEqual(robot_after["position"], robot_before["position"])

    def test_failed_reroute_blocks_robot_without_incrementing_metric(self):
        warehouse = WarehouseService(step_seconds=0.1)
        warehouse.observe_detections([{"marker_id": 1}], now=10.0)

        rerouted = warehouse.set_dynamic_obstacles(
            {(0, 1), (2, 1), (1, 0), (1, 2)},
            "All exits blocked",
            now=10.01,
        )
        state = warehouse.snapshot(now=10.01)

        self.assertFalse(rerouted)
        self.assertEqual(state["robots"][0]["status"], "blocked")
        self.assertEqual(state["metrics"]["reroutes"], 0)
        self.assertEqual(state["metrics"]["failed_deliveries"], 1)
        self.assertEqual(state["metrics"]["blocked_routes"], 1)

    def test_backend_exposes_continuous_progress_only_on_one_route_segment(self):
        warehouse = WarehouseService(step_seconds=1.0)
        warehouse.observe_detections([{"marker_id": 7}], now=10.0)

        state = warehouse.snapshot(now=10.5)
        robot = state["robots"][0]
        start = robot["route"][robot["route_index"]]
        end = robot["route"][robot["route_index"] + 1]

        self.assertAlmostEqual(robot["step_progress"], 0.5)
        self.assertEqual(
            abs(end[0] - start[0]) + abs(end[1] - start[1]),
            1,
        )
        self.assertEqual(state["step_seconds"], 1.0)

    def test_queued_robot_dispatches_after_active_delivery_completes(self):
        warehouse = WarehouseService(step_seconds=0.1)
        warehouse.observe_detections(
            [{"marker_id": 1}, {"marker_id": 40}],
            now=10.0,
        )

        first_state = warehouse.snapshot(now=10.0)
        self.assertEqual(first_state["summary"]["moving"], 1)
        self.assertEqual(first_state["summary"]["queued"], 1)

        next_state = warehouse.snapshot(now=100.0)

        self.assertEqual(next_state["summary"]["delivered"], 1)
        self.assertEqual(next_state["summary"]["moving"], 1)
        self.assertEqual(next_state["summary"]["queued"], 0)
        self.assertEqual(next_state["robots"][1]["status"], "moving")

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
