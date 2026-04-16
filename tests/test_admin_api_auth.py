import http.client
import json
import time
import unittest

from assistant_os.control_plane.admin_server import AdminHTTPServer, start_admin_server_thread


class TestAdminApiAuth(unittest.TestCase):
    server: AdminHTTPServer
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.port = start_admin_server_thread("127.0.0.1", 0)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        from assistant_os.control_plane.locks import reset_lock_backend
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.operator_identity import reset_operator_registry
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator
        from assistant_os.storage.mso_store import clear_mso_store

        reset_lock_backend()
        reset_dynamic_capabilities()
        reset_operator_registry()
        clear_operational_mode_override()
        reset_task_registry()
        reset_trace_aggregator()
        clear_mso_store()

    def _request(self, method: str, path: str, body: dict | None = None, *, token: str | None):
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
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

    def _mint_token(self, operator_id: str, ttl_minutes: int = 60) -> tuple[str, str]:
        from assistant_os.control_plane.admin_service import mint_operator_token

        payload = mint_operator_token(operator_id=operator_id, ttl_minutes=ttl_minutes)
        return payload["token"], payload["token_record"]["token_id"]

    def _create_restriction(self) -> str:
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess
        from assistant_os.mso.contracts import DelegationTask, ExecutionCapability
        from assistant_os.mso.restrictions import get_active_restrictions

        task = DelegationTask(
            task_id="auth-api-task",
            origin_intent_id="auth-api-intent",
            task_type="BASIC_COGNITIVE_EXECUTION",
            task_goal="Trigger auth restriction.",
            allowed_operations=["read_system_state"],
            input_refs=["request:auth-api"],
            scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True},
            requires_capability="BASIC_COGNITIVE_EXECUTION",
            expected_output_schema={"required_artifact_keys": ["system_state"]},
            expiry="2099-01-01T00:00:00+00:00",
            trace_id="trace:auth-api",
        )
        capability = ExecutionCapability(
            capability_id="auth-api-capability",
            task_id="auth-api-task",
            execution_class="BASIC_COGNITIVE_EXECUTION",
            allowed_operations=["read_system_state"],
            scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True},
            issued_at="2026-04-15T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
            issued_by="kernel",
            trace_id="trace:auth-api",
        )
        run_task_in_subprocess(task, capability)
        return get_active_restrictions()[0].restriction_id

    def test_missing_token_is_rejected(self):
        status, data = self._request("GET", "/admin/restrictions", token=None)

        self.assertEqual(status, 401)
        self.assertEqual(data["error"]["type"], "Unauthorized")

    def test_revoked_token_is_rejected(self):
        from assistant_os.control_plane.admin_service import revoke_operator_token

        token, token_id = self._mint_token("ops-viewer")
        revoke_operator_token(token_id=token_id)

        status, data = self._request("GET", "/admin/restrictions", token=token)

        self.assertEqual(status, 401)
        self.assertEqual(data["error"]["type"], "Unauthorized")

    def test_webhook_server_no_longer_serves_admin_routes(self):
        from assistant_os.webhook_server import start_server_thread

        server, port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/admin/restrictions")
            response = conn.getresponse()
            raw = response.read().decode("utf-8")
            conn.close()
            data = json.loads(raw)
            self.assertEqual(response.status, 405)
            self.assertEqual(data["error"]["type"], "MethodNotAllowed")
        finally:
            server.shutdown()
            server.server_close()

    def test_admin_can_audit_tokens_without_leaking_raw_secret(self):
        admin_token, revoked_token_id = self._mint_token("ops-admin")
        viewer_token, _ = self._mint_token("ops-viewer")

        status, data = self._request("GET", "/admin/tokens", token=admin_token)

        self.assertEqual(status, 200)
        self.assertGreaterEqual(data["count"], 2)
        self.assertTrue("control_plane_request" in data)
        self.assertTrue(all(item["token_hash"] == "" for item in data["tokens"]))
        self.assertIn(revoked_token_id, {item["token_id"] for item in data["tokens"]})

        status, data = self._request("GET", "/admin/tokens", token=viewer_token)
        self.assertEqual(status, 403)
        self.assertEqual(data["error"]["type"], "Forbidden")

    def test_conflicting_actions_fail_closed(self):
        from assistant_os.control_plane.admin_service import _get_lock

        restriction_id = self._create_restriction()
        token, _ = self._mint_token("ops-admin")
        lock = _get_lock(restriction_id)
        self.assertTrue(lock.acquire(blocking=False))
        try:
            status, data = self._request(
                "POST",
                f"/admin/restrictions/{restriction_id}/clear",
                {"reason": "Conflict test."},
                token=token,
            )
            self.assertEqual(status, 409)
            self.assertEqual(data["error"]["type"], "Conflict")
        finally:
            lock.release()


if __name__ == "__main__":
    unittest.main()
