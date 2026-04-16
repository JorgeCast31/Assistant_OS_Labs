import unittest


class TestMsoRestrictions(unittest.TestCase):
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

    def _task(self, **overrides):
        from assistant_os.mso.contracts import DelegationTask

        data = {
            "task_id": "restriction-task-1",
            "origin_intent_id": "restriction-intent-1",
            "task_type": "BASIC_COGNITIVE_EXECUTION",
            "task_goal": "Trigger restriction flow.",
            "allowed_operations": ["read_system_state"],
            "input_refs": ["request:restriction"],
            "scope": {"domain": "COGNITIVE", "timeout_ms": 10, "force_runner_delay_ms": 80},
            "requires_capability": "BASIC_COGNITIVE_EXECUTION",
            "expected_output_schema": {"required_artifact_keys": ["system_state"]},
            "expiry": "2099-01-01T00:00:00+00:00",
            "trace_id": "trace:restriction",
        }
        data.update(overrides)
        return DelegationTask(**data)

    def _network_task(self):
        return self._task(scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True})

    def _capability(self, **overrides):
        from assistant_os.mso.contracts import ExecutionCapability

        data = {
            "capability_id": "restriction-cap-1",
            "task_id": "restriction-task-1",
            "execution_class": "BASIC_COGNITIVE_EXECUTION",
            "allowed_operations": ["read_system_state"],
            "scope": {"domain": "COGNITIVE", "timeout_ms": 10, "force_runner_delay_ms": 80},
            "issued_at": "2026-04-14T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "issued_by": "kernel",
            "trace_id": "trace:restriction",
        }
        data.update(overrides)
        return ExecutionCapability(**data)

    def _network_capability(self):
        return self._capability(scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True})

    def test_restriction_created_from_security_response(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess
        from assistant_os.mso.restrictions import get_active_restrictions, get_restrictions_by_source_event, get_restrictions_by_type

        run_task_in_subprocess(self._network_task(), self._network_capability())

        restrictions = get_active_restrictions()
        self.assertEqual(len(restrictions), 1)
        self.assertEqual(restrictions[0].type, "REVOKE_CAPABILITY")
        self.assertTrue(restrictions[0].source_events)
        self.assertEqual(len(get_restrictions_by_type("REVOKE_CAPABILITY")), 1)
        self.assertEqual(len(get_restrictions_by_source_event(restrictions[0].source_events[0])), 1)

    def test_restriction_lifecycle_extend_and_expire(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess
        from assistant_os.mso.operator_actions import extend_restriction
        from assistant_os.mso.restrictions import expire_restrictions, get_active_restrictions, get_recent_expired_restrictions

        run_task_in_subprocess(self._network_task(), self._network_capability())
        restriction = get_active_restrictions()[0]

        extend_restriction(
            operator_id="ops-admin",
            restriction_id=restriction.restriction_id,
            reason="Need more observation time.",
            expires_at="2099-01-01T00:15:00+00:00",
            trace_id="trace:operator",
        )
        active = get_active_restrictions()[0]
        self.assertEqual(active.status, "EXTENDED")

        expire_restrictions(now_ts="2100-01-01T00:16:00+00:00")
        expired = get_recent_expired_restrictions()
        self.assertEqual(expired[0].status, "EXPIRED")

    def test_operator_clear_and_override_are_traced(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess
        from assistant_os.mso.capability_registry import check_capability
        from assistant_os.mso.operator_actions import clear_restriction, override_restriction
        from assistant_os.mso.restrictions import get_active_restrictions, get_restriction, get_restriction_history

        network_task = self._task(scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True})
        network_capability = self._capability(scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True})
        run_task_in_subprocess(network_task, network_capability)
        restriction = get_active_restrictions()[0]

        override_restriction(
            operator_id="ops-admin",
            restriction_id=restriction.restriction_id,
            reason="Temporary supervised recovery.",
            override_mode="allow",
            expires_at="2026-04-14T00:20:00+00:00",
            trace_id="trace:override",
        )
        updated = get_restriction(restriction.restriction_id)
        capability = check_capability("BASIC_COGNITIVE_EXECUTION", "COGNITIVE")
        history = get_restriction_history(restriction.restriction_id)

        self.assertEqual(updated.status, "OVERRIDDEN")
        self.assertEqual(capability.mode, "allow")
        self.assertGreaterEqual(len(history["operator_actions"]), 1)

        clear_restriction(
            operator_id="ops-admin",
            restriction_id=restriction.restriction_id,
            reason="Clear after override window.",
            trace_id="trace:clear",
        )
        cleared = get_restriction(restriction.restriction_id)
        self.assertEqual(cleared.status, "CLEARED")

    def test_invalid_operator_action_requires_reason_and_existing_target(self):
        from assistant_os.mso.operator_actions import acknowledge_restriction

        with self.assertRaises(ValueError):
            acknowledge_restriction(operator_id="ops-reviewer", restriction_id="missing", reason="")

    def test_diagnostics_expose_restrictions_and_operator_actions(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess
        from assistant_os.mso.diagnostics import get_mso_diagnostics
        from assistant_os.mso.operator_actions import acknowledge_restriction
        from assistant_os.mso.restrictions import get_active_restrictions

        run_task_in_subprocess(self._network_task(), self._network_capability())
        restriction = get_active_restrictions()[0]
        acknowledge_restriction(
            operator_id="ops-reviewer",
            restriction_id=restriction.restriction_id,
            reason="Seen by operator.",
            trace_id="trace:ack",
        )

        diagnostics = get_mso_diagnostics()
        self.assertGreaterEqual(len(diagnostics["active_restrictions"]), 1)
        self.assertGreaterEqual(len(diagnostics["recent_operator_actions"]), 1)
        self.assertGreaterEqual(len(diagnostics["triggered_responses"]), 1)
        self.assertEqual(diagnostics["active_restrictions"][0]["review_state"], "acknowledged")


if __name__ == "__main__":
    unittest.main()
