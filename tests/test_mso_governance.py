import unittest
from unittest.mock import patch


class TestGovernanceEngine(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_task_registry()
        reset_trace_aggregator()

    def test_low_risk_allow_keeps_auto_execution(self):
        from assistant_os.mso.contracts import GovernanceReason, RiskEvaluation
        from assistant_os.mso.governance_engine import evaluate_governance

        decision = evaluate_governance(
            action="WORK_QUERY",
            domain="WORK",
            base_execution_mode="auto",
            risk=RiskEvaluation(
                level="low",
                reasons=[GovernanceReason(code="base_risk", detail="low")],
                base_risk="low",
            ),
            created_at="2026-04-13T00:00:00+00:00",
        )

        self.assertEqual(decision.action, "ALLOW")
        self.assertEqual(decision.effective_execution_mode, "auto")

    def test_medium_risk_auto_requires_confirmation(self):
        from assistant_os.mso.contracts import GovernanceReason, RiskEvaluation
        from assistant_os.mso.governance_engine import evaluate_governance

        decision = evaluate_governance(
            action="FIN_EXPENSE",
            domain="FIN",
            base_execution_mode="auto",
            risk=RiskEvaluation(
                level="medium",
                reasons=[GovernanceReason(code="base_risk", detail="medium")],
                base_risk="medium",
            ),
            created_at="2026-04-13T00:00:00+00:00",
        )

        self.assertEqual(decision.action, "REQUIRE_CONFIRMATION")
        self.assertEqual(decision.effective_execution_mode, "confirm")

    def test_high_risk_is_blocked(self):
        from assistant_os.mso.contracts import GovernanceReason, RiskEvaluation
        from assistant_os.mso.governance_engine import evaluate_governance

        decision = evaluate_governance(
            action="WORK_DELETE",
            domain="WORK",
            base_execution_mode="confirm",
            risk=RiskEvaluation(
                level="high",
                reasons=[GovernanceReason(code="destructive_action", detail="delete")],
                base_risk="high",
            ),
            created_at="2026-04-13T00:00:00+00:00",
        )

        self.assertEqual(decision.action, "BLOCK")
        self.assertEqual(decision.effective_execution_mode, "blocked")

    def test_capability_denial_blocks_even_if_policy_is_permissive(self):
        from assistant_os.mso.contracts import GovernanceReason, RiskEvaluation
        from assistant_os.mso.governance_engine import evaluate_governance

        decision = evaluate_governance(
            action="COMMAND",
            domain="UNKNOWN",
            base_execution_mode="auto",
            risk=RiskEvaluation(
                level="low",
                reasons=[GovernanceReason(code="base_risk", detail="low")],
                base_risk="low",
            ),
            created_at="2026-04-13T00:00:00+00:00",
        )

        self.assertEqual(decision.action, "BLOCK")
        self.assertEqual(decision.capability_mode, "deny")

    def test_anomaly_degrades_auto_to_confirmation(self):
        from assistant_os.mso.contracts import GovernanceReason, RiskEvaluation
        from assistant_os.mso.governance_engine import evaluate_governance

        decision = evaluate_governance(
            action="WORK_QUERY",
            domain="WORK",
            base_execution_mode="auto",
            risk=RiskEvaluation(
                level="low",
                reasons=[GovernanceReason(code="recent_failures_observed", detail="observed")],
                base_risk="low",
                recent_failure_count=2,
                anomaly_detected=True,
            ),
            created_at="2026-04-13T00:00:00+00:00",
        )

        self.assertEqual(decision.action, "DEGRADE")
        self.assertEqual(decision.effective_execution_mode, "confirm")


class TestGovernanceOrchestratorIntegration(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_task_registry()
        reset_trace_aggregator()

    def _request(self, text: str) -> dict:
        from assistant_os.contracts import normalize_request

        return normalize_request(text=text)

    @patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None)
    @patch(
        "assistant_os.classifier.classify_text",
        return_value={
            "domain": "WORK",
            "operation": "WORK_DELETE",
            "confidence": 0.95,
            "alternatives": [],
            "needs_confirmation": True,
            "reason": "test",
            "type": "",
            "cognitive_load": "",
            "impact": "",
            "next_action": "",
        },
    )
    def test_high_risk_block_prevents_execution_and_exposes_trace(self, _mock_classify, _mock_advisory):
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.mso.governance_surface import get_recent_governance

        result = handle_request(self._request("borra la tarea demo"))

        self.assertEqual(result["result_type"], "plan_generated")
        self.assertTrue(result["data"]["governance_blocked"])
        self.assertEqual(result["data"]["governance_trace"]["action"], "BLOCK")
        recent = get_recent_governance(limit=1)
        self.assertEqual(recent[0].action, "BLOCK")

    @patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None)
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
    @patch(
        "assistant_os.core.orchestrator._evaluate_mso_governance",
    )
    def test_degrade_path_returns_confirmation_without_executing_pipeline(self, mock_governance, _mock_classify, _mock_advisory):
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.mso.contracts import GovernanceConstraint, GovernanceDecision, GovernanceReason

        mock_governance.return_value = GovernanceDecision(
            governance_ref="governance:test",
            action="DEGRADE",
            effective_execution_mode="confirm",
            risk_level="medium",
            justification="Degraded to confirmation.",
            reasons=[GovernanceReason(code="anomaly_degrade", detail="recent failures")],
            constraints=[GovernanceConstraint(kind="degrade", value="confirm_due_to_recent_failures")],
            capability_mode="allow",
            base_execution_mode="auto",
            created_at="2026-04-13T00:00:00+00:00",
        )

        result = handle_request(self._request("dame mis tareas"))

        self.assertEqual(result["result_type"], "plan_confirmation_required")
        self.assertEqual(result["data"]["governance_trace"]["action"], "DEGRADE")

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
    def test_allow_path_preserves_deterministic_execution(self, _mock_classify, _mock_execute, _mock_advisory):
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.mso.governance_surface import get_trace_view
        from assistant_os.mso.task_registry import list_tasks

        result = handle_request(self._request("dame mis tareas"))

        self.assertEqual(result["result_type"], "work_query")
        completed = list_tasks(status="completed")
        self.assertEqual(len(completed), 1)
        chain = get_trace_view(completed[0].plan_id)
        self.assertEqual(chain.governance_trace["action"], "ALLOW")
        self.assertEqual(chain.execution["executed"], True)


if __name__ == "__main__":
    unittest.main()
