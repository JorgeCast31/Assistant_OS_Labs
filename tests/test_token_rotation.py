import http.client
import json
import time
import unittest

from assistant_os.control_plane.admin_server import AdminHTTPServer, start_admin_server_thread


class TestTokenRotation(unittest.TestCase):
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
        from assistant_os.mso.operator_identity import reset_operator_registry
        from assistant_os.storage.mso_store import clear_mso_store

        reset_lock_backend()
        reset_operator_registry()
        clear_mso_store()

    def _mint_admin_token(self) -> tuple[str, str]:
        from assistant_os.control_plane.admin_service import mint_operator_token

        payload = mint_operator_token(operator_id="ops-admin", ttl_minutes=60)
        return payload["token"], payload["token_record"]["token_id"]

    def _request(self, method: str, path: str, body: dict | None = None, *, token: str):
        headers = {"Authorization": f"Bearer {token}"}
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        conn.close()
        return response.status, data

    def test_rotate_token_revokes_previous_and_issues_replacement(self):
        admin_token, token_id = self._mint_admin_token()

        status, data = self._request(
            "POST",
            "/admin/tokens/rotate",
            {"token_id": token_id, "reason": "routine rotation", "ttl_minutes": 45},
            token=admin_token,
        )

        self.assertEqual(status, 200)
        self.assertTrue(data["token"])
        self.assertEqual(data["replaced_token_record"]["token_id"], token_id)
        self.assertFalse(data["replaced_token_record"]["is_active"])
        self.assertEqual(data["replaced_token_record"]["revoked_by"], "ops-admin")
        self.assertEqual(data["token_record"]["rotated_from"], token_id)

    def test_cleanup_expired_tokens_deactivates_stale_credentials(self):
        from assistant_os.control_plane.admin_service import mint_operator_token
        from assistant_os.mso.operator_identity import get_operator_token_by_id
        from assistant_os.storage.mso_store import persist_operator_token

        admin_token, _ = self._mint_admin_token()
        issued = mint_operator_token(operator_id="ops-reviewer", ttl_minutes=60)
        record = get_operator_token_by_id(issued["token_record"]["token_id"])
        assert record is not None
        record.expires_at = "2000-01-01T00:00:00+00:00"
        persist_operator_token(record)

        status, data = self._request(
            "POST",
            "/admin/tokens/cleanup",
            {"now_ts": "2001-01-01T00:00:00+00:00"},
            token=admin_token,
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        self.assertFalse(data["cleaned_tokens"][0]["is_active"])
        self.assertEqual(data["cleaned_tokens"][0]["revoked_by"], "system:expiry_cleanup")

    def test_token_audit_shows_operators_and_bootstrap_history(self):
        from assistant_os.control_plane.bootstrap import bootstrap_control_plane

        payload = bootstrap_control_plane(operator_id="ops-admin", ttl_minutes=30, reason="bootstrap-audit")
        admin_token = payload["token"]

        status, operators = self._request("GET", "/admin/operators", token=admin_token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(operators["count"], 3)

        status, bootstrap = self._request("GET", "/admin/bootstrap", token=admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(bootstrap["count"], 1)
        self.assertEqual(bootstrap["bootstrap_history"][0]["operator_id"], "ops-admin")


if __name__ == "__main__":
    unittest.main()
