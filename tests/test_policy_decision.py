"""
Tests for PolicyDecision v1 contracts.

Covers:
- PolicyDecision contract creation (required fields always present)
- ui_intent derived from UI_INTENT_MAP (not ad hoc strings)
- execution_mode is valid and deterministic
- execution_mode == "auto" for safe auto-executable actions
- execution_mode == "confirm" for mutation actions
- execution_mode == "clarify" when required fields are missing
- execution_mode == "blocked" for unsupported / unknown actions
- UI_INTENT_MAP: all known ACTION_* values map correctly
- Unknown action maps to "unknown"
- determine_execution_mode() consistency with should_auto_execute()
- PolicyDecision does NOT contain execution-only fields (context_id, plan_id)
- Integration: _route_text_by_classification uses execution_mode for auto path
"""
import unittest
from unittest.mock import MagicMock, patch

from assistant_os.contracts import (
    # PolicyDecision contracts
    PolicyDecision,
    build_policy_decision,
    determine_execution_mode,
    ui_intent_for_action,
    UI_INTENT_MAP,
    EXECUTION_MODE_AUTO,
    EXECUTION_MODE_CONFIRM,
    EXECUTION_MODE_CLARIFY,
    EXECUTION_MODE_BLOCKED,
    # Action constants
    ACTION_WORK_QUERY,
    ACTION_WORK_CREATE,
    ACTION_WORK_CREATE_TEST,
    ACTION_WORK_UPDATE,
    ACTION_WORK_UPDATE_BULK,
    ACTION_WORK_DELETE,
    ACTION_WORK_DELETE_TEST,
    ACTION_WORK_TEST_RESET,
    ACTION_FIN_EXPENSE,
    ACTION_FIN_BATCH,
    ACTION_COMMAND,
    ACTION_CLASSIFY,
    ACTION_UNKNOWN,
    # Risk
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
    # Plan auto-execute for consistency check
    make_plan,
    should_auto_execute,
)


# ---------------------------------------------------------------------------
# Required fields always present
# ---------------------------------------------------------------------------

class TestPolicyDecisionRequiredFields(unittest.TestCase):
    def _build(self, **overrides):
        defaults = dict(
            text="query tasks",
            action=ACTION_WORK_QUERY,
            domain="WORK",
            risk_level=RISK_LOW,
            requires_confirmation=False,
            confidence=0.95,
        )
        defaults.update(overrides)
        return build_policy_decision(**defaults)

    def test_trace_id_present(self):
        self.assertIn("trace_id", self._build())
        self.assertTrue(self._build()["trace_id"])

    def test_domain_present(self):
        pd = self._build(domain="WORK")
        self.assertEqual(pd["domain"], "WORK")

    def test_routing_action_present(self):
        pd = self._build(action=ACTION_WORK_QUERY)
        self.assertEqual(pd["routing_action"], ACTION_WORK_QUERY)

    def test_ui_intent_present(self):
        pd = self._build()
        self.assertIn("ui_intent", pd)
        self.assertIsInstance(pd["ui_intent"], str)

    def test_confidence_present(self):
        pd = self._build(confidence=0.88)
        self.assertAlmostEqual(pd["confidence"], 0.88)

    def test_risk_level_present(self):
        pd = self._build(risk_level=RISK_MEDIUM)
        self.assertEqual(pd["risk_level"], RISK_MEDIUM)

    def test_execution_mode_present(self):
        pd = self._build()
        self.assertIn("execution_mode", pd)

    def test_parsed_payload_present(self):
        pd = self._build()
        self.assertIn("parsed_payload", pd)
        self.assertIsInstance(pd["parsed_payload"], dict)

    def test_raw_text_present(self):
        pd = self._build(text="query my tasks")
        self.assertEqual(pd["raw_text"], "query my tasks")

    def test_does_not_contain_plan_id(self):
        pd = self._build()
        self.assertNotIn("plan_id", pd)

    def test_does_not_contain_context_id(self):
        pd = self._build()
        self.assertNotIn("context_id", pd)

    def test_does_not_contain_idempotency_key(self):
        pd = self._build()
        self.assertNotIn("idempotency_key", pd)

    def test_trace_id_propagated_when_provided(self):
        pd = build_policy_decision(
            "query", ACTION_WORK_QUERY, "WORK", RISK_LOW, False, 0.9,
            trace_id="my-trace-001"
        )
        self.assertEqual(pd["trace_id"], "my-trace-001")

    def test_trace_id_auto_generated_when_absent(self):
        pd1 = build_policy_decision("q", ACTION_WORK_QUERY, "WORK", RISK_LOW, False, 0.9)
        pd2 = build_policy_decision("q", ACTION_WORK_QUERY, "WORK", RISK_LOW, False, 0.9)
        self.assertNotEqual(pd1["trace_id"], pd2["trace_id"])

    def test_classifier_intent_stored_for_audit(self):
        pd = build_policy_decision(
            "query", ACTION_WORK_QUERY, "WORK", RISK_LOW, False, 0.9,
            classifier_intent="WORK_QUERY"
        )
        self.assertEqual(pd["classifier_intent"], "WORK_QUERY")

    def test_parsed_payload_passed_through(self):
        payload = {"title": "Test task", "status": "NEXT"}
        pd = build_policy_decision(
            "create task", ACTION_WORK_CREATE, "WORK", RISK_MEDIUM, True, 0.9,
            parsed_payload=payload
        )
        self.assertEqual(pd["parsed_payload"], payload)


