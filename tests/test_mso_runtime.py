import unittest


class TestMsoRuntime(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator
        from assistant_os.storage.mso_store import clear_mso_store

        reset_dynamic_capabilities()
        clear_operational_mode_override()
        reset_task_registry()
        reset_trace_aggregator()
        clear_mso_store()

    def test_runtime_delegates_cognitive_request_and_persists_artifacts(self):
        from assistant_os.contracts import RESULT_TYPE_COGNITIVE_EXECUTION
        from assistant_os.mso.runtime import run_mso_cycle
        from assistant_os.storage.mso_store import list_recent_delegations, list_recent_intents, list_recent_reports

        bundle = run_mso_cycle(
            text="please summarize current system state and run a diagnostic summary",
            session_id="session-runtime-1",
            user_request_ref="request:runtime-1",
        )

        self.assertEqual(bundle["sovereign_intent"]["delegation_recommendation"], "delegate_basic_cognitive_execution")
        self.assertEqual(bundle["result"]["result_type"], RESULT_TYPE_COGNITIVE_EXECUTION)
        self.assertIn("persistence_refs", bundle["result"]["data"])
        self.assertEqual(len(list_recent_intents()), 1)
        self.assertEqual(len(list_recent_delegations()), 1)
        self.assertEqual(len(list_recent_reports()), 1)

    def test_runtime_non_delegated_request_translates_to_plain_canonical_request(self):
        from assistant_os.mso.runtime import run_mso_cycle

        bundle = run_mso_cycle(
            text="dame mis tareas pendientes",
            session_id="session-runtime-2",
            user_request_ref="request:runtime-2",
        )

        self.assertEqual(bundle["sovereign_intent"]["delegation_recommendation"], "none")
        self.assertNotIn("action", bundle["canonical_request"]["metadata"])
        self.assertIn(bundle["result"]["result_type"], {"work_query", "plan_confirmation_required", "plan_generated"})

    def test_runtime_trace_continuity_contains_persistence_refs(self):
        from assistant_os.mso.governance_surface import get_trace_view
        from assistant_os.mso.runtime import run_mso_cycle

        bundle = run_mso_cycle(
            text="simulate system state summary diagnostic",
            session_id="session-runtime-3",
            user_request_ref="request:runtime-3",
        )
        plan_id = bundle["result"]["plan_id"]
        trace = get_trace_view(plan_id)

        self.assertIsNotNone(trace)
        self.assertTrue(trace.persistence_refs.get("intent"))
        self.assertTrue(trace.persistence_refs.get("delegation"))
        self.assertTrue(trace.persistence_refs.get("report"))
        self.assertTrue(trace.sovereign_cycle_ref)

    def test_runtime_persists_rejected_translation_without_dispatching_kernel(self):
        from assistant_os.mso.runtime import run_mso_cycle
        from assistant_os.storage.mso_store import list_recent_cycles, list_recent_translator_rejections

        bundle = run_mso_cycle(
            text="   ",
            session_id="session-runtime-reject",
            user_request_ref="request:runtime-reject",
        )

        self.assertIsNone(bundle["canonical_request"])
        self.assertIsNone(bundle["result"])
        self.assertEqual(bundle["translator_rejection"]["reason_code"], "empty_original_text")
        self.assertEqual(len(list_recent_translator_rejections()), 1)
        self.assertEqual(len(list_recent_cycles()), 1)

    def test_runtime_diagnostics_surface_reports_recent_cognitive_activity(self):
        from assistant_os.mso.diagnostics import get_mso_diagnostics
        from assistant_os.mso.runtime import run_mso_cycle

        run_mso_cycle(
            text="state diagnostic summary",
            session_id="session-runtime-4",
            user_request_ref="request:runtime-4",
        )
        diagnostics = get_mso_diagnostics()

        self.assertIn("operational_mode", diagnostics)
        self.assertGreaterEqual(len(diagnostics["recent_cycles"]), 1)
        self.assertGreaterEqual(len(diagnostics["recent_intents"]), 1)
        self.assertGreaterEqual(len(diagnostics["recent_delegations"]), 1)
        self.assertGreaterEqual(len(diagnostics["recent_reports"]), 1)
        self.assertIn("store_status", diagnostics)
        self.assertIn("worker_runner_status", diagnostics)
        self.assertIn("current_restriction_level", diagnostics)

    def test_diagnostics_show_triggered_security_responses(self):
        from assistant_os.executors.cognitive_worker_runner import run_task_in_subprocess
        from assistant_os.mso.diagnostics import get_mso_diagnostics
        from assistant_os.mso.contracts import DelegationTask, ExecutionCapability

        task = DelegationTask(
            task_id="diag-task-1",
            origin_intent_id="diag-intent-1",
            task_type="BASIC_COGNITIVE_EXECUTION",
            task_goal="Trigger network denial for diagnostics.",
            allowed_operations=["read_system_state"],
            input_refs=["request:diag"],
            scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True},
            requires_capability="BASIC_COGNITIVE_EXECUTION",
            expected_output_schema={"required_artifact_keys": []},
            expiry="2099-01-01T00:00:00+00:00",
            trace_id="trace:diag",
        )
        capability = ExecutionCapability(
            capability_id="diag-cap-1",
            task_id="diag-task-1",
            execution_class="BASIC_COGNITIVE_EXECUTION",
            allowed_operations=["read_system_state"],
            scope={"domain": "COGNITIVE", "timeout_ms": 200, "force_network_attempt": True},
            issued_at="2026-04-14T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
            issued_by="kernel",
            trace_id="trace:diag",
        )

        run_task_in_subprocess(task, capability)
        diagnostics = get_mso_diagnostics()

        self.assertGreaterEqual(len(diagnostics["triggered_responses"]), 1)
        self.assertIn("network_denied", diagnostics["security_event_counters"])
        self.assertEqual(diagnostics["current_restriction_level"]["source"], "revocation")

    def test_runtime_trace_contains_worker_security_events(self):
        from assistant_os.mso.governance_surface import get_trace_view
        from assistant_os.mso.runtime import run_mso_cycle

        bundle = run_mso_cycle(
            text="please summarize current system state and run a diagnostic summary",
            session_id="session-runtime-sec-1",
            user_request_ref="request:runtime-sec-1",
        )

        trace = get_trace_view(bundle["result"]["plan_id"])
        self.assertIsNotNone(trace)
        self.assertTrue(trace.worker_security_event_refs)
        self.assertTrue(any(item["event_type"] == "worker_started" for item in trace.worker_security_events))


if __name__ == "__main__":
    unittest.main()
