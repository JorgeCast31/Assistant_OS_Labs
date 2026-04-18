import unittest


class TestMachineOperatorPolicy(unittest.TestCase):
    def _request(self, **overrides):
        from assistant_os.mso.contracts import (
            MachineOperatorBudget,
            MachineOperatorIntentRequest,
            MachineOperatorPolicyContext,
        )

        request = MachineOperatorIntentRequest(
            intent_id="intent-002",
            correlation_id="corr-002",
            capability_name="browser.snapshot",
            capability_tier="read_only",
            arguments={"url": "https://example.test"},
            policy_context=MachineOperatorPolicyContext(
                policy_decision_ref="policy-002",
                governance_ref="gov-002",
                execution_mode="auto",
                approval_mode="none",
                constraints=["bounded_scope"],
                allowlist_refs=["allowlist:web-safe"],
                secret_refs=[],
            ),
            budget=MachineOperatorBudget(
                max_steps=2,
                max_duration_ms=8000,
                max_output_bytes=4096,
                max_side_effects=0,
            ),
            requested_side_effects=[],
            approval_token=None,
        )
        for key, value in overrides.items():
            setattr(request, key, value)
        return request

    def test_known_capability_accepted(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        decision = enforce_machine_operator_request(self._request())

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "allowed")
        self.assertEqual(decision.policy.policy_level, "N0")

    def test_unknown_capability_rejected(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        decision = enforce_machine_operator_request(
            self._request(capability_name="browser.click")
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "unknown_capability")
        self.assertFalse(decision.policy.allowed_by_default)

    def test_capability_tier_mismatch_rejected(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        decision = enforce_machine_operator_request(
            self._request(capability_tier="interactive")
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "invalid_tier")

    def test_approval_required_capability_rejected_without_token(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._request(
            capability_name="browser.navigate",
            capability_tier="interactive",
            approval_token=None,
        )
        request.policy_context.approval_mode = "required"
        request.budget.max_steps = 3
        request.budget.max_duration_ms = 15000

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "invalid_request")
        self.assertIn("approval_token", decision.message)

    def test_allowlist_required_capability_rejected_without_context(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._request()
        request.policy_context.allowlist_refs = []

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "missing_allowlist_context")

    def test_policy_context_cannot_override_registry_approval_mode(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._request()
        request.policy_context.approval_mode = "required"
        request.approval_token = "approval-002"

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "approval_mode_mismatch")

    def test_side_effect_mismatch_rejected(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._request()
        request.budget.max_side_effects = 1
        request.requested_side_effects = ["click:submit"]

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "side_effects_not_allowed")

    def test_side_effect_budget_mismatch_rejected(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._request()
        request.budget.max_side_effects = 1

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "side_effect_budget_not_allowed")

    def test_policy_defaults_fail_closed(self):
        from assistant_os.mso.machine_operator_policy import get_machine_operator_policy

        policy = get_machine_operator_policy("browser.unregistered_future_capability")

        self.assertFalse(policy.allowed_by_default)
        self.assertEqual(policy.policy_level, "N2")
        self.assertEqual(policy.approval_mode, "required")

    def test_secret_refs_do_not_enable_unknown_capability(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._request(capability_name="browser.unregistered_future_capability")
        request.policy_context.secret_refs = ["secret:test"]

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "unknown_capability")

    def test_budget_exceeding_policy_is_rejected(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._request()
        request.budget.max_steps = 99

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "budget_exceeded")


if __name__ == "__main__":
    unittest.main()