# ---------------------------------------------------------------------------
# execution_mode — auto
# ---------------------------------------------------------------------------

class TestExecutionModeAuto(unittest.TestCase):
    def test_work_query_low_risk_is_auto(self):
        mode = determine_execution_mode(ACTION_WORK_QUERY, RISK_LOW, False)
        self.assertEqual(mode, EXECUTION_MODE_AUTO)

    def test_work_query_auto_in_build(self):
        pd = build_policy_decision("query", ACTION_WORK_QUERY, "WORK", RISK_LOW, False, 0.95)
        self.assertEqual(pd["execution_mode"], EXECUTION_MODE_AUTO)

    def test_auto_consistent_with_should_auto_execute(self):
        """execution_mode == 'auto' must match should_auto_execute() == True."""
        plan = make_plan("WORK", ACTION_WORK_QUERY, "test query", risk_level=RISK_LOW)
        plan["requires_confirmation"] = False
        mode = determine_execution_mode(ACTION_WORK_QUERY, RISK_LOW, False)
        self.assertEqual(mode == EXECUTION_MODE_AUTO, should_auto_execute(plan))

    def test_requires_confirmation_overrides_auto(self):
        """Even a whitelisted action must not auto-execute if requires_confirmation=True."""
        mode = determine_execution_mode(ACTION_WORK_QUERY, RISK_LOW, requires_confirmation=True)
        self.assertNotEqual(mode, EXECUTION_MODE_AUTO)

    def test_work_query_medium_risk_not_auto(self):
        """Only the specific (action, risk_level) pair in the whitelist is auto."""
        mode = determine_execution_mode(ACTION_WORK_QUERY, RISK_MEDIUM, False)
        self.assertNotEqual(mode, EXECUTION_MODE_AUTO)


# ---------------------------------------------------------------------------
# execution_mode — confirm
# ---------------------------------------------------------------------------

