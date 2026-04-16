import io
import json
import unittest
from contextlib import redirect_stdout


class TestSchedulerRunner(unittest.TestCase):
    def setUp(self):
        from assistant_os.control_plane.locks import reset_lock_backend
        from assistant_os.mso.operator_identity import reset_operator_registry
        from assistant_os.storage.mso_store import clear_mso_store

        reset_lock_backend()
        reset_operator_registry()
        clear_mso_store()

    def test_scheduler_runner_can_run_once_without_admin_server(self):
        from assistant_os.control_plane import scheduler_runner

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = scheduler_runner.main(["--run-once", "--interval-seconds", "1"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["scheduler"]["host_mode"], "standalone_scheduler_runner")
        self.assertEqual(payload["run"]["run_id"], "scheduler-run:1")

    def test_maintenance_cycle_runs_without_admin_server_startup(self):
        from assistant_os.control_plane.maintenance import run_maintenance_cycle, recent_maintenance

        payload = run_maintenance_cycle(trigger="test-harness")

        self.assertEqual(payload["maintenance"]["action_type"], "maintenance_cycle")
        self.assertGreaterEqual(len(recent_maintenance(limit=10)), 1)


if __name__ == "__main__":
    unittest.main()
