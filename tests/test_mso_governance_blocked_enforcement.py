"""
MSO Governance BLOCKED Execution Gate — Enforcement Validation

This test module directly addresses the AUTHORITY_PATH_AUDIT finding:
"MSO Governance execution_mode=BLOCKED: Effect on execution NOT verified"

Tests verify that when MSO Governance returns execution_mode = BLOCKED:
1. The orchestrator does NOT invoke any domain pipeline
2. The response is plan_generated (not execution result)
3. No capability token is consumed (non-execution path)
"""

import unittest
from unittest.mock import patch, MagicMock

from assistant_os.contracts import (
    normalize_request,
    RESULT_TYPE_PLAN_GENERATED,
    RESULT_TYPE_WORK_QUERY,
    EXECUTION_MODE_AUTO,
    EXECUTION_MODE_BLOCKED,
)
from assistant_os.core.orchestrator import handle_request
from assistant_os.mso.contracts import (
    GovernanceDecision,
    GovernanceReason,
    GovernanceConstraint,
    GovernanceIntervention,
)


class TestMSOGovernanceBlockedEnforcement(unittest.TestCase):
    """
    CRITICAL TEST: Verify that MSO Governance BLOCKED execution_mode
    genuinely prevents domain pipeline execution.
    """

    def setUp(self):
        """Clean up MSO state before each test."""
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

    def _create_governance_blocked(self) -> GovernanceDecision:
        """Factory: create a GovernanceDecision with execution_mode=BLOCKED."""
        return GovernanceDecision(
            governance_ref="gov-test-blocked-001",
            action="BLOCK",
            target_domain="WORK",
            target_action="WORK_QUERY",
            effective_execution_mode=EXECUTION_MODE_BLOCKED,
            risk_level="high",
            justification="Test: governance blocks execution",
            reasons=[
                GovernanceReason(code="test_block", detail="Test governance BLOCK"),
            ],
            constraints=[],
            interventions=[
                GovernanceIntervention(
                    kind="test_block", value="*", reason="Test BLOCK"
                ),
            ],
            capability_mode="allow",
            base_execution_mode="auto",
            operational_mode="normal",
            created_at="2026-05-08T00:00:00+00:00",
        )

    def _create_governance_auto(self) -> GovernanceDecision:
        """Factory: create a GovernanceDecision with execution_mode=AUTO."""
        return GovernanceDecision(
            governance_ref="gov-test-auto-001",
            action="ALLOW",
            target_domain="WORK",
            target_action="WORK_QUERY",
            effective_execution_mode=EXECUTION_MODE_AUTO,
            risk_level="low",
            justification="Test: governance allows auto execution",
            reasons=[
                GovernanceReason(code="test_auto", detail="Test governance AUTO"),
            ],
            constraints=[],
            interventions=[],
            capability_mode="allow",
            base_execution_mode="auto",
            operational_mode="normal",
            created_at="2026-05-08T00:00:00+00:00",
        )

    @patch("assistant_os.classifier.classify_text")
    @patch("assistant_os.core.orchestrator._evaluate_mso_governance")
    def test_governance_blocked_returns_plan_not_execution_result(
        self,
        mock_governance,
        mock_classify,
    ):
        """
        CRITICAL: When MSO governance returns execution_mode=BLOCKED,
        the response is plan_generated (not a domain execution result).

        This proves that execution_mode=BLOCKED genuinely blocks execution,
        not just marks a flag.
        """
        mock_classify.return_value = {
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
        }
        mock_governance.return_value = self._create_governance_blocked()

        req = normalize_request(text="dame mis tareas")
        result = handle_request(req)

        # Verify: result is PLAN_GENERATED, not execution result
        self.assertEqual(result["result_type"], RESULT_TYPE_PLAN_GENERATED)
        self.assertNotEqual(result["result_type"], RESULT_TYPE_WORK_QUERY)
        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["governance_blocked"])

    @patch("assistant_os.classifier.classify_text")
    @patch("assistant_os.core.orchestrator._evaluate_mso_governance")
    def test_governance_blocked_includes_governance_trace(
        self,
        mock_governance,
        mock_classify,
    ):
        """Governance BLOCKED result includes governance_trace for audit."""
        mock_classify.return_value = {
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
        }
        mock_governance.return_value = self._create_governance_blocked()

        req = normalize_request(text="dame mis tareas")
        result = handle_request(req)

        # Verify: governance_trace shows the BLOCK action
        self.assertIn("governance_trace", result["data"])
        trace = result["data"]["governance_trace"]
        self.assertEqual(trace["action"], "BLOCK")
        self.assertEqual(trace["effective_execution_mode"], "blocked")

    @patch("assistant_os.classifier.classify_text")
    @patch("assistant_os.core.orchestrator._evaluate_mso_governance")
    @patch("assistant_os.capabilities.token_verifier.consume_token")
    def test_governance_blocked_does_not_consume_token(
        self,
        mock_consume_token,
        mock_governance,
        mock_classify,
    ):
        """Non-execution paths (BLOCKED) should NOT consume capability token."""
        mock_classify.return_value = {
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
        }
        mock_governance.return_value = self._create_governance_blocked()

        req = normalize_request(text="dame mis tareas")
        result = handle_request(req)

        # Verify: token was NOT consumed (non-execution path)
        mock_consume_token.assert_not_called()


