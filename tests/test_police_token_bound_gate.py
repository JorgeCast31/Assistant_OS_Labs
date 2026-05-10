"""Police Token-Bound Gate — S-POLICE-CORE-03 Implementation Tests"""

import unittest
from assistant_os.police.enforcement import check
from assistant_os.police.gate_models import (
    PoliceGateRequest,
    PoliceDecision,
    PoliceOutcome,
    PoliceReason,
)


def _request(**overrides) -> PoliceGateRequest:
    """Factory: create a default PoliceGateRequest with optional overrides."""
    values = {
        "execution_id": "exec-test-001",
        "operation_key": "op.execute",
        "token_ref": "token-valid-001",
        "binding_ref": "binding-valid-001",
        "authorized_plan_ref": "plan-valid-001",
        "capability_name": "code.execute",
        "governance_ref": "gov-valid-001",
        "policy_decision_ref": "policy-valid-001",
        "trace_id": "trace-test-001",
    }
    values.update(overrides)
    return PoliceGateRequest(**values)


class TestPoliceGateDeniesInvalidToken(unittest.TestCase):
    """T1-T3: Police Gate validation of token."""

    def test_police_gate_denies_missing_token(self):
        """T1: Token reference is None → DENIED with reason TOKEN_MISSING."""
        request = _request(token_ref=None)
        decision = check(request)

        self.assertEqual(decision.outcome, PoliceOutcome.DENIED)
        self.assertEqual(decision.reason, PoliceReason.TOKEN_MISSING)
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.execution_id, request.execution_id)

    def test_police_gate_denies_empty_token_ref(self):
        """T1 variant: Empty string token reference → TOKEN_MISSING."""
        request = _request(token_ref="")
        decision = check(request)

        self.assertEqual(decision.outcome, PoliceOutcome.DENIED)
        self.assertEqual(decision.reason, PoliceReason.TOKEN_MISSING)
        self.assertFalse(decision.permitted)

    def test_police_gate_with_capability_name_present(self):
        """T4 baseline: Requested capability is provided → validation continues."""
        request = _request(
            token_ref="token-valid-001",
            capability_name="code.write"
        )

        decision = check(request)
        self.assertIsInstance(decision, PoliceDecision)
        self.assertTrue(decision.permitted)


class TestPoliceGateDeniesInvalidRequest(unittest.TestCase):
    """T5: Malformed or incomplete request → fail-closed decision."""

    def test_police_gate_denies_missing_governance_ref(self):
        """T9: Missing governance_ref (no MSO governance consulted)."""
        request = _request(governance_ref=None)
        decision = check(request)

        self.assertIn(decision.outcome, [PoliceOutcome.DENIED, PoliceOutcome.DEFERRED])
        self.assertFalse(decision.permitted)

    def test_police_gate_denies_missing_policy_decision_ref(self):
        """T9 variant: Missing policy_decision_ref."""
        request = _request(policy_decision_ref=None)
        decision = check(request)

        self.assertIn(decision.outcome, [PoliceOutcome.DENIED, PoliceOutcome.DEFERRED])
        self.assertFalse(decision.permitted)

    def test_police_gate_denies_missing_execution_id(self):
        """T5: Request missing execution_id (required field)."""
        # execution_id is required; PoliceGateRequest should not allow None
        self.skipTest("execution_id is required by PoliceGateRequest construction")


class TestPoliceGateAllowsValidContext(unittest.TestCase):
    """T6: Valid token, scope, and authorization context → PERMITTED."""

    def test_police_gate_allows_valid_token_and_scope(self):
        """T6: All validations pass → decision.outcome=PERMITTED."""
        request = _request(
            token_ref="token-valid-001",
            binding_ref="binding-valid-001",
            capability_name="code.execute",
            governance_ref="gov-valid-001",
            policy_decision_ref="policy-valid-001",
        )

        decision = check(request)

        self.assertEqual(decision.outcome, PoliceOutcome.PERMITTED)
        self.assertEqual(decision.reason, PoliceReason.ALLOWED)
        self.assertTrue(decision.permitted)
        self.assertEqual(decision.execution_id, request.execution_id)
        self.assertNotEqual(decision.detail, "")


