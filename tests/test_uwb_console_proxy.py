import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_safeguard_app():
    spec = importlib.util.spec_from_file_location(
        "safeguard_root_app_uwb_console", ROOT / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, body, content_type="application/json", status=200):
        self.body = body
        self.headers = {"Content-Type": content_type}
        self.status = status

    def read(self, _size=-1):
        body, self.body = self.body, b""
        return body

    def getcode(self):
        return self.status

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class UwbConsoleProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_safeguard_app()

    def setUp(self):
        self.database_path = ROOT / ".test-uwb-console.db"
        self.database_path.unlink(missing_ok=True)
        self.module.app.config.update(
            TESTING=True,
            DATABASE=str(self.database_path),
            UWB_BACKEND_URL="http://127.0.0.1:5002",
        )
        self.client = self.module.app.test_client()
        response = self.client.post(
            "/", data={"account": "admin", "password": "admin123"}
        )
        self.assertEqual(response.status_code, 302)

    def tearDown(self):
        self.database_path.unlink(missing_ok=True)

    def test_uwb_page_keeps_safeguard_navigation_and_embeds_console(self):
        response = self.client.get("/site-map")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("SafeGuard", html)
        self.assertIn('/site-map/console/', html)
        self.assertIn("電子圍欄與智慧安全腰帶 UWB 監控", html)
        self.assertIn("查看即時危險警報", html)

    def test_console_proxy_rewrites_uwb_api_urls(self):
        upstream_html = (
            b'<script>fetch("/api/status");'
            b'fetch("/api/belt/status", {method:"POST"});</script>'
        )
        with patch.object(
            self.module.urllib.request,
            "urlopen",
            return_value=FakeResponse(upstream_html, "text/html; charset=utf-8"),
        ):
            response = self.client.get("/site-map/console/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('fetch("/site-map/service/api/status")', html)
        self.assertIn('fetch("/site-map/service/api/belt/status"', html)

    def test_status_reports_connected_backend(self):
        status = json.dumps({"belts": [], "danger_zones": []}).encode("utf-8")
        with patch.object(
            self.module.urllib.request,
            "urlopen",
            return_value=FakeResponse(status),
        ):
            response = self.client.get("/api/uwb/status")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(response.get_json()["state"], "online")


if __name__ == "__main__":
    unittest.main()
