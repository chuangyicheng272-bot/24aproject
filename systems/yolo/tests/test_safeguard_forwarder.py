import os
import unittest
from unittest.mock import Mock, patch

from backend.safeguard_forwarder import (
    SafeGuardAlertForwarder,
    build_safeguard_camera_payload,
    post_safeguard_camera_payload,
)


EVENT = {
    "event_id": "evt-001",
    "worker_id": "worker-001",
    "track_id": 1,
    "camera_id": "CAM-01",
    "zone": "施工區 A",
    "risk_level": "danger",
    "alerts": ["未配戴安全帽", "疑似跌倒"],
    "wall_time": 1789627200.0,
}
WORKER = {
    "worker_id": "worker-001",
    "track_id": 1,
    "camera_id": "CAM-01",
    "zone": "施工區 A",
    "confidence": 0.96,
    "ppe": {"helmet": False, "vest": True},
    "behavior": {"fall": True, "status": "疑似跌倒"},
}


class SafeGuardForwarderTests(unittest.TestCase):
    def test_build_payload_separates_ppe_and_fall_alerts(self):
        payload = build_safeguard_camera_payload(EVENT, WORKER)
        self.assertEqual(payload["camera_id"], "CAM-01")
        self.assertEqual(payload["location"], "施工區 A")
        self.assertEqual(len(payload["detections"]), 2)
        self.assertFalse(payload["detections"][0]["helmet"])
        fall = payload["detections"][1]
        self.assertEqual(fall["alert_type"], "fall_detected")
        self.assertEqual(fall["severity"], "emergency")

    @patch("backend.safeguard_forwarder.requests.post")
    def test_post_uses_camera_endpoint_and_api_key(self, mock_post):
        response = Mock(status_code=201)
        response.json.return_value = {"ok": True}
        mock_post.return_value = response
        payload = build_safeguard_camera_payload(EVENT, WORKER)
        with patch.dict(
            os.environ,
            {
                "SAFEGUARD_BASE_URL": "http://127.0.0.1:5000",
                "SAFEGUARD_IOT_API_KEY": "test-key",
            },
            clear=False,
        ):
            result = post_safeguard_camera_payload(payload)
        self.assertEqual(result["status"], "success")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:5000/api/iot/camera")
        self.assertEqual(kwargs["headers"], {"X-API-Key": "test-key"})

    def test_dispatch_can_be_disabled(self):
        with patch.dict(
            os.environ, {"SAFEGUARD_FORWARD_ENABLED": "false"}, clear=False
        ):
            result = SafeGuardAlertForwarder().dispatch(EVENT, WORKER)
        self.assertEqual(result["status"], "disabled")


if __name__ == "__main__":
    unittest.main()
