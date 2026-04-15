import unittest
from unittest.mock import patch


class TestTaskRegistryLifecycle(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_dynamic_capabilities()
        clear_operational_mode_override()
        reset_task_registry()
        reset_trace_aggregator()

    def test_task_lifecycle_registration_and_completion(self):
        from assistant_os.contracts import now_iso
        from assistant_os.mso.contracts import TaskRecord
        from assistant_os.mso.task_registry import get_recent_transitions, list_tasks, register_task, transition_task

        record = TaskRecord(
            task_id="task-1",
            context_id="ctx-1",
            trace_id="trace-1",
            plan_id="plan-1",
            domain="WORK",
            status="active",
            created_at=now_iso(),
            updated_at=now_iso(),
            last_known_action="WORK_QUERY",
        )
        register_task(record)
        transition_task("task-1", to_status="completed", reason="work_query", result_type="work_query")

        completed = list_tasks(status="completed")
        transitions = get_recent_transitions(limit=5)

        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].task_id, "task-1")
        self.assertEqual(transitions[0].to_status, "completed")
        self.assertEqual(transitions[-1].to_status, "active")


class TestTraceAggregator(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_dynamic_capabilities()
        clear_operational_mode_override()
        reset_trace_aggregator()

    def test_trace_chain_reconstructs_request_decision_and_result(self):
        from assistant_os.contracts import now_iso
        from assistant_os.mso.contracts import DeterministicDecisionTrace
        from assistant_os.mso.trace_aggregator import begin_trace_chain, finalize_trace_chain, get_trace_chain

        decision = DeterministicDecisionTrace(
            decision_ref="decision:plan-1",
            context_id="ctx-1",
            trace_id="trace-1",
            plan_id="plan-1",
            domain="WORK",
            action="WORK_QUERY",
            execution_mode="auto",
            operation="WORK_QUERY",
            preview="Consultar tareas",
            created_at=now_iso(),
            advisory_trace_ref="advisory:plan-1",
        )
        begin_trace_chain(
            task_id="task-1",
            context_id="ctx-1",
            trace_id="trace-1",
            plan_id="plan-1",
            request_text="dame mis tareas",
            operation="WORK_QUERY",
            domain="WORK",
            action="WORK_QUERY",
            execution_mode="auto",
            created_at=now_iso(),
            advisory_trace={"final_action": "WORK_QUERY"},
            decision_trace=decision,
        )
        finalize_trace_chain(
            "plan-1",
            executed=True,
            result={"ok": True, "result_type": "work_query", "plan_id": "plan-1"},
            execution_id="plan-1",
        )

        chain = get_trace_chain("plan-1")
        self.assertIsNotNone(chain)
        self.assertEqual(chain.request_text, "dame mis tareas")
        self.assertEqual(chain.execution["executed"], True)
        self.assertEqual(chain.result["result_type"], "work_query")


class TestSystemStateSnapshot(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_dynamic_capabilities()
        clear_operational_mode_override()
        reset_task_registry()
        reset_trace_aggregator()

    def test_snapshot_counts_match_registry_state(self):
        from assistant_os.contracts import now_iso
        from assistant_os.mso.contracts import TaskRecord
        from assistant_os.mso.system_state import build_system_state_snapshot
        from assistant_os.mso.task_registry import register_task

        ts = now_iso()
        register_task(TaskRecord("active-1", "ctx-a", "tr-a", "pl-a", "WORK", "active", ts, ts, "WORK_QUERY"))
        register_task(TaskRecord("pending-1", "ctx-p", "tr-p", "pl-p", "CODE", "pending", ts, ts, "CODE_FIX"))
        register_task(TaskRecord("blocked-1", "ctx-b", "tr-b", "pl-b", "UNKNOWN", "blocked", ts, ts, "COMMAND"))

        snapshot = build_system_state_snapshot()
        domains = {item.domain: item for item in snapshot.domain_status_summary}

        self.assertEqual(len(snapshot.active_tasks), 1)
        self.assertEqual(len(snapshot.pending_tasks), 1)
        self.assertEqual(len(snapshot.blocked_tasks), 1)
        self.assertEqual(domains["WORK"].active, 1)
        self.assertEqual(domains["CODE"].pending, 1)

    def test_snapshot_exposes_operational_mode_revocations_and_anomalies(self):
        from assistant_os.contracts import now_iso
        from assistant_os.mso.capability_registry import revoke_capability
        from assistant_os.mso.contracts import (
            DeterministicDecisionTrace,
            GovernanceConstraint,
            GovernanceDecision,
            GovernanceIntervention,
            GovernanceReason,
            TaskRecord,
        )
        from assistant_os.mso.system_state import build_system_state_snapshot, set_operational_mode
        from assistant_os.mso.task_registry import register_task
        from assistant_os.mso.trace_aggregator import begin_trace_chain

        ts = now_iso()
        set_operational_mode("RESTRICTED", reason="manual incident response")
        revoke_capability(action="WORK_QUERY", domain="WORK", reason="manual revoke")
        register_task(TaskRecord("failed-1", "ctx-f1", "tr-f1", "pl-f1", "WORK", "failed", ts, ts, "WORK_UPDATE"))
        register_task(TaskRecord("failed-2", "ctx-f2", "tr-f2", "pl-f2", "WORK", "failed", ts, ts, "WORK_UPDATE"))

        decision = GovernanceDecision(
            governance_ref="governance:test",
            action="BLOCK",
            target_domain="WORK",
            target_action="WORK_QUERY",
            effective_execution_mode="blocked",
            risk_level="medium",
            justification="blocked",
            reasons=[GovernanceReason(code="capability_revoked", detail="manual revoke")],
            constraints=[GovernanceConstraint(kind="degrade", value="restricted")],
            interventions=[GovernanceIntervention(kind="revoke_capability", value="WORK_QUERY", reason="manual revoke")],
            capability_mode="deny",
            base_execution_mode="auto",
            operational_mode="RESTRICTED",
            created_at=ts,
        )
        begin_trace_chain(
            task_id="task-state",
            context_id="ctx-state",
            trace_id="trace-state",
            plan_id="plan-state",
            request_text="dame mis tareas",
            operation="WORK_QUERY",
            domain="WORK",
            action="WORK_QUERY",
            execution_mode="auto",
            created_at=ts,
            advisory_trace=None,
            decision_trace=DeterministicDecisionTrace(
                decision_ref="decision:plan-state",
                context_id="ctx-state",
                trace_id="trace-state",
                plan_id="plan-state",
                domain="WORK",
                action="WORK_QUERY",
                execution_mode="auto",
                operation="WORK_QUERY",
                preview="Consultar tareas",
                created_at=ts,
            ),
            governance_trace=None,
            governance_decision=decision,
        )

        snapshot = build_system_state_snapshot()

        self.assertEqual(snapshot.operational_mode, "RESTRICTED")
        self.assertEqual(len(snapshot.active_capability_revocations), 1)
        self.assertGreaterEqual(len(snapshot.recent_anomaly_signals), 1)


class TestOrchestratorStatePublication(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_dynamic_capabilities()
        clear_operational_mode_override()
        reset_task_registry()
        reset_trace_aggregator()

    def _req(self, text: str) -> dict:
        from assistant_os.contracts import normalize_request

        return normalize_request(text=text)

    @patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None)
    @patch(
        "assistant_os.pipelines.work_pipeline.execute",
        return_value={
            "ok": True,
            "result_type": "work_query",
            "domain": "WORK",
            "message": "ok",
            "data": {"items": [], "total": 0},
            "error": None,
        },
    )
    @patch(
        "assistant_os.classifier.classify_text",
        return_value={
            "domain": "WORK",
            "operation": "WORK_QUERY",
            "confidence": 0.95,
            "alternatives": [],
            "needs_confirmation": False,
            "reason": "test",
            "type": "",
            "cognitive_load": "",
            "impact": "",
            "next_action": "",
        },
    )
    def test_auto_execution_publishes_completed_task_and_trace(self, _mock_classify, _mock_work_execute, _mock_advisory):
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.mso.governance_surface import get_governance_summary, get_trace_view
        from assistant_os.mso.task_registry import list_tasks

        result = handle_request(self._req("dame mis tareas"))

        self.assertEqual(result["result_type"], "work_query")
        tasks = list_tasks(status="completed")
        self.assertEqual(len(tasks), 1)
        trace = get_trace_view(tasks[0].plan_id)
        summary = get_governance_summary()

        self.assertIsNotNone(trace)
        self.assertEqual(trace.result["result_type"], "work_query")
        self.assertEqual(summary.active_count, 0)
        self.assertEqual(summary.current_state, "idle")

    @patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None)
    @patch(
        "assistant_os.classifier.classify_text",
        return_value={
            "domain": "WORK",
            "operation": "WORK_CREATE",
            "confidence": 0.9,
            "alternatives": [],
            "needs_confirmation": True,
            "reason": "test",
            "type": "",
            "cognitive_load": "",
            "impact": "",
            "next_action": "",
        },
    )
    def test_confirmation_path_publishes_pending_task(self, _mock_classify, _mock_advisory):
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.mso.governance_surface import get_pending_tasks

        result = handle_request(self._req("Crea una tarea: Titulo: Test. Proyecto: X."))

        self.assertEqual(result["result_type"], "plan_confirmation_required")
        pending = get_pending_tasks()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].status, "pending")
