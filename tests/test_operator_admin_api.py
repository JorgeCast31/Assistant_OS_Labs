import http.client
import json
import time
import unittest
from unittest.mock import patch

from assistant_os.webhook_server import WebhookHTTPServer, start_server_thread


class TestOperatorAdminApi(unittest.TestCase):
    server: WebhookHTTPServer
    port: int
    _token_patcher = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._token_patcher = patch("assistant_os.webhook_server.ASSISTANT_API_TOKEN", "admin-test-token")
        cls._token_patcher.start()
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        if cls._token_patcher is not None:
            cls._token_patcher.stop()

    def setUp(self):
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.operator_identity import reset_operator_registry
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator
        from assistant_os.storage.mso_store import clear_mso_store

        reset_dynamic_capabilities()
        reset_operator_registry()
        clear_operational_mode_override()
        reset_task_registry()
        reset_trace_aggregator()
        clear_mso_store()

    def _request(self, method: str, path: str, body: dict | None = None, *, operator_id: str = "", admin_token: str = "admin-test-token"):
        headers = {"X-Assistant-Admin-Token": admin_token}
        if operator_id:
            headers["X-Assistant-Operator-Id"] = operator_id
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        conn.close()
        return response.status, json.loads(raw)

    def _create_restriction(self) -> str:
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess
        from assistant_os.mso.restrictions import get_active_restrictions
        from assistant_os.mso.contracts import DelegationTask, ExecutionCapability

        task = DelegationTask(
            task_id="admin-api-task",
            origin_intent_id="admin-api-intent",
            task_type="BASIC_COGNITIVE_EXECUTION",
            task_goal="Trigger admin restriction.",
            allowed_operations=["read_system_state"],
            input_refs=["request:admin-api"],
            scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True},
            requires_capability="BASIC_COGNITIVE_EXECUTION",
            expected_output_schema={"required_artifact_keys": ["system_state"]},
            expiry="2099-01-01T00:00:00+00:00",
            trace_id="trace:admin-api",
        )
        capability = ExecutionCapability(
            capability_id="admin-api-capability",
            task_id="admin-api-task",
            execution_class="BASIC_COGNITIVE_EXECUTION",
            allowed_operations=["read_system_state"],
            scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True},
            issued_at="2026-04-14T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
            issued_by="kernel",
            trace_id="trace:admin-api",
        )
        run_task_in_subprocess(task, capability)
        return get_active_restrictions()[0].restriction_id

    def test_viewer_can_read_active_restrictions(self):
        restriction_id = self._create_restriction()

        status, data = self._request("GET", "/admin/restrictions", operator_id="ops-viewer")

        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["restrictions"][0]["restriction_id"], restriction_id)
        self.assertEqual(data["operator"]["role"], "viewer")

    def test_reviewer_can_acknowledge_and_updates_review_state(self):
        restriction_id = self._create_restriction()

        status, data = self._request(
            "POST",
            f"/admin/restrictions/{restriction_id}/acknowledge",
            {"operator_id": "ops-reviewer", "reason": "Reviewed by human."},
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["action"]["operator_role"], "reviewer")
        self.assertEqual(data["restriction"]["review_state"], "acknowledged")
        self.assertEqual(data["restriction"]["reviewed_by"], "ops-reviewer")

    def test_admin_can_clear_restriction(self):
        restriction_id = self._create_restriction()

        status, data = self._request(
            "POST",
            f"/admin/restrictions/{restriction_id}/clear",
            {"operator_id": "ops-admin", "reason": "Recovered safely."},
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["action"]["operator_role"], "admin")
        self.assertEqual(data["restriction"]["status"], "CLEARED")
        self.assertEqual(data["restriction"]["review_state"], "actioned")

    def test_insufficient_role_is_denied(self):
        restriction_id = self._create_restriction()

        status, data = self._request(
            "POST",
            f"/admin/restrictions/{restriction_id}/clear",
            {"operator_id": "ops-reviewer", "reason": "Not enough role."},
        )

        self.assertEqual(status, 403)
        self.assertEqual(data["error"]["type"], "Forbidden")

    def test_invalid_operator_is_denied(self):
        restriction_id = self._create_restriction()

        status, data = self._request(
            "POST",
            f"/admin/restrictions/{restriction_id}/acknowledge",
            {"operator_id": "missing-operator", "reason": "Bad operator."},
        )

        self.assertEqual(status, 403)
        self.assertEqual(data["error"]["type"], "Forbidden")

    def test_missing_reason_is_rejected(self):
        restriction_id = self._create_restriction()

        status, data = self._request(
            "POST",
            f"/admin/restrictions/{restriction_id}/override",
            {"operator_id": "ops-admin"},
        )

        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["type"], "BadRequest")

    def test_history_links_events_response_and_actions(self):
        restriction_id = self._create_restriction()
        self._request(
            "POST",
            f"/admin/restrictions/{restriction_id}/acknowledge",
            {"operator_id": "ops-reviewer", "reason": "Seen."},
        )

        status, data = self._request(
            "GET",
            f"/admin/restrictions/{restriction_id}/history",
            operator_id="ops-viewer",
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["history"]["restriction"]["restriction_id"], restriction_id)
        self.assertTrue(data["history"]["source_events"])
        self.assertIsNotNone(data["history"]["security_response"])
        self.assertGreaterEqual(len(data["history"]["operator_actions"]), 1)

    def test_operator_actions_support_filters(self):
        restriction_id = self._create_restriction()
        self._request(
            "POST",
            f"/admin/restrictions/{restriction_id}/acknowledge",
            {"operator_id": "ops-reviewer", "reason": "Seen."},
        )

        status, data = self._request(
            "GET",
            f"/admin/operator-actions?filter_operator_id=ops-reviewer&restriction_id={restriction_id}&action_type=acknowledge_restriction",
            operator_id="ops-viewer",
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["operator_actions"][0]["target_restriction_id"], restriction_id)


if __name__ == "__main__":
    unittest.main()
