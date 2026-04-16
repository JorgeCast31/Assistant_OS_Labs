import unittest


class TestCognitiveWorkerRunner(unittest.TestCase):
    def setUp(self):
        from assistant_os.storage.mso_store import clear_mso_store
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.system_state import clear_operational_mode_override

        clear_mso_store()
        reset_dynamic_capabilities()
        clear_operational_mode_override()

    def _task(self, **overrides):
        from assistant_os.mso.contracts import DelegationTask

        data = {
            "task_id": "task-1",
            "origin_intent_id": "intent-1",
            "task_type": "BASIC_COGNITIVE_EXECUTION",
            "task_goal": "Inspect current system state and summarize it.",
            "allowed_operations": ["read_system_state", "summarize_context"],
            "input_refs": ["request:1"],
            "scope": {"domain": "COGNITIVE", "max_items": 5, "timeout_ms": 200},
            "requires_capability": "BASIC_COGNITIVE_EXECUTION",
            "expected_output_schema": {"required_artifact_keys": ["system_state", "summary"]},
            "expiry": "2099-01-01T00:00:00+00:00",
            "trace_id": "trace-1",
        }
        data.update(overrides)
        return DelegationTask(**data)

    def _capability(self, **overrides):
        from assistant_os.mso.contracts import ExecutionCapability

        data = {
            "capability_id": "cap-1",
            "task_id": "task-1",
            "execution_class": "BASIC_COGNITIVE_EXECUTION",
            "allowed_operations": ["read_system_state", "summarize_context", "simulate"],
            "scope": {"domain": "COGNITIVE", "max_items": 5, "timeout_ms": 200},
            "issued_at": "2026-04-14T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "issued_by": "kernel",
            "trace_id": "trace-1",
        }
        data.update(overrides)
        return ExecutionCapability(**data)

    def test_runner_returns_completed_report_on_valid_task(self):
        from assistant_os.executors.cognitive_worker_runner import get_runner_status, run_task_in_subprocess

        report, escalation, events = run_task_in_subprocess(self._task(), self._capability())

        self.assertEqual(report.status, "completed")
        self.assertIsNone(escalation)
        self.assertTrue(any(event.event_type == "worker_started" for event in events))
        self.assertTrue(any(event.event_type == "os_hardening_applied" for event in events))
        self.assertTrue(any(event.event_type == "worker_completed" for event in events))
        self.assertEqual(get_runner_status()["active_process_count"], 0)

    def test_runner_reports_timeout_when_process_exceeds_budget(self):
        from assistant_os.executors.cognitive_worker_runner import get_runner_status, run_task_in_subprocess

        report, escalation, events = run_task_in_subprocess(
            self._task(
                allowed_operations=["read_system_state"],
                expected_output_schema={"required_artifact_keys": ["system_state"]},
                scope={"domain": "COGNITIVE", "timeout_ms": 10, "force_runner_delay_ms": 80},
            ),
            self._capability(
                allowed_operations=["read_system_state"],
                scope={"domain": "COGNITIVE", "timeout_ms": 10, "force_runner_delay_ms": 80},
            ),
        )

        self.assertEqual(report.status, "timeout")
        self.assertTrue(report.requires_escalation)
        self.assertEqual(escalation.current_limit_hit, "worker_process_timeout")
        self.assertTrue(any(event.event_type == "worker_forced_kill" for event in events))
        self.assertEqual(get_runner_status()["active_process_count"], 0)

    def test_runner_reports_failure_when_process_crashes(self):
        from assistant_os.executors.cognitive_worker_runner import get_runner_status, run_task_in_subprocess

        report, escalation, events = run_task_in_subprocess(
            self._task(
                allowed_operations=["read_system_state"],
                expected_output_schema={"required_artifact_keys": ["system_state"]},
                scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_runner_crash": True},
            ),
            self._capability(
                allowed_operations=["read_system_state"],
                scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_runner_crash": True},
            ),
        )

        self.assertEqual(report.status, "failed")
        self.assertTrue(report.requires_escalation)
        self.assertEqual(escalation.current_limit_hit, "worker_process_failure")
        self.assertTrue(any(event.event_type == "worker_crash" for event in events))
        self.assertEqual(get_runner_status()["active_process_count"], 0)

    def test_runner_blocks_invalid_input_refs_and_persists_security_event(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess
        from assistant_os.storage.mso_store import list_recent_worker_security_events

        report, escalation, events = run_task_in_subprocess(
            self._task(input_refs=["state:current", "state:../../secrets"]),
            self._capability(),
        )

        self.assertEqual(report.status, "blocked")
        self.assertEqual(escalation.current_limit_hit, "invalid_input_ref")
        self.assertTrue(any(event.event_type == "invalid_input_ref" for event in events))
        persisted = list_recent_worker_security_events()
        self.assertTrue(any(item["payload"]["event_type"] == "invalid_input_ref" for item in persisted))

    def test_runner_blocks_network_requiring_task(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess

        report, escalation, events = run_task_in_subprocess(
            self._task(
                input_refs=["request:1"],
                scope={"domain": "COGNITIVE", "timeout_ms": 200, "allow_network": True},
            ),
            self._capability(scope={"domain": "COGNITIVE", "timeout_ms": 200, "allow_network": True}),
        )

        self.assertEqual(report.status, "blocked")
        self.assertEqual(escalation.current_limit_hit, "network_denied")
        self.assertTrue(any(event.event_type == "network_denied" for event in events))

    def test_runner_blocks_excessive_input_refs(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess

        report, escalation, events = run_task_in_subprocess(
            self._task(
                input_refs=[f"request:{idx}" for idx in range(10)],
                scope={"domain": "COGNITIVE", "max_input_refs": 3, "timeout_ms": 200},
            ),
            self._capability(scope={"domain": "COGNITIVE", "max_input_refs": 3, "timeout_ms": 200}),
        )

        self.assertEqual(report.status, "blocked")
        self.assertEqual(escalation.current_limit_hit, "max_input_refs_exceeded")
        self.assertTrue(any(event.event_type == "resource_limit_exceeded" for event in events))

    def test_repeated_timeouts_trigger_confirmation_restriction(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess
        from assistant_os.mso.capability_registry import check_capability
        from assistant_os.storage.mso_store import list_recent_security_responses

        for _ in range(2):
            run_task_in_subprocess(
                self._task(
                    allowed_operations=["read_system_state"],
                    expected_output_schema={"required_artifact_keys": ["system_state"]},
                    scope={"domain": "COGNITIVE", "timeout_ms": 10, "force_runner_delay_ms": 80},
                ),
                self._capability(
                    allowed_operations=["read_system_state"],
                    scope={"domain": "COGNITIVE", "timeout_ms": 10, "force_runner_delay_ms": 80},
                ),
            )

        capability = check_capability("BASIC_COGNITIVE_EXECUTION", "COGNITIVE")
        responses = list_recent_security_responses()
        self.assertEqual(capability.mode, "confirm_only")
        self.assertTrue(any(item["payload"]["action"] == "require_confirmation" for item in responses))

    def test_repeated_crashes_trigger_capability_revocation(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess
        from assistant_os.mso.capability_registry import check_capability

        for _ in range(2):
            run_task_in_subprocess(
                self._task(
                    allowed_operations=["read_system_state"],
                    expected_output_schema={"required_artifact_keys": ["system_state"]},
                    scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_runner_crash": True},
                ),
                self._capability(
                    allowed_operations=["read_system_state"],
                    scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_runner_crash": True},
                ),
            )

        capability = check_capability("BASIC_COGNITIVE_EXECUTION", "COGNITIVE")
        self.assertFalse(capability.allowed)
        self.assertEqual(capability.source, "revocation")

    def test_actual_network_attempt_is_denied_and_traced(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess

        report, escalation, events = run_task_in_subprocess(
            self._task(
                allowed_operations=["read_system_state"],
                expected_output_schema={"required_artifact_keys": []},
                scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True},
            ),
            self._capability(
                allowed_operations=["read_system_state"],
                scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True},
            ),
        )

        self.assertEqual(report.status, "blocked")
        self.assertEqual(escalation.current_limit_hit, "network_denied")
        self.assertTrue(any(event.event_type == "network_denied" for event in events))
        self.assertTrue(any(event.response_triggered for event in events))


if __name__ == "__main__":
    unittest.main()
