import unittest


class TestCognitiveWorker(unittest.TestCase):
    def _task(self, **overrides):
        from assistant_os.mso.contracts import DelegationTask

        data = {
            "task_id": "task-1",
            "origin_intent_id": "intent-1",
            "task_type": "BASIC_COGNITIVE_EXECUTION",
            "task_goal": "Inspect current system state and summarize it.",
            "allowed_operations": ["read_system_state", "summarize_context"],
            "input_refs": ["request:1"],
            "scope": {"domain": "COGNITIVE", "max_items": 5},
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
            "allowed_operations": ["read_system_state", "summarize_context"],
            "scope": {"domain": "COGNITIVE", "max_items": 5},
            "issued_at": "2026-04-14T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "issued_by": "kernel",
            "trace_id": "trace-1",
        }
        data.update(overrides)
        return ExecutionCapability(**data)

    def test_valid_worker_execution_returns_report(self):
        from assistant_os.executors.cognitive_worker import execute_delegation_task

        report, escalation = execute_delegation_task(self._task(), self._capability())

        self.assertEqual(report.status, "completed")
        self.assertFalse(report.requires_escalation)
        self.assertIn("system_state", report.artifacts)
        self.assertIsNone(escalation)

    def test_worker_blocked_without_capability(self):
        from assistant_os.executors.cognitive_worker import execute_delegation_task

        report, escalation = execute_delegation_task(
            self._task(allowed_operations=["read_system_state", "simulate"]),
            self._capability(allowed_operations=["read_system_state"]),
        )

        self.assertEqual(report.status, "blocked")
        self.assertTrue(report.requires_escalation)
        self.assertIsNotNone(escalation)
        self.assertEqual(escalation.current_limit_hit, "operation_not_allowed")

    def test_worker_scope_violation_generates_escalation(self):
        from assistant_os.executors.cognitive_worker import execute_delegation_task

        report, escalation = execute_delegation_task(
            self._task(scope={"domain": "WORK"}),
            self._capability(scope={"domain": "COGNITIVE"}),
        )

        self.assertEqual(report.status, "blocked")
        self.assertTrue(report.requires_escalation)
        self.assertEqual(escalation.current_limit_hit, "scope_violation")

    def test_expected_output_schema_miss_triggers_escalation(self):
        from assistant_os.executors.cognitive_worker import execute_delegation_task

        report, escalation = execute_delegation_task(
            self._task(expected_output_schema={"required_artifact_keys": ["system_state", "summary", "missing_key"]}),
            self._capability(),
        )

        self.assertEqual(report.status, "needs_escalation")
        self.assertTrue(report.requires_escalation)
        self.assertEqual(escalation.current_limit_hit, "expected_output_schema")

    def test_worker_timeout_generates_escalation(self):
        from assistant_os.executors.cognitive_worker import execute_delegation_task

        report, escalation = execute_delegation_task(
            self._task(
                allowed_operations=["simulate"],
                expected_output_schema={"required_artifact_keys": ["simulation"]},
                scope={"domain": "COGNITIVE", "timeout_ms": 5, "simulate_delay_ms": 20},
            ),
            self._capability(
                allowed_operations=["simulate"],
                scope={"domain": "COGNITIVE", "timeout_ms": 5, "simulate_delay_ms": 20},
            ),
        )

        self.assertEqual(report.status, "timeout")
        self.assertTrue(report.requires_escalation)
        self.assertEqual(escalation.current_limit_hit, "timeout")


if __name__ == "__main__":
    unittest.main()
