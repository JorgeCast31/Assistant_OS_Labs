"""
S-K18 — RouteDecision and Kernel Enrichment

Tests for the RouteDecision TypedDict and the enrichment computation module.
RouteDecision is a non-authoritative enrichment artifact produced after
intent classification. Its fields are signals only — they MUST NOT affect
execution_mode, PolicyDecision, GovernanceVerdict, or pipeline dispatch.
"""

import unittest

from assistant_os.contracts import (
    normalize_request,
    RouteDecision,
    make_route_decision,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
)
from assistant_os.core.enrichment import compute_enrichment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req(text: str) -> dict:
    return normalize_request(text=text)


def _intent(domain: str = "WORK", operation: str = "WORK_QUERY", risk: str = RISK_LOW) -> dict:
    return {
        "domain": domain,
        "operation": operation,
        "type": "Tarea",
        "cognitive_load": "Baja",
        "impact": "Operativo",
        "next_action": "query tasks",
        "confidence": 0.9,
        "alternatives": [],
        "needs_confirmation": False,
        "reason": "test",
    }


# ---------------------------------------------------------------------------
# 1. RouteDecision TypedDict contract
# ---------------------------------------------------------------------------

class TestRouteDecisionContract(unittest.TestCase):

    def test_make_route_decision_with_required_fields(self):
        """make_route_decision returns a RouteDecision with all required fields."""
        rd = make_route_decision(
            intent_type="WORK_QUERY",
            domain="WORK",
        )
        self.assertEqual(rd["intent_type"], "WORK_QUERY")
        self.assertEqual(rd["domain"], "WORK")

    def test_make_route_decision_defaults(self):
        """Optional enrichment fields default to None / empty list."""
        rd = make_route_decision(intent_type="WORK_QUERY", domain="WORK")
        self.assertIsNone(rd["operator_goal"])
        self.assertIsNone(rd["semantic_summary"])
        self.assertIsNone(rd["risk_hint"])
        self.assertEqual(rd["context_requirements"], [])
        self.assertIsNone(rd["suggested_next_step"])

    def test_make_route_decision_with_all_fields(self):
        """make_route_decision stores all provided enrichment fields."""
        rd = make_route_decision(
            intent_type="CODE_FIX",
            domain="CODE",
            operator_goal="Fix authentication bug",
            semantic_summary="Code mutation: fix bug in auth module",
            risk_hint="medium",
            context_requirements=["target_file", "workspace"],
            suggested_next_step="Confirm the proposed change before applying.",
        )
        self.assertEqual(rd["intent_type"], "CODE_FIX")
        self.assertEqual(rd["domain"], "CODE")
        self.assertEqual(rd["operator_goal"], "Fix authentication bug")
        self.assertEqual(rd["semantic_summary"], "Code mutation: fix bug in auth module")
        self.assertEqual(rd["risk_hint"], "medium")
        self.assertEqual(rd["context_requirements"], ["target_file", "workspace"])
        self.assertEqual(rd["suggested_next_step"], "Confirm the proposed change before applying.")

    def test_risk_hint_allowed_values(self):
        """risk_hint must be one of: none, low, medium, high, or None."""
        valid_hints = ["none", "low", "medium", "high", None]
        for hint in valid_hints:
            rd = make_route_decision(intent_type="X", domain="Y", risk_hint=hint)
            self.assertEqual(rd["risk_hint"], hint)


# ---------------------------------------------------------------------------
# 2. compute_enrichment — deterministic enrichment from request + intent
# ---------------------------------------------------------------------------