class TestExecutionModeConfirm(unittest.TestCase):
    def test_work_create_is_confirm(self):
        mode = determine_execution_mode(ACTION_WORK_CREATE, RISK_MEDIUM, True)
        self.assertEqual(mode, EXECUTION_MODE_CONFIRM)

    def test_work_delete_is_confirm(self):
        mode = determine_execution_mode(ACTION_WORK_DELETE, RISK_MEDIUM, True)
        self.assertEqual(mode, EXECUTION_MODE_CONFIRM)

    def test_work_delete_high_is_confirm(self):
        mode = determine_execution_mode(ACTION_WORK_DELETE, RISK_HIGH, True)
        self.assertEqual(mode, EXECUTION_MODE_CONFIRM)

    def test_work_update_is_confirm(self):
        mode = determine_execution_mode(ACTION_WORK_UPDATE, RISK_MEDIUM, True)
        self.assertEqual(mode, EXECUTION_MODE_CONFIRM)

    def test_work_update_bulk_is_confirm(self):
        mode = determine_execution_mode(ACTION_WORK_UPDATE_BULK, RISK_HIGH, True)
        self.assertEqual(mode, EXECUTION_MODE_CONFIRM)

    def test_fin_expense_is_confirm(self):
        mode = determine_execution_mode(ACTION_FIN_EXPENSE, RISK_MEDIUM, True)
        self.assertEqual(mode, EXECUTION_MODE_CONFIRM)

    def test_work_test_reset_is_confirm(self):
        mode = determine_execution_mode(ACTION_WORK_TEST_RESET, RISK_HIGH, True)
        self.assertEqual(mode, EXECUTION_MODE_CONFIRM)

    def test_build_work_create_is_confirm(self):
        pd = build_policy_decision("create task X", ACTION_WORK_CREATE, "WORK", RISK_MEDIUM, True, 0.9)
        self.assertEqual(pd["execution_mode"], EXECUTION_MODE_CONFIRM)


# ---------------------------------------------------------------------------
# execution_mode — clarify
# ---------------------------------------------------------------------------

class TestExecutionModeClarify(unittest.TestCase):
    def test_missing_fields_triggers_clarify(self):
        mode = determine_execution_mode(ACTION_WORK_CREATE, RISK_MEDIUM, True, missing_fields=["title"])
        self.assertEqual(mode, EXECUTION_MODE_CLARIFY)

    def test_empty_missing_fields_does_not_trigger_clarify(self):
        mode = determine_execution_mode(ACTION_WORK_CREATE, RISK_MEDIUM, True, missing_fields=[])
        self.assertNotEqual(mode, EXECUTION_MODE_CLARIFY)

    def test_none_missing_fields_does_not_trigger_clarify(self):
        mode = determine_execution_mode(ACTION_WORK_CREATE, RISK_MEDIUM, True, missing_fields=None)
        self.assertNotEqual(mode, EXECUTION_MODE_CLARIFY)

    def test_clarify_sets_clarification_reason(self):
        pd = build_policy_decision(
            "create task", ACTION_WORK_CREATE, "WORK", RISK_MEDIUM, True, 0.9,
            missing_fields=["title"]
        )
        self.assertEqual(pd["execution_mode"], EXECUTION_MODE_CLARIFY)
        self.assertEqual(pd["clarification_reason"], "missing_required_field")

    def test_clarify_preserves_missing_fields(self):
        missing = ["title", "project"]
        pd = build_policy_decision(
            "create task", ACTION_WORK_CREATE, "WORK", RISK_MEDIUM, True, 0.9,
            missing_fields=missing
        )
        self.assertEqual(pd["missing_fields"], missing)

    def test_clarify_overrides_auto(self):
        """Even a whitelisted action is clarify if fields are missing."""
        mode = determine_execution_mode(ACTION_WORK_QUERY, RISK_LOW, False, missing_fields=["search_term"])
        self.assertEqual(mode, EXECUTION_MODE_CLARIFY)

    def test_no_missing_fields_no_clarification_reason(self):
        pd = build_policy_decision("query", ACTION_WORK_QUERY, "WORK", RISK_LOW, False, 0.95)
        self.assertIsNone(pd["clarification_reason"])
        self.assertIsNone(pd["missing_fields"])


# ---------------------------------------------------------------------------
# execution_mode — blocked
# ---------------------------------------------------------------------------