class TestMSOGovernanceAutoExecutes(unittest.TestCase):
    """
    Contrast test: verify that execution_mode=AUTO DOES execute pipeline.
    This confirms BLOCKED is special (not just default behavior).
    """

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

    def _create_governance_auto(self) -> GovernanceDecision:
        """Factory: create a GovernanceDecision with execution_mode=AUTO."""
        return GovernanceDecision(
            governance_ref="gov-test-auto-001",
            action="ALLOW",
            target_domain="WORK",
            target_action="WORK_QUERY",
            effective_execution_mode=EXECUTION_MODE_AUTO,
            risk_level="low",
            justification="Test: governance allows auto execution",
            reasons=[
                GovernanceReason(code="test_auto", detail="Test governance AUTO"),
            ],
            constraints=[],
            interventions=[],
            capability_mode="allow",
            base_execution_mode="auto",
            operational_mode="normal",
            created_at="2026-05-08T00:00:00+00:00",
        )

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text")
    @patch("assistant_os.core.orchestrator._evaluate_mso_governance")
    def test_governance_auto_executes_pipeline(
        self,
        mock_governance,
        mock_classify,
        mock_query,
        mock_notion,
    ):
        """Contrast: governance AUTO DOES execute pipeline and returns execution result."""
        mock_classify.return_value = {
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
        }
        mock_governance.return_value = self._create_governance_auto()

        req = normalize_request(text="dame mis tareas")
        result = handle_request(req)

        # Verify: pipeline executed (result_type is work_query, not plan_generated)
        self.assertEqual(result["result_type"], RESULT_TYPE_WORK_QUERY)
        self.assertNotEqual(result["result_type"], RESULT_TYPE_PLAN_GENERATED)

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text")
    @patch("assistant_os.core.orchestrator._evaluate_mso_governance")
    @patch("assistant_os.capabilities.token_verifier.consume_token")
    def test_governance_auto_consumes_token(
        self,
        mock_consume_token,
        mock_governance,
        mock_classify,
        mock_query,
        mock_notion,
    ):
        """Execution paths (AUTO) SHOULD consume token."""
        mock_classify.return_value = {
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
        }
        mock_governance.return_value = self._create_governance_auto()

        req = normalize_request(text="dame mis tareas")
        result = handle_request(req)

        # Verify: token WAS consumed (execution path)
        mock_consume_token.assert_called_once()


if __name__ == "__main__":
    unittest.main()
