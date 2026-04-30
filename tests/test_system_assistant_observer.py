"""Tests for assistant_os.system_assistant.observer.

Verifies:
1. observe_system() returns a snapshot dict.
2. Source failure does not raise; it produces warnings.
3. observe_system() does not call pipelines.
4. observe_system() does not call agent entrypoints.
5. observe_system() does not write audit records.
6. observe_system() does not mutate ExecutionRegistry.
7. observe_system() does not produce execution_mode, GovernanceVerdict, or PolicyDecision.
8. Snapshot can include partial state when some sources are unavailable.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestObserveSystemReturnsSnapshot(unittest.TestCase):
    """observe_system() returns a non-empty dict with required keys."""

    def setUp(self) -> None:
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        clear_operational_mode_override()
        reset_task_registry()
        reset_dynamic_capabilities()

    def test_returns_dict(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertIsInstance(snapshot, dict)

    def test_snapshot_has_required_keys(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertIn("generated_at", snapshot)
        self.assertIn("status", snapshot)

    def test_snapshot_status_is_string(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertIsInstance(snapshot["status"], str)

    def test_snapshot_generated_at_is_string(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertIsInstance(snapshot["generated_at"], str)
        self.assertGreater(len(snapshot["generated_at"]), 0)

    def test_snapshot_warnings_is_list(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertIn("warnings", snapshot)
        self.assertIsInstance(snapshot["warnings"], list)


class TestObserveSystemOperationalMode(unittest.TestCase):
    """Snapshot reflects current operational_mode from the read-only source."""

    def setUp(self) -> None:
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        clear_operational_mode_override()
        reset_task_registry()
        reset_dynamic_capabilities()

    def test_operational_mode_present(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertIn("operational_mode", snapshot)

    def test_operational_mode_reflects_override(self) -> None:
        from assistant_os.mso.system_state import set_operational_mode
        from assistant_os.system_assistant.observer import observe_system
        set_operational_mode("RESTRICTED", reason="test")
        snapshot = observe_system()
        self.assertEqual(snapshot["operational_mode"], "RESTRICTED")

    def test_operational_mode_none_when_no_override(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        # No override set — value is None or a derived mode string, never raises.
        mode = snapshot["operational_mode"]
        self.assertTrue(mode is None or isinstance(mode, str))


class TestObserveSystemAgentsSummary(unittest.TestCase):
    """Snapshot includes agent registry summary (read-only)."""

    def test_agents_summary_present(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertIn("agents", snapshot)

    def test_agents_summary_is_list(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertIsInstance(snapshot["agents"], list)

    def test_agents_summary_entries_have_name(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        for entry in snapshot["agents"]:
            self.assertIn("name", entry)

    def test_agents_entrypoints_not_called(self) -> None:
        """Ensure observe_system() reads agent metadata but never calls entrypoints."""
        call_tracker = []

        def tracking_entrypoint(request: object) -> object:  # noqa: ANN001
            call_tracker.append(request)
            return {}

        with patch(
            "assistant_os.agents.registry.AGENT_REGISTRY",
            {
                "test_agent": {
                    "name": "test_agent",
                    "domain": "TEST",
                    "version": "0.0.1",
                    "description": "Test agent for observer tests.",
                    "input_contract": "TestRequest",
                    "output_contract": "TestResult",
                    "requires_review": False,
                    "capability_scope": [],
                    "entrypoint": tracking_entrypoint,
                }
            },
        ):
            from assistant_os.system_assistant.observer import observe_system
            observe_system()

        self.assertEqual(call_tracker, [], "Agent entrypoints must never be called by observe_system()")


class TestObserveSystemCapabilitiesSummary(unittest.TestCase):
    """Snapshot includes capabilities summary (read-only)."""

    def test_capabilities_present(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertIn("capabilities", snapshot)

    def test_capabilities_is_list(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertIsInstance(snapshot["capabilities"], list)


class TestObserveSystemFailSoft(unittest.TestCase):
    """Source failures produce warnings, not exceptions."""

    def test_agent_source_failure_produces_warning_not_exception(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        with patch(
            "assistant_os.system_assistant.observer._read_agents_summary",
            side_effect=RuntimeError("simulated registry failure"),
        ):
            snapshot = observe_system()  # must not raise
        self.assertIsInstance(snapshot, dict)
        self.assertTrue(
            any("agent" in w.lower() for w in snapshot.get("warnings", [])),
            f"Expected agent-related warning, got: {snapshot.get('warnings')}",
        )

    def test_capabilities_source_failure_produces_warning_not_exception(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        with patch(
            "assistant_os.system_assistant.observer._read_capabilities_summary",
            side_effect=RuntimeError("simulated capability failure"),
        ):
            snapshot = observe_system()  # must not raise
        self.assertIsInstance(snapshot, dict)
        self.assertTrue(
            any("capabilit" in w.lower() for w in snapshot.get("warnings", [])),
            f"Expected capability-related warning, got: {snapshot.get('warnings')}",
        )

    def test_mode_source_failure_produces_warning_not_exception(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        with patch(
            "assistant_os.system_assistant.observer._read_operational_mode",
            side_effect=RuntimeError("simulated mode failure"),
        ):
            snapshot = observe_system()  # must not raise
        self.assertIsInstance(snapshot, dict)
        self.assertTrue(
            any("mode" in w.lower() or "operational" in w.lower() for w in snapshot.get("warnings", [])),
            f"Expected mode-related warning, got: {snapshot.get('warnings')}",
        )

    def test_tasks_source_failure_produces_warning_not_exception(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        with patch(
            "assistant_os.system_assistant.observer._read_tasks_summary",
            side_effect=RuntimeError("simulated task registry failure"),
        ):
            snapshot = observe_system()  # must not raise
        self.assertIsInstance(snapshot, dict)
        self.assertTrue(
            any("task" in w.lower() for w in snapshot.get("warnings", [])),
            f"Expected task-related warning, got: {snapshot.get('warnings')}",
        )

    def test_total_failure_returns_unavailable_snapshot(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        with (
            patch(
                "assistant_os.system_assistant.observer._read_operational_mode",
                side_effect=RuntimeError("total failure"),
            ),
            patch(
                "assistant_os.system_assistant.observer._read_agents_summary",
                side_effect=RuntimeError("total failure"),
            ),
            patch(
                "assistant_os.system_assistant.observer._read_capabilities_summary",
                side_effect=RuntimeError("total failure"),
            ),
            patch(
                "assistant_os.system_assistant.observer._read_tasks_summary",
                side_effect=RuntimeError("total failure"),
            ),
        ):
            snapshot = observe_system()
        self.assertIsInstance(snapshot, dict)
        self.assertGreater(len(snapshot.get("warnings", [])), 0)

    def test_partial_state_when_some_sources_unavailable(self) -> None:
        """Snapshot contains data from working sources even if others fail."""
        from assistant_os.system_assistant.observer import observe_system
        with patch(
            "assistant_os.system_assistant.observer._read_agents_summary",
            side_effect=RuntimeError("agent source down"),
        ):
            snapshot = observe_system()
        # capabilities should still be present
        self.assertIn("capabilities", snapshot)
        # warnings should note agent failure
        self.assertTrue(any("agent" in w.lower() for w in snapshot.get("warnings", [])))


class TestObserveSystemNoPipelines(unittest.TestCase):
    """observe_system() must never call pipelines or the orchestrator."""

    def test_does_not_call_handle_request(self) -> None:
        handle_mock = MagicMock()
        with patch("assistant_os.core.orchestrator.handle_request", handle_mock):
            from assistant_os.system_assistant.observer import observe_system
            observe_system()
        handle_mock.assert_not_called()

    def test_does_not_invoke_code_pipeline(self) -> None:
        mock_pipeline = MagicMock()
        with patch.dict(
            "sys.modules",
            {"assistant_os.pipelines.code_pipeline": mock_pipeline},
        ):
            from assistant_os.system_assistant.observer import observe_system
            observe_system()
        # The pipeline module was never accessed through observe_system
        self.assertFalse(mock_pipeline.execute.called if hasattr(mock_pipeline, "execute") else False)


class TestObserveSystemNoAuditWrites(unittest.TestCase):
    """observe_system() must not write to any audit store."""

    def test_does_not_write_to_audit_store(self) -> None:
        from assistant_os.system_assistant.observer import observe_system

        with patch("assistant_os.storage.mso_store.persist_worker_security_event") as audit_mock:
            observe_system()
        audit_mock.assert_not_called()


class TestObserveSystemNoForbiddenOutputs(unittest.TestCase):
    """Snapshot must not contain execution_mode, GovernanceVerdict, or PolicyDecision."""

    def test_no_execution_mode_in_snapshot(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertNotIn("execution_mode", snapshot)

    def test_no_governance_verdict_in_snapshot(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertNotIn("governance_verdict", snapshot)
        self.assertNotIn("GovernanceVerdict", snapshot)

    def test_no_policy_decision_in_snapshot(self) -> None:
        from assistant_os.system_assistant.observer import observe_system
        snapshot = observe_system()
        self.assertNotIn("policy_decision", snapshot)
        self.assertNotIn("PolicyDecision", snapshot)


class TestObserveSystemNoStatesMutation(unittest.TestCase):
    """observe_system() must not mutate ExecutionRegistry or any system state."""

    def setUp(self) -> None:
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        clear_operational_mode_override()
        reset_task_registry()

    def test_operational_mode_not_mutated(self) -> None:
        from assistant_os.mso.system_state import get_operational_mode_override
        from assistant_os.system_assistant.observer import observe_system
        before_mode, _ = get_operational_mode_override()
        observe_system()
        after_mode, _ = get_operational_mode_override()
        self.assertEqual(before_mode, after_mode)

    def test_task_registry_not_mutated(self) -> None:
        from assistant_os.mso.task_registry import list_tasks
        from assistant_os.system_assistant.observer import observe_system
        tasks_before = list_tasks()
        observe_system()
        tasks_after = list_tasks()
        self.assertEqual(len(tasks_before), len(tasks_after))


if __name__ == "__main__":
    unittest.main()
