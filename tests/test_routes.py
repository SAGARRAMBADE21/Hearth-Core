import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from server import app


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"HEARTH_STATE_DIR": self.tmp.name})
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_health_and_agents(self):
        self.assertEqual(self.client.get("/health").json()["agent"], "claude_code")
        agents = self.client.get("/api/agents").json()
        self.assertEqual((agents["active"], agents["adapters"]), ("claude_code", ["claude_code"]))
        caps = self.client.get("/api/agents/capabilities").json()
        self.assertTrue(caps["data"]["github"]["enabled"])

    def test_apidiff_route(self):
        body = {"language": "python", "module": "sdk",
                "old": "def a(x: int) -> int: ...\n", "new": "def a(x: int, y: int) -> int: ...\n",
                "provider": "acme", "package": {"ecosystem": "pypi", "name": "acme", "from": "1", "to": "2"}}
        out = self.client.post("/api/apidiff", json=body).json()
        self.assertEqual(out["breaking"], 1)
        self.assertEqual(out["changes"][0]["type"], "param_added_required")
        self.assertEqual(out["change_record"]["kind"], "breaking")

    def test_github_token_route_rejects_garbage(self):
        self.assertEqual(self.client.post("/api/connectors/github/token", json={"token": "nope"}).status_code, 400)
        self.assertEqual(self.client.post("/api/connectors/github/token", json={"token": "  "}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
