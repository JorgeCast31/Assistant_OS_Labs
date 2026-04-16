import http.client
import json
import time
import unittest

from assistant_os.control_plane.admin_server import AdminHTTPServer, start_admin_server_thread


class TestControlPlaneMaintenance(unittest.TestCase):
    server: AdminHTTPServer
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.port = start_admin_server_thread(
            "127.0.0.1",
            0,
            scheduler_enabled=True,
            scheduler_interval_seconds=60,
        )
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

    def _mint_admin_token(self) -> str:
        from assistant_os.control_plane.admin_service import mint_operator_token

        return mint_operator_token(operator_id="ops-admin", ttl_minutes=60)["token"]

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

    def test_admin_can_trigger_maintenance_cycle(self):
        token = self._mint_admin_token()

        status, data = self._request("POST", "/admin/maintenance/run", {}, token=token)

        self.assertEqual(status, 200)
        self.assertEqual(data["control_plane_request"]["action"], "run_maintenance_cycle")
        self.assertEqual(data["maintenance"]["action_type"], "maintenance_cycle")
        self.assertIn("result", data)

    def test_admin_can_inspect_locks_and_cleanup_slots(self):
        token = self._mint_admin_token()

        status, data = self._request("GET", "/admin/maintenance/locks", token=token)
        self.assertEqual(status, 200)
        self.assertIn("active_count", data)
        self.assertIn("maintenance", data)

        status, data = self._request("POST", "/admin/maintenance/locks/cleanup", {}, token=token)
        self.assertEqual(status, 200)
        self.assertEqual(data["maintenance"]["action_type"], "force_lock_cleanup")
        self.assertIn("signals", data)

    def test_maintenance_status_exposes_recent_activity_and_signals(self):
        token = self._mint_admin_token()
        self._request("POST", "/admin/maintenance/locks/cleanup", {}, token=token)

        status, data = self._request("GET", "/admin/maintenance", token=token)

        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(data["recent_maintenance"]), 1)
        self.assertIn("recent_signals", data)


if __name__ == "__main__":
    unittest.main()
