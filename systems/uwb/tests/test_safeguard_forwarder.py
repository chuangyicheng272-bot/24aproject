import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safeguard_forwarder import build_safeguard_payload, forward_uwb_position


BELT = {
    "belt_id": "BELT-001",
    "device_name": "智慧安全腰帶 1",
    "battery": 85,
    "online": True,
}
POSITION = {"x": 2200.0, "y": 600.0, "z": 1000.0}
SAFE_ASSESSMENT = {"zone": None, "zone_risk": None, "level": "正常"}
DANGER_ASSESSMENT = {
    "zone": {"id": "edge-a", "name": "樓層邊緣 A 區", "risk": "high"},
    "zone_risk": "high",
    "level": "注意",
}


class SafeGuardForwarderTests(unittest.TestCase):
    def test_safe_position_payload_does_not_create_danger(self):
        payload = build_safeguard_payload(
            BELT, POSITION, SAFE_ASSESSMENT, "2026-09-17T12:00:00+08:00"
        )
        self.assertEqual(payload["device_id"], "BELT-001")
        self.assertEqual(payload["risk"], "低風險")
        self.assertTrue(payload["inside_safe_zone"])
        self.assertNotIn("danger", payload)

    def test_danger_zone_payload_creates_geofence_alert(self):
        payload = build_safeguard_payload(
            BELT, POSITION, DANGER_ASSESSMENT, "2026-09-17T12:00:00+08:00"
        )
        self.assertEqual(payload["risk"], "中高風險")
        self.assertFalse(payload["inside_safe_zone"])
        self.assertTrue(payload["danger"])
        self.assertEqual(payload["alert_type"], "geofence_intrusion")
        self.assertIn("樓層邊緣 A 區", payload["alert_message"])

    @patch("safeguard_forwarder.requests.post")
    def test_forward_uses_safe_guard_endpoint_and_api_key(self, mock_post):
        response = Mock(status_code=201)
        response.json.return_value = {"ok": True}
        mock_post.return_value = response
        with patch.dict(
            os.environ,
            {
                "SAFEGUARD_BASE_URL": "http://127.0.0.1:5000",
                "SAFEGUARD_IOT_API_KEY": "test-key",
                "SAFEGUARD_FORWARD_ENABLED": "true",
            },
            clear=False,
        ):
            result = forward_uwb_position(BELT, POSITION, SAFE_ASSESSMENT)
        self.assertEqual(result["status"], "success")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:5000/api/iot/uwb")
        self.assertEqual(kwargs["headers"], {"X-API-Key": "test-key"})

    @patch(
        "safeguard_forwarder.requests.post",
        side_effect=requests.ConnectionError("connection refused"),
    )
    def test_forward_failure_does_not_raise(self, _mock_post):
        with patch.dict(os.environ, {"SAFEGUARD_FORWARD_ENABLED": "true"}, clear=False):
            result = forward_uwb_position(BELT, POSITION, SAFE_ASSESSMENT)
        self.assertEqual(result["status"], "failed")
        self.assertIn("connection refused", result["error"])


if __name__ == "__main__":
    unittest.main()