class TestExecutionModeBlocked(unittest.TestCase):
    def test_unknown_action_is_blocked(self):
        mode = determine_execution_mode(ACTION_UNKNOWN, RISK_MEDIUM, False)
        self.assertEqual(mode, EXECUTION_MODE_BLOCKED)

    def test_classify_action_is_blocked(self):
        mode = determine_execution_mode(ACTION_CLASSIFY, RISK_LOW, False)
        self.assertEqual(mode, EXECUTION_MODE_BLOCKED)

    def test_unknown_action_blocked_in_build(self):
        pd = build_policy_decision("unknown input", ACTION_UNKNOWN, "UNKNOWN", RISK_MEDIUM, False, 0.2)
        self.assertEqual(pd["execution_mode"], EXECUTION_MODE_BLOCKED)


# ---------------------------------------------------------------------------
# UI_INTENT_MAP
# ---------------------------------------------------------------------------

class TestUiIntentMap(unittest.TestCase):
    def test_all_known_actions_in_map(self):
        known_actions = [
            ACTION_WORK_QUERY, ACTION_WORK_CREATE, ACTION_WORK_CREATE_TEST,
            ACTION_WORK_UPDATE, ACTION_WORK_UPDATE_BULK,
            ACTION_WORK_DELETE, ACTION_WORK_DELETE_TEST, ACTION_WORK_TEST_RESET,
            ACTION_FIN_EXPENSE, ACTION_FIN_BATCH,
            ACTION_COMMAND, ACTION_CLASSIFY, ACTION_UNKNOWN,
        ]
        for action in known_actions:
            with self.subTest(action=action):
                self.assertIn(action, UI_INTENT_MAP)

    def test_work_query_maps_to_query(self):
        self.assertEqual(ui_intent_for_action(ACTION_WORK_QUERY), "query")

    def test_work_create_maps_to_create(self):
        self.assertEqual(ui_intent_for_action(ACTION_WORK_CREATE), "create")

    def test_work_create_test_maps_to_create(self):
        self.assertEqual(ui_intent_for_action(ACTION_WORK_CREATE_TEST), "create")

    def test_work_update_maps_to_update(self):
        self.assertEqual(ui_intent_for_action(ACTION_WORK_UPDATE), "update")

    def test_work_update_bulk_maps_to_bulk_update(self):
        self.assertEqual(ui_intent_for_action(ACTION_WORK_UPDATE_BULK), "bulk_update")

    def test_work_delete_maps_to_delete(self):
        self.assertEqual(ui_intent_for_action(ACTION_WORK_DELETE), "delete")

    def test_work_delete_test_maps_to_delete(self):
        self.assertEqual(ui_intent_for_action(ACTION_WORK_DELETE_TEST), "delete")

    def test_work_test_reset_maps_to_delete(self):
        self.assertEqual(ui_intent_for_action(ACTION_WORK_TEST_RESET), "delete")

    def test_fin_expense_maps_to_expense(self):
        self.assertEqual(ui_intent_for_action(ACTION_FIN_EXPENSE), "expense")

    def test_fin_batch_maps_to_expense(self):
        self.assertEqual(ui_intent_for_action(ACTION_FIN_BATCH), "expense")

    def test_command_maps_to_command(self):
        self.assertEqual(ui_intent_for_action(ACTION_COMMAND), "command")

    def test_unknown_action_maps_to_unknown(self):
        self.assertEqual(ui_intent_for_action("NONEXISTENT_ACTION_XYZ"), "unknown")
        self.assertEqual(ui_intent_for_action(""), "unknown")

    def test_ui_intent_in_policy_decision_matches_map(self):
        """build_policy_decision must use UI_INTENT_MAP, not ad hoc strings."""
        for action, expected_intent in UI_INTENT_MAP.items():
            with self.subTest(action=action):
                pd = build_policy_decision(
                    "test", action, "WORK", RISK_MEDIUM, False, 0.9
                )
                self.assertEqual(pd["ui_intent"], expected_intent)

    def test_all_map_values_are_lowercase(self):
        for action, intent in UI_INTENT_MAP.items():
            with self.subTest(action=action):
                self.assertEqual(intent, intent.lower(),
                                 f"ui_intent for {action} should be lowercase")


