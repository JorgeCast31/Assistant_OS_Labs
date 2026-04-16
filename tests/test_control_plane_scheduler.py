import http.client
import json
import time
import unittest

from assistant_os.control_plane.admin_server import AdminHTTPServer, start_admin_server_thread


class TestControlPlaneScheduler(unittest.TestCase):
    server: AdminHTTPServer
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.port = start_admin_server_thread(
            "127.0.0.1",
            0,
            scheduler_enabled=True,
            scheduler_interval_seconds=1,
        )
        time.sleep(0.15)

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

    def test_scheduler_run_cleans_expired_tokens(self):
        from assistant_os.control_plane.scheduler import ControlPlaneScheduler
        from assistant_os.control_plane.token_service import issue_operator_token
        from assistant_os.mso.operator_identity import get_operator_token_by_id
        from assistant_os.storage.mso_store import persist_operator_token

        issued = issue_operator_token(operator_id="ops-admin", ttl_minutes=30, issued_reason="scheduler-test")
        token = get_operator_token_by_id(issued["token_record"]["token_id"])
        assert token is not None
        token.expires_at = "2000-01-01T00:00:00+00:00"
        persist_operator_token(token)

        scheduler = ControlPlaneScheduler(interval_seconds=60)
        result = scheduler.run_once()

        cleaned = get_operator_token_by_id(issued["token_record"]["token_id"])
        assert cleaned is not None
        self.assertEqual(result.cleaned_tokens, 1)
        self.assertFalse(cleaned.is_active)
        self.assertEqual(cleaned.revoked_by, "system:expiry_cleanup")

    def test_scheduler_runner_is_injectable_for_future_host_decoupling(self):
        from assistant_os.control_plane.scheduler import ControlPlaneScheduler

        calls = []

        def fake_runner(*, trigger: str, operator_context=None, trace_id: str = "", now_ts: str = ""):
            calls.append(
                {
                    "trigger": trigger,
                    "operator_context": operator_context,
                    "trace_id": trace_id,
                    "now_ts": now_ts,
                }
            )
            return {
                "maintenance": {"action_id": "maintenance:test"},
                "result": {
                    "cleaned_tokens": 0,
                    "cleaned_store_records": {},
                    "cleaned_lock_slots": 0,
                    "token_summary": {"active_count": 0, "revoked_count": 0, "expired_active_tokens": 0},
                    "store_status": {"counts": {}, "expired_record_count": 0},
                    "warnings": [],
                },
                "signals": [],
            }

        scheduler = ControlPlaneScheduler(interval_seconds=60, runner=fake_runner)
        result = scheduler.run_once()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["trigger"], "scheduler")
        self.assertEqual(result.cleaned_tokens, 0)

    def test_health_endpoint_includes_scheduler_and_operational_fields(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/health")
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        conn.close()

        self.assertEqual(response.status, 200)
        self.assertIn(payload["status"], {"ok", "degraded"})
        self.assertIn("uptime_seconds", payload)
        self.assertIn("scheduler", payload)
        self.assertTrue(payload["scheduler"]["running"])
        self.assertIn("tokens", payload)
        self.assertIn("locks", payload)
        self.assertIn("store", payload)
        self.assertIn("recent_maintenance", payload)
        self.assertIn("recent_signals", payload)
        self.assertIn("warnings", payload)

    def test_lock_manager_tracks_ownership_and_conflict(self):
        from assistant_os.control_plane.locks import ControlPlaneLockManager, LockConflictError

        manager = ControlPlaneLockManager()
        lease = manager.acquire("restriction:test", owner_id="request-1")
        self.assertEqual(lease.owner_id, "request-1")
        self.assertEqual(len(manager.active_locks()), 1)
        with self.assertRaises(LockConflictError):
            manager.acquire("restriction:test", owner_id="request-2", timeout_seconds=0.0)
        with self.assertRaises(LockConflictError):
            manager.release("restriction:test", owner_id="request-2")
        manager.release("restriction:test", owner_id="request-1")
        self.assertEqual(manager.active_locks(), [])
        removed = manager.cleanup_unused_locks()
        self.assertEqual(removed, 1)


if __name__ == "__main__":
    unittest.main()
