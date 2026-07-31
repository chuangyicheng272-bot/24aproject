import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.anchor_api import (
    AnchorRangesPayload,
    anchor_report_history,
    latest_anchor_reports,
    latest_belt_ranges,
    receive_anchor_ranges,
)
from app.belt_api import (
    BeltStatusPayload,
    belt_statuses,
    get_belt_status,
    receive_belt_status,
)
from app.main import app


def anchor_payload(anchor_id="Anchor1", sequence_id=1024):
    return {
        "sequence_id": sequence_id,
        "anchor_id": anchor_id,
        "timestamp": 1781943343,
        "detected_belts": {
            "BELT-001": {"distance_mm": 1820},
            "BELT-002": {"distance_mm": 452},
        },
    }


class DeviceApiTests(unittest.TestCase):
    def setUp(self):
        latest_anchor_reports.clear()
        anchor_report_history.clear()
        latest_belt_ranges.clear()
        belt_statuses.clear()

    def test_routes_are_registered(self):
        paths = set(app.openapi()["paths"])
        self.assertIn("/api/anchor/ranges", paths)
        self.assertIn("/api/belt/status", paths)
        self.assertIn("/api/belt/{belt_id}/status", paths)

    @patch("app.anchor_api.post_to_flask", return_value=(200, None))
    def test_anchor_accepts_two_belts_and_forwards_each_one(self, mock_forward):
        response = receive_anchor_ranges(AnchorRangesPayload(**anchor_payload()))
        self.assertEqual(response["status"], "success")
        self.assertEqual(mock_forward.call_count, 2)
        forwarded = [call.args[0] for call in mock_forward.call_args_list]
        self.assertEqual(
            {item["belt_id"] for item in forwarded}, {"BELT-001", "BELT-002"}
        )
        self.assertTrue(all(item["sequence_id"] == 1024 for item in forwarded))
        self.assertIn("Anchor1:1024", latest_anchor_reports)
        self.assertIn("BELT-001:1024:Anchor1", latest_belt_ranges)

    @patch("app.anchor_api.post_to_flask", return_value=(200, None))
    def test_four_anchors_share_source_sequence_id(self, mock_forward):
        for number in range(1, 5):
            receive_anchor_ranges(
                AnchorRangesPayload(**anchor_payload(f"Anchor{number}", 2048))
            )
        self.assertEqual(
            {report["sequence_id"] for report in anchor_report_history}, {2048}
        )

    def test_anchor_rejects_invalid_anchor_and_distances(self):
        invalid_cases = [
            {"anchor_id": "Anchor5"},
            {"detected_belts": {"BELT-001": {"distance_mm": -1}}},
            {"detected_belts": {"BELT-001": {"distance_mm": 4501}}},
        ]
        for changes in invalid_cases:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                AnchorRangesPayload(**(anchor_payload() | changes))

    def test_anchor_rejects_removed_fields(self):
        for field, value in (("sample_id", 7), ("battery", 85), ("vest", True)):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                AnchorRangesPayload(**(anchor_payload() | {field: value}))

    def test_low_battery_alert(self):
        response = receive_belt_status(
            BeltStatusPayload(
                belt_id="BELT-001",
                timestamp=1781943343,
                battery=19,
                charging=False,
            )
        )
        self.assertEqual(
            response["data"]["alerts"],
            [{"code": "battery_low", "message": "腰帶電量過低"}],
        )

    def test_belt_is_offline_after_timeout(self):
        old_time = datetime.now(timezone.utc) - timedelta(seconds=11)
        belt_statuses["BELT-001"] = {
            "belt_id": "BELT-001",
            "battery": 85,
            "charging": False,
            "device_timestamp": 1781943343,
            "last_seen": old_time,
            "server_received_at": old_time,
        }
        response = get_belt_status("BELT-001")
        self.assertFalse(response["online"])
        self.assertEqual(
            response["alerts"],
            [{"code": "belt_offline", "message": "腰帶裝置離線"}],
        )

    def test_belt_status_rejects_distance(self):
        with self.assertRaises(ValidationError):
            BeltStatusPayload(
                belt_id="BELT-001",
                timestamp=1781943343,
                battery=85,
                charging=False,
                distance_mm=1000,
            )

    def test_device_judgment_has_only_device_rules(self):
        source = (
            Path(__file__).parents[1] / "app" / "device_judgment.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("YOLO", source)
        self.assertNotIn("safety_belt", source)
        self.assertNotIn("vest", source)


if __name__ == "__main__":
    unittest.main()
