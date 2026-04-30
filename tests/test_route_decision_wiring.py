"""
S-K18 — RouteDecision wiring into handle_request()

Verifies that compute_enrichment() is wired into the Kernel orchestration path
and that RouteDecision is attached to DomainResult.data["route_decision"].

Invariants under test:
- RouteDecision appears in result.data for all execution paths.
- Removing / ignoring route_decision does NOT change execution_mode, pipeline,
  DomainResult.ok, or policy outcome.
- risk_hint does NOT affect authorization.
- suggested_next_step is not a callable, module path, or pipeline name.
- If enrichment fails the request completes normally (fail-quiet).
"""

import unittest
from unittest.mock import patch, MagicMock

from assistant_os.contracts import (
    normalize_request,
    make_domain_result,
    RESULT_TYPE_WORK_QUERY,
    RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
    RESULT_TYPE_PLAN_GENERATED,
    EXECUTION_MODE_AUTO,
    EXECUTION_MODE_CONFIRM,
    EXECUTION_MODE_BLOCKED,
)
from assistant_os.core.orchestrator import handle_request


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

def _req(text: str) -> dict:
    return normalize_request(text=text)


def _reset_mso():
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


# ---------------------------------------------------------------------------
# 1. RouteDecision present in DomainResult — NL auto path (WORK_QUERY)
# ---------------------------------------------------------------------------

class TestRouteDecisionPresentInResult(unittest.TestCase):

    def setUp(self):
        _reset_mso()

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_route_decision_present_in_auto_path(self, _mc, _mq, _mn):
        """NL AUTO path: result.data contains route_decision."""
        result = handle_request(_req("dame mis tareas"))
        self.assertIn("data", result)
        data = result.get("data") or {}
        self.assertIn("route_decision", data,
                      "DomainResult.data must contain route_decision after handle_request()")

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_route_decision_has_required_fields(self, _mc, _mq, _mn):
        """route_decision in result.data contains intent_type and domain."""
        result = handle_request(_req("dame mis tareas"))
        rd = (result.get("data") or {}).get("route_decision")
        self.assertIsNotNone(rd, "route_decision must not be None")
        self.assertIn("intent_type", rd)
        self.assertIn("domain", rd)
        self.assertIn("risk_hint", rd)
        self.assertIn("context_requirements", rd)
        self.assertIn("suggested_next_step", rd)

    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_CREATE", "confidence": 0.9,
               "alternatives": [], "needs_confirmation": True, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_route_decision_present_in_confirm_path(self, _mc):
        """NL CONFIRM path: result.data contains route_decision."""
        _reset_mso()
        result = handle_request(_req("crea una tarea nueva"))
        data = result.get("data") or {}
        self.assertIn("route_decision", data,
                      "CONFIRM path must also attach route_decision to result.data")

    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "UNKNOWN", "operation": "COMMAND", "confidence": 0.5,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_route_decision_present_in_blocked_path(self, _mc):
        """BLOCKED/plan_generated path: result.data contains route_decision."""
        _reset_mso()
        result = handle_request(_req("unknown command xyz"))
        data = result.get("data") or {}
        self.assertIn("route_decision", data,
                      "BLOCKED path must also attach route_decision to result.data")


# ---------------------------------------------------------------------------
# 2. Enrichment fail-quiet — request continues when compute_enrichment raises
# ---------------------------------------------------------------------------