class TestPoliceGateDoesNotExecute(unittest.TestCase):
    """T7: Police Gate never executes or dispatches."""

    def test_police_gate_does_not_invoke_pipeline(self):
        """T7: Police Gate returns decision without executing pipelines."""
        request = _request()
        decision = check(request)

        self.assertIsNotNone(decision)
        self.assertIsInstance(decision, PoliceDecision)
        self.assertEqual(decision.outcome, PoliceOutcome.PERMITTED)

    def test_police_gate_does_not_call_openclaw(self):
        """T7 variant: Police Gate does not call external services."""
        request = _request()
        decision = check(request)

        self.assertIsInstance(decision, PoliceDecision)


class TestPoliceDecisionStructure(unittest.TestCase):
    """T8: Police Decision is properly typed, frozen, and auditable."""

    def test_police_decision_is_frozen(self):
        """Decision is immutable once created."""
        decision = PoliceDecision(
            execution_id="exec-001",
            trace_id="trace-001",
            outcome=PoliceOutcome.PERMITTED,
            reason=PoliceReason.ALLOWED,
            detail="Allowed.",
            permitted=True,
        )

        with self.assertRaises(Exception):
            decision.permitted = False

    def test_police_decision_has_timezone_aware_timestamp(self):
        """checked_at is timezone-aware."""
        request = _request()
        decision = check(request)

        self.assertIsNotNone(decision.checked_at)
        self.assertIsNotNone(decision.checked_at.tzinfo)

    def test_police_decision_detail_is_non_empty(self):
        """Detail field is always populated for audit."""
        request = _request()
        decision = check(request)

        self.assertIsInstance(decision.detail, str)
        self.assertGreater(len(decision.detail), 0)


class TestPoliceGateFailsClosedOnAmbiguity(unittest.TestCase):
    """T10: Ambiguous context → fail-closed decision, not exception."""

    def test_police_gate_returns_denied_not_exception_on_ambiguous_request(self):
        """T10: Invalid context → DENIED decision (not exception)."""
        request = _request(binding_ref=None)

        decision = check(request)

        self.assertIsInstance(decision, PoliceDecision)
        self.assertIn(decision.outcome, [PoliceOutcome.DENIED, PoliceOutcome.DEFERRED])
        self.assertFalse(decision.permitted)

    def test_police_gate_returns_decision_for_missing_plan_ref(self):
        """T10 variant: Missing authorized_plan_ref."""
        request = _request(authorized_plan_ref=None)
        decision = check(request)

        self.assertIsInstance(decision, PoliceDecision)
        self.assertEqual(decision.outcome, PoliceOutcome.DENIED)
        self.assertEqual(decision.reason, PoliceReason.PLAN_BINDING_FAILURE)
        self.assertFalse(decision.permitted)


class TestPoliceGateIntegrationWithMSOGovernance(unittest.TestCase):
    """Integration: Police Gate respects MSO Governance context."""

    def test_police_gate_respects_governance_ref_presence(self):
        """Police Gate requires governance_ref for authorization.

        Two distinct token refs are used so the first PERMITTED decision does
        not spend the token used by the second call.  Tokens are single-use;
        reusing the same ref for both calls would cause the second to be denied
        for TOKEN_ALREADY_CONSUMED rather than GOVERNANCE_REF_MISSING.
        """
        from assistant_os.police.token_registry import register_token
        from assistant_os.police.authorized_plan_registry import register_authorized_plan_ref

        register_token("gov-test-token-with", binding_ref="binding-valid-001")
        register_token("gov-test-token-without", binding_ref="binding-valid-001")
        register_authorized_plan_ref(
            "gov-test-plan-with",
            execution_id="exec-test-001",
            token_ref="gov-test-token-with",
            binding_ref="binding-valid-001",
        )

        request_with_gov = _request(
            governance_ref="gov-001",
            token_ref="gov-test-token-with",
            authorized_plan_ref="gov-test-plan-with",
        )
        decision_with_gov = check(request_with_gov)

        request_without_gov = _request(
            governance_ref=None,
            token_ref="gov-test-token-without",
        )
        decision_without_gov = check(request_without_gov)

        self.assertIsInstance(decision_with_gov, PoliceDecision)
        self.assertIsInstance(decision_without_gov, PoliceDecision)

        self.assertEqual(decision_with_gov.outcome, PoliceOutcome.PERMITTED)
        self.assertTrue(decision_with_gov.permitted)

        self.assertFalse(decision_without_gov.permitted)


if __name__ == "__main__":
    unittest.main()
