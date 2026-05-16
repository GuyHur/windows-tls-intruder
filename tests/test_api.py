"""Integration tests for FastAPI endpoints (Frida is mocked out)."""

import unittest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

# Mock frida before any intruder module is imported
frida_mock = MagicMock()
with patch.dict("sys.modules", {"frida": frida_mock, "frida.core": MagicMock()}):
    from intruder.app import app


class HealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health(self) -> None:
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


class ScriptsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_list_scripts(self) -> None:
        r = self.client.get("/api/scripts")
        self.assertEqual(r.status_code, 200)
        scripts = r.json()["scripts"]
        self.assertIn("winsock", scripts)
        self.assertIn("schannel", scripts)
        self.assertIn("openssl", scripts)
        self.assertIn("libc", scripts)
        self.assertIn("gnutls", scripts)
        self.assertNotIn("_debug_agent", scripts)


class SessionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_list_sessions_empty(self) -> None:
        r = self.client.get("/api/sessions")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sessions"], [])

    def test_delete_nonexistent_session(self) -> None:
        r = self.client.delete("/api/sessions/nonexistent")
        self.assertEqual(r.status_code, 404)


class PendingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_list_pending_empty(self) -> None:
        r = self.client.get("/api/pending")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pending"], [])

    def test_resolve_nonexistent(self) -> None:
        r = self.client.post("/api/pending/fake/resolve", json={"action": "forward"})
        self.assertEqual(r.status_code, 404)


class WebSocketTests(unittest.TestCase):
    def test_ws_connects(self) -> None:
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            pass


if __name__ == "__main__":
    unittest.main()
