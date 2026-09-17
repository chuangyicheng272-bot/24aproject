import math
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import app as monitor


class UwbHistoryAndGeofenceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = monitor.DB_PATH
        self.original_window = monitor.HARDWARE_POSITION_WINDOW
        monitor.DB_PATH = Path(self.temp_dir.name) / "test.db"
        monitor.HARDWARE_POSITION_WINDOW = 1
        monitor.range_buffer.clear()
        monitor.position_history.clear()
        monitor.init_db()
        self.client = monitor.app.test_client()

    def tearDown(self):
        monitor.DB_PATH = self.original_db_path
        monitor.HARDWARE_POSITION_WINDOW = self.original_window
        monitor.range_buffer.clear()
        monitor.position_history.clear()
        self.temp_dir.cleanup()

    def send_sequence(self, sequence_id, position):
        responses = []
        with patch.object(monitor, "calculate_position_3d", return_value=position):
            for anchor_id in ("Anchor1", "Anchor2", "Anchor3", "Anchor4"):
                responses.append(
                    self.client.post(
                        "/api/uwb/range",
                        json={
                            "sequence_id": sequence_id,
                            "anchor_id": anchor_id,
                            "timestamp": 1_700_000_000 + sequence_id,
                            "detected_belts": {
                                "BELT-001": {"distance_mm": 2000.0}
                            },
                        },
                    )
                )
        return responses

    def send_geometric_sequence(self, sequence_id, position):
        responses = []
        for anchor in monitor.UWB_ANCHORS.values():
            geometric_distance = math.sqrt(
                (position[0] - anchor["x"]) ** 2
                + (position[1] - anchor["y"]) ** 2
                + (position[2] - anchor["z"]) ** 2
            )
            responses.append(
                self.client.post(
                    "/api/uwb/range",
                    json={
                        "sequence_id": sequence_id,
                        "anchor_id": anchor["id"],
                        "timestamp": 1_700_000_000 + sequence_id,
                        "detected_belts": {
                            "BELT-001": {
                                "distance_mm": geometric_distance
                                + monitor.ANCHOR_DISTANCE_OFFSETS_MM[anchor["id"]]
                            }
                        },
                    },
                )
            )
        return responses

    def test_history_is_written_only_after_four_anchors(self):
        responses = self.send_sequence(100, (1000.0, 1000.0, 1000.0))
        self.assertEqual([item.status_code for item in responses], [202, 202, 202, 200])

        history = self.client.get("/api/history/BELT-001").get_json()
        self.assertEqual(history["count"], 1)
        self.assertEqual(history["records"][0]["sequence_id"], 100)
        self.assertEqual(history["records"][0]["risk_level"], "safe")

    def test_enter_stay_exit_and_duplicate_sequence(self):
        self.send_sequence(200, (1000.0, 1000.0, 1000.0))
        self.send_sequence(201, (2200.0, 600.0, 1000.0))
        self.send_sequence(202, (2300.0, 700.0, 1000.0))
        self.send_sequence(203, (1000.0, 1000.0, 1000.0))
        duplicate = self.send_sequence(203, (1100.0, 1100.0, 1000.0))[-1].get_json()

        history = self.client.get("/api/history/BELT-001?limit=20").get_json()
        events = self.client.get("/api/geofence-events?limit=20").get_json()
        self.assertEqual(history["count"], 4)
        self.assertFalse(duplicate["results"]["BELT-001"]["history_created"])
        self.assertEqual(events["count"], 2)
        self.assertEqual(
            [event["event_type"] for event in events["events"]],
            ["EXIT", "ENTER"],
        )
        self.assertEqual(
            {event["zone_name"] for event in events["events"]},
            {"樓層邊緣 A 區"},
        )

    def test_trilateration_formula_still_returns_known_point(self):
        expected = (1200.0, 900.0, 800.0)
        distances = {}
        for key, anchor in monitor.UWB_ANCHORS.items():
            distances[key] = math.sqrt(
                (expected[0] - anchor["x"]) ** 2
                + (expected[1] - anchor["y"]) ** 2
                + (expected[2] - anchor["z"]) ** 2
            )
        actual = monitor.calculate_position_3d(distances)
        for actual_value, expected_value in zip(actual, expected):
            self.assertAlmostEqual(actual_value, expected_value, places=6)

    def test_geometric_anchor_payload_reaches_history(self):
        expected = (1200.0, 900.0, 800.0)
        responses = self.send_geometric_sequence(300, expected)
        result = responses[-1].get_json()["results"]["BELT-001"]
        self.assertEqual(responses[-1].status_code, 200)
        self.assertEqual(result["status"], "calculated")
        history = self.client.get("/api/history/BELT-001").get_json()["records"]
        for axis, expected_value in zip(("x", "y", "z"), expected):
            self.assertAlmostEqual(history[0][axis], expected_value, places=6)

    def test_history_and_events_support_time_range_queries(self):
        self.send_sequence(400, (1000.0, 1000.0, 1000.0))
        self.send_sequence(401, (2200.0, 600.0, 1000.0))
        self.send_sequence(402, (1000.0, 1000.0, 1000.0))
        with monitor.get_db() as conn:
            conn.execute(
                "UPDATE uwb_logs_v2 SET created_at='2026-08-23T10:00:00' WHERE sequence_id=400"
            )
            conn.execute(
                "UPDATE uwb_logs_v2 SET created_at='2026-08-23T10:01:00' WHERE sequence_id=401"
            )
            conn.execute(
                "UPDATE uwb_logs_v2 SET created_at='2026-08-23T10:02:00' WHERE sequence_id=402"
            )
            conn.execute(
                "UPDATE geofence_events SET created_at='2026-08-23T10:01:00' WHERE sequence_id=401"
            )
            conn.execute(
                "UPDATE geofence_events SET created_at='2026-08-23T10:02:00' WHERE sequence_id=402"
            )

        history = self.client.get(
            "/api/history/BELT-001?start=2026-08-23T10:00:30"
            "&end=2026-08-23T10:01:30&limit=200"
        ).get_json()
        events = self.client.get(
            "/api/geofence-events?belt_id=BELT-001"
            "&start=2026-08-23T10:00:30&end=2026-08-23T10:01:30"
        ).get_json()
        self.assertEqual([record["sequence_id"] for record in history["records"]], [401])
        self.assertEqual([event["event_type"] for event in events["events"]], ["ENTER"])

    def test_history_rejects_invalid_time_range(self):
        invalid = self.client.get("/api/history/BELT-001?start=not-a-date")
        reversed_range = self.client.get(
            "/api/history/BELT-001?start=2026-08-23T11:00"
            "&end=2026-08-23T10:00"
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(reversed_range.status_code, 400)

    def test_event_acknowledgement_and_exit_pairing(self):
        self.send_sequence(500, (1000.0, 1000.0, 1000.0))
        self.send_sequence(501, (2200.0, 600.0, 1000.0))
        entered = self.client.get("/api/geofence-events").get_json()["events"][0]
        self.assertEqual(entered["event_type"], "ENTER")
        self.assertEqual(entered["status"], "UNHANDLED")
        self.assertIsNone(entered["exited_at"])

        acknowledged = self.client.patch(
            f"/api/geofence-events/{entered['id']}",
            json={"status": "ACKNOWLEDGED"},
        )
        self.assertEqual(acknowledged.status_code, 200)
        self.assertEqual(acknowledged.get_json()["event"]["status"], "ACKNOWLEDGED")

        self.send_sequence(502, (1000.0, 1000.0, 1000.0))
        events = self.client.get("/api/geofence-events").get_json()["events"]
        exited, resolved_enter = events[0], events[1]
        self.assertEqual(exited["event_type"], "EXIT")
        self.assertEqual(exited["related_enter_id"], entered["id"])
        self.assertEqual(resolved_enter["status"], "RESOLVED")
        self.assertIsNotNone(resolved_enter["exited_at"])
        self.assertIsNotNone(resolved_enter["duration_seconds"])

    def test_open_event_becomes_critical_after_sixty_seconds(self):
        self.send_sequence(600, (1000.0, 1000.0, 1000.0))
        self.send_sequence(601, (2200.0, 600.0, 1000.0))
        old_time = (datetime.now() - timedelta(seconds=61)).isoformat(timespec="seconds")
        with monitor.get_db() as conn:
            conn.execute(
                "UPDATE geofence_events SET created_at=? WHERE sequence_id=601",
                (old_time,),
            )
        event = self.client.get("/api/geofence-events").get_json()["events"][0]
        self.assertGreaterEqual(event["duration_seconds"], 61)
        self.assertEqual(event["alert_level"], "critical")


if __name__ == "__main__":
    unittest.main()
