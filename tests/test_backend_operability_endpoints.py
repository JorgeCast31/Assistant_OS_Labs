import http.client
import json
import time
import unittest
from unittest.mock import patch

from assistant_os.config import WEBHOOK_TOKEN
from assistant_os.webhook_server import WebhookHTTPServer, start_server_thread


class TestBackendOperabilityEndpoints(unittest.TestCase):
    server: WebhookHTTPServer
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator
        from assistant_os.storage.mso_store import clear_mso_store

        reset_dynamic_capabilities()
        clear_operational_mode_override()
        reset_task_registry()
        reset_trace_aggregator()
        clear_mso_store()

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        token: str | None = WEBHOOK_TOKEN,
    ) -> tuple[int, dict]:
        headers: dict[str, str] = {}
        payload = None
        if token is not None:
            headers["X-Assistant-Token"] = token
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode("utf-8")

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        conn.close()
        return response.status, json.loads(raw)

    def test_get_agents_registry_returns_ok_and_list(self) -> None:
        status, data = self._request("GET", "/agents/registry")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIsInstance(data["agents"], list)
        self.assertGreaterEqual(len(data["agents"]), 1)
        self.assertTrue(any(item["id"] == "code_executor" for item in data["agents"]))

        agent = data["agents"][0]
        self.assertIn("name", agent)
        self.assertIn("status", agent)
        self.assertIn("capabilities", agent)
        self.assertIn("requires_authority", agent)
        self.assertIn("requires_review", agent)

    def test_get_system_capabilities_returns_ok_and_features(self) -> None:
        status, data = self._request("GET", "/system/capabilities")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("features", data)
        self.assertIn("domains", data)
        self.assertIn("capabilities", data)
        self.assertTrue(data["features"]["authority_artifact"])
        self.assertTrue(data["features"]["replay_prevention"])
        self.assertTrue(data["features"]["runner_enforced"])
        self.assertIn(data["features"]["code_apply_mode"], ("stub", "real", "unknown"))
        self.assertIn(data["features"]["machine_operator"], ("available", "unavailable", "unknown"))
        self.assertIsInstance(data["capabilities"], list)
        self.assertTrue(any(item["id"] == "WORK_QUERY" for item in data["capabilities"]))

    def test_get_mso_state_returns_ok_and_operational_fields(self) -> None:
        status, data = self._request("GET", "/mso/state")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("operational_mode", data)
        self.assertIn("authority_status", data)
        self.assertIn("governance", data)
        self.assertIn("agents_available", data)
        self.assertIn("pending_confirmations", data)
        self.assertIn("active_executions", data)
        self.assertIn("recent_events", data)
        self.assertEqual(data["operational_mode"], "NORMAL")
        self.assertEqual(data["authority_status"], "active")
        self.assertGreaterEqual(data["agents_available"], 1)
        self.assertIsInstance(data["recent_events"], list)

    def test_chat_process_surface_is_preserved_in_metadata_and_audit_without_changing_execution_mode(self) -> None:
        captured: dict[str, dict] = {}

        def _fake_handle_request(req: dict) -> dict:
            captured["req"] = req
            return {
                "ok": True,
                "result_type": "plan_confirmation_required",
                "domain": "WORK",
                "message": "Confirmar",
                "data": {
                    "type": "plan_confirmation_required",
                    "plan": {
                        "plan_id": "plan-surface-1",
                        "preview": "Confirmar",
                    },
                    "plan_id": "plan-surface-1",
                    "governance_trace": {
                        "effective_execution_mode": "confirm",
                    },
                },
                "error": None,
            }

        with patch("assistant_os.core.orchestrator.handle_request", side_effect=_fake_handle_request):
            status, data = self._request(
                "POST",
                "/chat/process",
                body={
                    "text": "crea una tarea",
                    "surface": "system_chat",
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(captured["req"]["metadata"]["surface"], "system_chat")
        self.assertEqual(data["audit"]["surface"], "system_chat")
        self.assertEqual(data["audit"]["execution_mode"], "confirm")
        self.assertTrue(data["needs_confirmation"])


if __name__ == "__main__":
    unittest.main()