# ---------------------------------------------------------------------------
# determine_execution_mode() consistency with should_auto_execute()
# ---------------------------------------------------------------------------

class TestExecutionModeConsistency(unittest.TestCase):
    """execution_mode == 'auto' ↔ should_auto_execute() == True for all known actions."""

    _CASES = [
        (ACTION_WORK_QUERY,       RISK_LOW,    False),
        (ACTION_WORK_QUERY,       RISK_MEDIUM, False),
        (ACTION_WORK_CREATE,      RISK_MEDIUM, True),
        (ACTION_WORK_UPDATE,      RISK_MEDIUM, True),
        (ACTION_WORK_UPDATE_BULK, RISK_HIGH,   True),
        (ACTION_WORK_DELETE,      RISK_MEDIUM, True),
        (ACTION_FIN_EXPENSE,      RISK_MEDIUM, False),
        (ACTION_UNKNOWN,          RISK_MEDIUM, False),
    ]

    def test_auto_mode_matches_should_auto_execute(self):
        for action, risk, req_confirm in self._CASES:
            with self.subTest(action=action, risk=risk):
                plan = make_plan(
                    "WORK", action, "test target", risk_level=risk,
                    requires_confirmation=req_confirm,
                )
                mode = determine_execution_mode(action, risk, req_confirm)
                sae = should_auto_execute(plan)
                self.assertEqual(
                    mode == EXECUTION_MODE_AUTO, sae,
                    f"Mismatch for action={action}: mode={mode!r}, should_auto_execute={sae}"
                )


# ---------------------------------------------------------------------------
# Integration: _route_text_by_classification uses execution_mode for auto path
# ---------------------------------------------------------------------------

