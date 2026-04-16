import io
import json
import time
import unittest
from contextlib import redirect_stdout

from assistant_os.control_plane.admin_server import AdminHTTPServer, start_admin_server_thread


class TestControlPlaneBootstrap(unittest.TestCase):
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

    def test_bootstrap_cli_creates_initial_admin_record(self):
        from assistant_os.control_plane import admin_server

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = admin_server.main(
                ["--bootstrap", "--operator-id", "ops-admin", "--ttl-minutes", "30", "--reason", "bootstrap-test"]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["bootstrap_record"]["operator_id"], "ops-admin")
        self.assertEqual(payload["operator"]["role"], "admin")
        self.assertTrue(payload["token"])

    def test_bootstrap_rejects_repeat_unsafe_initialization(self):
        from assistant_os.control_plane.bootstrap import BootstrapError, bootstrap_control_plane

        bootstrap_control_plane(operator_id="ops-admin", ttl_minutes=30, reason="bootstrap-test")
        with self.assertRaises(BootstrapError):
            bootstrap_control_plane(operator_id="ops-admin", ttl_minutes=30, reason="bootstrap-repeat")

    def test_health_endpoint_reports_control_plane_identity(self):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/health")
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        conn.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["service"], "assistant_os_control_plane")
        self.assertEqual(payload["status"], "ok")


if __name__ == "__main__":
    unittest.main()
