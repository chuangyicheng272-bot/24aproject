import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
YOLO_ROOT = ROOT / "systems" / "yolo"
sys.path.insert(0, str(YOLO_ROOT))

from backend.safeguard_forwarder import build_safeguard_camera_payload


def load_safeguard_app():
    spec = importlib.util.spec_from_file_location(
        "safeguard_root_app_yolo", ROOT / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class YoloSafeGuardIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_safeguard_app()

    def setUp(self):
        self.database_path = ROOT / ".test-yolo-safeguard.db"
        self.database_path.unlink(missing_ok=True)
        self.module.app.config.update(
            TESTING=True,
            DATABASE=str(self.database_path),
            IOT_API_KEY="integration-test-key",
            LINE_CHANNEL_ACCESS_TOKEN="",
            LINE_TARGET_USER_ID="",
        )
        self.client = self.module.app.test_client()

    def tearDown(self):
        self.database_path.unlink(missing_ok=True)

    def test_ppe_and_fall_event_reach_safeguard(self):
        event = {
            "event_id": "evt-001",
            "worker_id": "worker-001",
            "track_id": 1,
            "camera_id": "CAM-01",
            "zone": "施工區 A",
            "risk_level": "danger",
            "alerts": ["未配戴安全帽", "疑似跌倒"],
            "wall_time": 1789627200.0,
        }
        worker = {
            "worker_id": "worker-001",
            "track_id": 1,
            "confidence": 0.96,
            "ppe": {"helmet": False, "vest": True},
            "behavior": {"fall": True},
        }
        payload = build_safeguard_camera_payload(event, worker)
        response = self.client.post(
            "/api/iot/camera",
            json=payload,
            headers={"X-API-Key": "integration-test-key"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.get_json()["ok"])

        conn = sqlite3.connect(self.database_path)
        try:
            camera = conn.execute(
                "SELECT id,location,status FROM monitoring_devices WHERE id='CAM-01'"
            ).fetchone()
            alerts = conn.execute(
                """
                SELECT alert_type FROM safety_alerts
                WHERE source_system='YOLO' AND device_id='CAM-01'
                ORDER BY alert_type
                """
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(camera, ("CAM-01", "施工區 A", "正常"))
        self.assertEqual(alerts, [("fall_detected",), ("ppe_violation",)])


if __name__ == "__main__":
    unittest.main()