class TestComputeEnrichment(unittest.TestCase):

    def test_returns_route_decision(self):
        """compute_enrichment returns a RouteDecision dict."""
        req = _req("dame mis tareas")
        intent = _intent("WORK", "WORK_QUERY", RISK_LOW)
        rd = compute_enrichment(req, intent)
        self.assertIn("intent_type", rd)
        self.assertIn("domain", rd)
        self.assertIn("operator_goal", rd)
        self.assertIn("semantic_summary", rd)
        self.assertIn("risk_hint", rd)
        self.assertIn("context_requirements", rd)
        self.assertIn("suggested_next_step", rd)

    def test_intent_type_derived_from_operation(self):
        """intent_type in RouteDecision matches the operation from classified intent."""
        req = _req("dame mis tareas")
        intent = _intent("WORK", "WORK_QUERY", RISK_LOW)
        rd = compute_enrichment(req, intent)
        self.assertEqual(rd["intent_type"], "WORK_QUERY")

    def test_domain_derived_from_intent(self):
        """domain in RouteDecision matches the domain from classified intent."""
        req = _req("dame mis tareas")
        intent = _intent("WORK", "WORK_QUERY", RISK_LOW)
        rd = compute_enrichment(req, intent)
        self.assertEqual(rd["domain"], "WORK")

    def test_risk_hint_low_for_read_only(self):
        """Read-only operations produce risk_hint='low'."""
        req = _req("show me my tasks")
        intent = _intent("WORK", "WORK_QUERY", RISK_LOW)
        rd = compute_enrichment(req, intent)
        self.assertEqual(rd["risk_hint"], "low")

    def test_risk_hint_medium_for_write(self):
        """Write operations produce risk_hint='medium'."""
        req = _req("create a task")
        intent = _intent("WORK", "WORK_CREATE", RISK_MEDIUM)
        rd = compute_enrichment(req, intent)
        self.assertEqual(rd["risk_hint"], "medium")

    def test_risk_hint_high_for_destructive(self):
        """Destructive operations produce risk_hint='high'."""
        req = _req("delete all tasks")
        intent = _intent("WORK", "WORK_DELETE", RISK_HIGH)
        rd = compute_enrichment(req, intent)
        self.assertEqual(rd["risk_hint"], "high")

    def test_suggested_next_step_is_string_or_none(self):
        """suggested_next_step must be a string or None — never a callable."""
        req = _req("dame mis tareas")
        intent = _intent("WORK", "WORK_QUERY", RISK_LOW)
        rd = compute_enrichment(req, intent)
        value = rd["suggested_next_step"]
        self.assertTrue(value is None or isinstance(value, str))

    def test_context_requirements_is_list(self):
        """context_requirements must always be a list."""
        req = _req("dame mis tareas")
        intent = _intent("WORK", "WORK_QUERY", RISK_LOW)
        rd = compute_enrichment(req, intent)
        self.assertIsInstance(rd["context_requirements"], list)

    def test_operator_goal_is_string_or_none(self):
        """operator_goal must be a string or None — never a callable or structured object."""
        req = _req("dame mis tareas")
        intent = _intent("WORK", "WORK_QUERY", RISK_LOW)
        rd = compute_enrichment(req, intent)
        value = rd["operator_goal"]
        self.assertTrue(value is None or isinstance(value, str))

    def test_same_input_produces_same_output(self):
        """Enrichment is deterministic: same inputs always produce same RouteDecision."""
        req = _req("dame mis tareas")
        intent = _intent("WORK", "WORK_QUERY", RISK_LOW)
        rd1 = compute_enrichment(req, intent)
        rd2 = compute_enrichment(req, intent)
        self.assertEqual(rd1["intent_type"], rd2["intent_type"])
        self.assertEqual(rd1["domain"], rd2["domain"])
        self.assertEqual(rd1["risk_hint"], rd2["risk_hint"])
        self.assertEqual(rd1["operator_goal"], rd2["operator_goal"])
        self.assertEqual(rd1["semantic_summary"], rd2["semantic_summary"])
        self.assertEqual(rd1["context_requirements"], rd2["context_requirements"])
        self.assertEqual(rd1["suggested_next_step"], rd2["suggested_next_step"])


# ---------------------------------------------------------------------------
# 3. Non-authority isolation — enrichment fields MUST NOT influence execution
# ---------------------------------------------------------------------------

class TestEnrichmentIsolation(unittest.TestCase):

    def test_risk_hint_is_not_risk_level(self):
        """risk_hint is a keyword-derived signal, not a PolicyDecision risk_level."""
        req = _req("dame mis tareas")
        intent = _intent("WORK", "WORK_QUERY", RISK_LOW)
        rd = compute_enrichment(req, intent)
        # risk_hint uses lowercase string values ("low"/"medium"/"high"/"none")
        # risk_level uses RISK_* constants (same values by convention, but different semantic role)
        # This test verifies the field name separation is enforced
        self.assertNotIn("risk_level", rd)
        self.assertNotIn("execution_mode", rd)
        self.assertNotIn("routing_action", rd)

    def test_route_decision_has_no_execution_fields(self):
        """RouteDecision must not carry execution_mode, routing_action, or policy fields."""
        rd = make_route_decision(intent_type="WORK_QUERY", domain="WORK")
        forbidden_fields = {
            "execution_mode", "routing_action", "requires_confirmation",
            "risk_level", "parsed_payload", "policy_explanation",
        }
        for field in forbidden_fields:
            self.assertNotIn(field, rd, f"RouteDecision must not contain '{field}'")

    def test_enrichment_does_not_modify_input_request(self):
        """compute_enrichment must not mutate the CanonicalRequest."""
        req = _req("dame mis tareas")
        original_keys = set(req.keys())
        intent = _intent("WORK", "WORK_QUERY", RISK_LOW)
        compute_enrichment(req, intent)
        self.assertEqual(set(req.keys()), original_keys)


if __name__ == "__main__":
    unittest.main()