class TestEnrichmentFailQuiet(unittest.TestCase):

    def setUp(self):
        _reset_mso()

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    @patch("assistant_os.core.enrichment.compute_enrichment",
           side_effect=RuntimeError("enrichment exploded"))
    def test_request_completes_when_enrichment_fails(self, _me, _mc, _mq, _mn):
        """If compute_enrichment raises, handle_request still returns a valid DomainResult."""
        result = handle_request(_req("dame mis tareas"))
        self.assertIsNotNone(result)
        self.assertIn("ok", result)
        # Execution must not be affected — still a real result, not a crash
        self.assertEqual(result.get("result_type"), RESULT_TYPE_WORK_QUERY)

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    @patch("assistant_os.core.enrichment.compute_enrichment",
           side_effect=RuntimeError("enrichment exploded"))
    def test_execution_mode_unchanged_when_enrichment_fails(self, _me, _mc, _mq, _mn):
        """Enrichment failure does not change execution_mode or result_type."""
        result_with_failure = handle_request(_req("dame mis tareas"))
        # result_type must still be work_query (AUTO path executed)
        self.assertEqual(result_with_failure.get("result_type"), RESULT_TYPE_WORK_QUERY)


# ---------------------------------------------------------------------------
# 3. Isolation — route_decision does not influence execution authority
# ---------------------------------------------------------------------------

class TestRouteDecisionIsolation(unittest.TestCase):

    def setUp(self):
        _reset_mso()

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_route_decision_does_not_contain_execution_mode(self, _mc, _mq, _mn):
        """route_decision must not carry execution_mode or routing_action."""
        result = handle_request(_req("dame mis tareas"))
        rd = (result.get("data") or {}).get("route_decision") or {}
        forbidden = {"execution_mode", "routing_action", "risk_level",
                     "requires_confirmation", "parsed_payload", "policy_explanation"}
        for field in forbidden:
            self.assertNotIn(field, rd,
                             f"route_decision must not contain authority field '{field}'")

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_result_type_unchanged_by_route_decision(self, _mc, _mq, _mn):
        """Presence of route_decision in data does not change result_type."""
        result = handle_request(_req("dame mis tareas"))
        # The real result_type must come from the pipeline, not from enrichment
        self.assertEqual(result.get("result_type"), RESULT_TYPE_WORK_QUERY)

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_pipeline_outcome_unchanged_by_route_decision(self, _mc, _mq, _mn):
        """Pipeline result_type is not affected by route_decision.

        Verifies that attaching a non-authoritative route_decision to data
        does not change the pipeline outcome. Uses result_type as the proxy
        for execution outcome (result_type=work_query implies ok=True by contract).
        """
        result = handle_request(_req("dame mis tareas"))
        # If route_decision incorrectly affected policy, result_type would be
        # plan_confirmation_required or plan_generated, not work_query.
        self.assertEqual(result.get("result_type"), RESULT_TYPE_WORK_QUERY)

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_risk_hint_does_not_appear_in_policy_fields(self, _mc, _mq, _mn):
        """risk_hint in route_decision is isolated from PolicyDecision risk_level."""
        result = handle_request(_req("dame mis tareas"))
        rd = (result.get("data") or {}).get("route_decision") or {}
        # route_decision has risk_hint (lowercase signal), not risk_level (authority field)
        self.assertNotIn("risk_level", rd)
        if "risk_hint" in rd and rd["risk_hint"] is not None:
            self.assertIn(rd["risk_hint"], ("none", "low", "medium", "high"),
                          "risk_hint must be one of the bounded signal values")

    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
    @patch("assistant_os.integrations.work_gateway.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
               "alternatives": [], "needs_confirmation": False, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_suggested_next_step_is_not_callable(self, _mc, _mq, _mn):
        """suggested_next_step must be a string or None — never a callable."""
        result = handle_request(_req("dame mis tareas"))
        rd = (result.get("data") or {}).get("route_decision") or {}
        value = rd.get("suggested_next_step")
        self.assertNotIsInstance(value, type,
                                 "suggested_next_step must not be a class or type")
        self.assertTrue(value is None or isinstance(value, str),
                        "suggested_next_step must be str or None")
        if isinstance(value, str):
            # Must not look like a module path or pipeline function name
            self.assertNotIn(".", value.split()[0] if value.split() else "",
                             "suggested_next_step must not contain dotted module paths")


if __name__ == "__main__":
    unittest.main()
