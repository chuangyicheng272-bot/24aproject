import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UWB_ROOT = ROOT / "systems" / "uwb"
sys.path.insert(0, str(UWB_ROOT))

from safeguard_forwarder import build_safeguard_payload


def load_safeguard_app():
    spec = importlib.util.spec_from_file_location(
        "safeguard_root_app", ROOT / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UwbSafeGuardIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_safeguard_app()

    def setUp(self):
        self.database_path = ROOT / ".test-uwb-safeguard.db"
        self.database_path.unlink(missing_ok=True)
        self.database = str(self.database_path)
        self.module.app.config.update(
            TESTING=True,
            DATABASE=self.database,
            IOT_API_KEY="integration-test-key",
            LINE_CHANNEL_ACCESS_TOKEN="",
            LINE_TARGET_USER_ID="",
        )
        self.client = self.module.app.test_client()

    def tearDown(self):
        self.database_path.unlink(missing_ok=True)

    def test_danger_zone_position_reaches_people_and_alert_tables(self):
        belt = {
            "belt_id": "BELT-001",
            "device_name": "智慧安全腰帶 1",
            "battery": 85,
            "online": True,
        }
        position = {"x": 2200.0, "y": 600.0, "z": 1000.0}
        assessment = {
            "zone": {"id": "edge-a", "name": "樓層邊緣 A 區", "risk": "high"},
            "zone_risk": "high",
            "level": "注意",
        }
        payload = build_safeguard_payload(
            belt, position, assessment, "2026-09-17T12:00:00+08:00"
        )

        response = self.client.post(
            "/api/iot/uwb",
            json=payload,
            headers={"X-API-Key": "integration-test-key"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.get_json()["ok"])

        conn = sqlite3.connect(self.database)
        try:
            person = conn.execute(
                "SELECT id,x,y,z,battery,risk,area FROM people WHERE id='BELT-001'"
            ).fetchone()
            alert = conn.execute(
                """
                SELECT source_system,device_id,alert_type,status
                FROM safety_alerts WHERE device_id='BELT-001'
                """
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(
            person,
            ("BELT-001", 2200.0, 600.0, 1000.0, 85, "中高風險", "樓層邊緣 A 區"),
        )
        self.assertEqual(alert, ("UWB", "BELT-001", "geofence_intrusion", "open"))


if __name__ == "__main__":
    unittest.main()