class TestRouteByClassificationIntegration(unittest.TestCase):
    """
    Verify that the active webhook path uses execution_mode to decide auto-execution,
    and that building a PolicyDecision internally does not change the external response.
    """

    @patch("assistant_os.webhook_server.check_notion_available", return_value=True)
    @patch("assistant_os.webhook_server.classify_text",
           return_value={"domain": "WORK", "operation": "WORK_QUERY", "confidence": 0.95,
                         "alternatives": [], "needs_confirmation": False, "reason": "test",
                         "type": "", "cognitive_load": "", "impact": "", "next_action": ""})
    @patch("assistant_os.webhook_server.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    def test_work_query_still_auto_executes(self, _mock_query, _mock_classify, _mock_notion):
        handler = MagicMock()
        from assistant_os.webhook_server import WebhookHandler
        result = WebhookHandler._route_text_by_classification(handler, "show my tasks", "127.0.0.1")
        # Kernel now calls _work_query_execute directly (no executor coupling).
        # Verify the response is a successful work_query result, not a confirmation prompt.
        self.assertEqual(result.get("output", {}).get("result_type"), "work_query")

    @patch("assistant_os.webhook_server.classify_text",
           return_value={"domain": "WORK", "operation": "WORK_CREATE", "confidence": 0.9,
                         "alternatives": [], "needs_confirmation": True, "reason": "test",
                         "type": "", "cognitive_load": "", "impact": "", "next_action": ""})
    def test_work_create_still_requires_confirmation(self, _mock_classify):
        handler = MagicMock()
        from assistant_os.webhook_server import WebhookHandler
        result = WebhookHandler._route_text_by_classification(handler, "create task X", "127.0.0.1")
        # Should return a plan_confirmation_required response, not auto-execute
        handler._execute_work_query_from_plan.assert_not_called()
        output_type = result.get("output", {}).get("type", "")
        self.assertEqual(output_type, "plan_confirmation_required")


# ---------------------------------------------------------------------------
# M0.6 — Whitelist alignment: WORK_UPDATE and FIN_EXPENSE
# ---------------------------------------------------------------------------

class TestWhitelistAlignment(unittest.TestCase):
    """
    M0.6: Verify that the whitelist accurately reflects all auto-execute actions.

    WORK_UPDATE (RISK_LOW) and FIN_EXPENSE (RISK_MEDIUM) are set to
    requires_confirmation=False by _create_plan_from_intent. They must be
    in _AUTO_EXECUTE_WHITELIST so that determine_execution_mode() returns "auto"
    and the orchestrator routes them through the pipeline without user confirmation.
    """

    def test_work_update_risk_low_is_auto(self):
        """WORK_UPDATE Phase 1 is read-only preview — must auto-execute."""
        mode = determine_execution_mode(ACTION_WORK_UPDATE, RISK_LOW, False)
        self.assertEqual(mode, EXECUTION_MODE_AUTO)

    def test_fin_expense_risk_medium_is_auto(self):
        """Single FIN_EXPENSE auto-executes by design."""
        mode = determine_execution_mode(ACTION_FIN_EXPENSE, RISK_MEDIUM, False)
        self.assertEqual(mode, EXECUTION_MODE_AUTO)

    def test_work_update_risk_low_auto_consistent_with_should_auto_execute(self):
        """determine_execution_mode and should_auto_execute must agree for WORK_UPDATE."""
        plan = make_plan("WORK", ACTION_WORK_UPDATE, "update task", risk_level=RISK_LOW,
                         requires_confirmation=False)
        mode = determine_execution_mode(ACTION_WORK_UPDATE, RISK_LOW, False)
        self.assertEqual(mode == EXECUTION_MODE_AUTO, should_auto_execute(plan))

    def test_fin_expense_auto_consistent_with_should_auto_execute(self):
        """determine_execution_mode and should_auto_execute must agree for FIN_EXPENSE."""
        plan = make_plan("FIN", ACTION_FIN_EXPENSE, "expense $50", risk_level=RISK_MEDIUM,
                         requires_confirmation=False)
        mode = determine_execution_mode(ACTION_FIN_EXPENSE, RISK_MEDIUM, False)
        self.assertEqual(mode == EXECUTION_MODE_AUTO, should_auto_execute(plan))

    def test_work_update_requires_confirmation_overrides_whitelist(self):
        """Even a whitelisted WORK_UPDATE must not auto-execute if requires_confirmation=True."""
        mode = determine_execution_mode(ACTION_WORK_UPDATE, RISK_LOW, requires_confirmation=True)
        self.assertNotEqual(mode, EXECUTION_MODE_AUTO)

    def test_work_update_risk_medium_not_auto(self):
        """Only (WORK_UPDATE, RISK_LOW) is whitelisted — RISK_MEDIUM is not."""
        mode = determine_execution_mode(ACTION_WORK_UPDATE, RISK_MEDIUM, False)
        self.assertNotEqual(mode, EXECUTION_MODE_AUTO)

    def test_fin_expense_risk_high_not_auto(self):
        """Only (FIN_EXPENSE, RISK_MEDIUM) is whitelisted — RISK_HIGH is not."""
        mode = determine_execution_mode(ACTION_FIN_EXPENSE, RISK_HIGH, False)
        self.assertNotEqual(mode, EXECUTION_MODE_AUTO)


# ---------------------------------------------------------------------------
# M0.6 — ACTION_COMMAND must be blocked
# ---------------------------------------------------------------------------

class TestCommandActionBlocked(unittest.TestCase):
    """
    M0.6: ACTION_COMMAND has no registered pipeline. Returning "confirm" for it
    would produce plan_confirmation_required (wrong). It must be "blocked" so the
    orchestrator falls through to plan_generated (informational routing).
    """

    def test_action_command_is_blocked(self):
        mode = determine_execution_mode(ACTION_COMMAND, RISK_MEDIUM, False)
        self.assertEqual(mode, EXECUTION_MODE_BLOCKED)

    def test_action_command_blocked_in_build(self):
        pd = build_policy_decision(
            "code something", ACTION_COMMAND, "CODE", RISK_MEDIUM, False, 0.5
        )
        self.assertEqual(pd["execution_mode"], EXECUTION_MODE_BLOCKED)


if __name__ == "__main__":
    unittest.main()
