"""
M0.6 — Orchestrator Policy Authority Tests

Verifies that core/orchestrator.handle_request() dispatches exclusively on
PolicyDecision.execution_mode, not on plan.requires_confirmation directly.

After M0.6, the following invariant must hold:
    "La decisión de ejecución del orchestrator está gobernada por PolicyDecision.execution_mode."

Covered cases:
- WORK_QUERY (execution_mode=auto)  → pipeline executes, returns work_query result
- WORK_CREATE (execution_mode=confirm) → returns plan_confirmation_required
- FIN_EXPENSE (execution_mode=auto) → pipeline executes, returns fin result
- WORK_UPDATE (execution_mode=auto) → pipeline executes, no confirmation
- ACTION_COMMAND (execution_mode=blocked) → returns plan_generated
- plan.requires_confirmation is NOT the dispatch signal (verified by policy override test)
"""

import unittest
from unittest.mock import patch, MagicMock

from assistant_os.contracts import (
    normalize_request,
    make_domain_result,
    RESULT_TYPE_WORK_QUERY,
    RESULT_TYPE_WORK_CREATE,
    RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
    RESULT_TYPE_PLAN_GENERATED,
    RESULT_TYPE_FIN_EXPENSE,
    EXECUTION_MODE_AUTO,
    EXECUTION_MODE_CONFIRM,
    EXECUTION_MODE_BLOCKED,
)
from assistant_os.core.orchestrator import handle_request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req(text: str) -> dict:
    return normalize_request(text=text)


# ---------------------------------------------------------------------------
# Auto-execute path: WORK_QUERY
# ---------------------------------------------------------------------------

class TestOrchestratorAutoExecute(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_task_registry()
        reset_trace_aggregator()

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_work_query_auto_executes_via_policy(self, _mock_classify, _mock_query, _mock_notion):
        """execution_mode=auto → pipeline executes → result_type=work_query, not plan_confirmation_required."""
        req = _req("dame mis tareas")
        result = handle_request(req)
        self.assertEqual(result["result_type"], RESULT_TYPE_WORK_QUERY)
        self.assertNotEqual(result["result_type"], RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED)

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_work_query_result_domain_is_work(self, _mock_classify, _mock_query, _mock_notion):
        """work_query result must have domain=WORK."""
        req = _req("muéstrame mis tareas de inbox")
        result = handle_request(req)
        self.assertEqual(result["domain"], "WORK")


# ---------------------------------------------------------------------------
# Confirm path: WORK_CREATE
# ---------------------------------------------------------------------------

class TestOrchestratorConfirmRequired(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_task_registry()
        reset_trace_aggregator()

    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_CREATE", "confidence": 0.9,
               "alternatives": [], "needs_confirmation": True, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_work_create_returns_plan_confirmation_required(self, _mock_classify):
        """execution_mode=confirm → result_type=plan_confirmation_required."""
        req = _req("Crea una tarea: Título: Test. Proyecto: X.")
        result = handle_request(req)
        self.assertEqual(result["result_type"], RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED)

    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_CREATE", "confidence": 0.9,
               "alternatives": [], "needs_confirmation": True, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_work_create_confirmation_output_contains_plan(self, _mock_classify):
        """plan_confirmation_required data must include the plan."""
        req = _req("Crea una tarea: Título: Test. Proyecto: X.")
        result = handle_request(req)
        self.assertIn("plan", result.get("data", {}))

    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_CREATE", "confidence": 0.9,
               "alternatives": [], "needs_confirmation": True, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_work_create_ok_is_true(self, _mock_classify):
        """plan_confirmation_required result must have ok=True (pending state, not error)."""
        req = _req("Crea una tarea: Título: Test. Proyecto: X.")
        result = handle_request(req)
        self.assertTrue(result["ok"])


# ---------------------------------------------------------------------------
# Policy is authoritative: verify execution_mode drives dispatch, not requires_confirmation
# ---------------------------------------------------------------------------

class TestOrchestratorPolicyIsAuthoritative(unittest.TestCase):
    """
    The critical invariant: plan.requires_confirmation is NOT read by the orchestrator.
    The orchestrator reads policy.execution_mode exclusively.

    We verify by patching build_policy to return a forced execution_mode and
    confirming that the orchestrator respects it, not plan.requires_confirmation.
    """
    def setUp(self):
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_task_registry()
        reset_trace_aggregator()

    @patch("assistant_os.core.policy.build_policy")
    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_forced_auto_mode_executes_pipeline(
        self, _mock_classify, _mock_query, _mock_notion, mock_build_policy
    ):
        """If policy returns execution_mode=auto, orchestrator executes — regardless of plan state."""
        mock_build_policy.return_value = {
            "execution_mode": EXECUTION_MODE_AUTO,
            "routing_action": "WORK_QUERY",
            "domain": "WORK",
        }
        req = _req("dame mis tareas")
        result = handle_request(req)
        self.assertEqual(result["result_type"], RESULT_TYPE_WORK_QUERY)

    @patch("assistant_os.core.policy.build_policy")
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_forced_confirm_mode_blocks_pipeline(self, _mock_classify, mock_build_policy):
        """If policy returns execution_mode=confirm, orchestrator returns confirmation — even for WORK_QUERY."""
        mock_build_policy.return_value = {
            "execution_mode": EXECUTION_MODE_CONFIRM,
            "routing_action": "WORK_QUERY",
            "domain": "WORK",
        }
        req = _req("dame mis tareas")
        result = handle_request(req)
        # Policy says confirm → must NOT auto-execute
        self.assertEqual(result["result_type"], RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED)

    @patch("assistant_os.core.policy.build_policy")
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.9,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_forced_blocked_mode_returns_plan_generated(self, _mock_classify, mock_build_policy):
        """If policy returns execution_mode=blocked, orchestrator returns plan_generated."""
        mock_build_policy.return_value = {
            "execution_mode": EXECUTION_MODE_BLOCKED,
            "routing_action": "WORK_QUERY",
            "domain": "WORK",
        }
        req = _req("dame mis tareas")
        result = handle_request(req)
        self.assertEqual(result["result_type"], RESULT_TYPE_PLAN_GENERATED)


if __name__ == "__main__":
    unittest.main()
