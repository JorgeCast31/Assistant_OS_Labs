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

    def _workflow_request(self, **overrides):
        from assistant_os.mso.contracts import (
            MachineOperatorBudget,
            MachineOperatorPolicyContext,
            MachineOperatorWorkflowRequest,
            MachineOperatorWorkflowStep,
        )

        request = MachineOperatorWorkflowRequest(
            intent_id="intent-workflow-002",
            correlation_id="corr-workflow-002",
            workflow_steps=[
                MachineOperatorWorkflowStep(
                    capability_name="browser.snapshot",
                    capability_tier="read_only",
                    arguments={"url": "https://example.test"},
                ),
                MachineOperatorWorkflowStep(
                    capability_name="browser.read_visible_text",
                    capability_tier="read_only",
                    arguments={"url": "https://example.test"},
                ),
            ],
            policy_context=MachineOperatorPolicyContext(
                policy_decision_ref="policy-workflow-002",
                governance_ref="gov-workflow-002",
                execution_mode="auto",
                approval_mode="none",
                constraints=["bounded_scope"],
                allowlist_refs=["allowlist:web-safe"],
                secret_refs=[],
            ),
            budget=MachineOperatorBudget(
                max_steps=2,
                max_duration_ms=16000,
                max_output_bytes=8192,
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

    def test_workflow_with_known_capabilities_is_accepted(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        decision = enforce_machine_operator_request(self._workflow_request())

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "allowed")
        self.assertEqual(decision.policy.capability_name, "workflow:browser.snapshot->browser.read_visible_text")
        self.assertEqual(decision.policy.policy_level, "N0")

    def test_single_step_workflow_uses_plain_capability_label(self):
        from assistant_os.mso.contracts import MachineOperatorWorkflowStep
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._workflow_request(
            workflow_steps=[
                MachineOperatorWorkflowStep(
                    capability_name="browser.snapshot",
                    capability_tier="read_only",
                    arguments={"url": "https://example.test"},
                )
            ],
            budget=self._workflow_request().budget.__class__(
                max_steps=1,
                max_duration_ms=8000,
                max_output_bytes=4096,
                max_side_effects=0,
            ),
        )

        decision = enforce_machine_operator_request(request)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "allowed")
        self.assertEqual(decision.policy.capability_name, "browser.snapshot")
        self.assertEqual(decision.policy.capability_tier, "read_only")
        self.assertEqual(decision.policy.approval_mode, "none")
        self.assertEqual(decision.policy.max_steps, 2)
        self.assertEqual(decision.policy.max_duration_ms, 8000)

    def test_workflow_with_mixed_invalid_tier_is_rejected(self):
        from assistant_os.mso.contracts import MachineOperatorWorkflowStep
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._workflow_request(
            workflow_steps=[
                MachineOperatorWorkflowStep(
                    capability_name="browser.snapshot",
                    capability_tier="interactive",
                    arguments={"url": "https://example.test"},
                )
            ]
        )

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "invalid_tier")

    def test_workflow_with_interactive_step_requires_approval(self):
        from assistant_os.mso.contracts import MachineOperatorWorkflowStep
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._workflow_request(
            workflow_steps=[
                MachineOperatorWorkflowStep(
                    capability_name="browser.navigate",
                    capability_tier="interactive",
                    arguments={"url": "https://example.test"},
                ),
                MachineOperatorWorkflowStep(
                    capability_name="browser.snapshot",
                    capability_tier="read_only",
                    arguments={"url": "https://example.test"},
                ),
            ],
            budget=self._workflow_request().budget.__class__(
                max_steps=2,
                max_duration_ms=23000,
                max_output_bytes=8192,
                max_side_effects=0,
            ),
        )

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "approval_mode_mismatch")

    def test_mixed_workflow_tiers_aggregate_deterministically_when_approved(self):
        from assistant_os.mso.contracts import MachineOperatorWorkflowStep
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._workflow_request(
            workflow_steps=[
                MachineOperatorWorkflowStep(
                    capability_name="browser.navigate",
                    capability_tier="interactive",
                    arguments={"url": "https://example.test"},
                ),
                MachineOperatorWorkflowStep(
                    capability_name="browser.snapshot",
                    capability_tier="read_only",
                    arguments={"url": "https://example.test"},
                ),
            ],
            policy_context=self._workflow_request().policy_context.__class__(
                policy_decision_ref="policy-workflow-002",
                governance_ref="gov-workflow-002",
                execution_mode="auto",
                approval_mode="required",
                constraints=["bounded_scope"],
                allowlist_refs=["allowlist:web-safe"],
                secret_refs=[],
            ),
            budget=self._workflow_request().budget.__class__(
                max_steps=5,
                max_duration_ms=23000,
                max_output_bytes=8192,
                max_side_effects=0,
            ),
            approval_token="approval-workflow-002",
        )

        decision = enforce_machine_operator_request(request)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, "allowed")
        self.assertEqual(decision.policy.capability_name, "workflow:browser.navigate->browser.snapshot")
        self.assertEqual(decision.policy.capability_tier, "interactive")
        self.assertEqual(decision.policy.policy_level, "N1")
        self.assertEqual(decision.policy.approval_mode, "required")
        self.assertTrue(decision.policy.requires_allowlist)
        self.assertFalse(decision.policy.requires_secrets)
        self.assertEqual(decision.policy.max_steps, 5)
        self.assertEqual(decision.policy.max_duration_ms, 23000)

    def test_workflow_budget_exceeding_aggregate_policy_is_rejected(self):
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._workflow_request()
        request.budget.max_duration_ms = 20000

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "budget_exceeded")

    def test_workflow_unknown_capability_is_invalid_request(self):
        from assistant_os.mso.contracts import MachineOperatorWorkflowStep
        from assistant_os.mso.machine_operator_policy import enforce_machine_operator_request

        request = self._workflow_request(
            workflow_steps=[
                MachineOperatorWorkflowStep(
                    capability_name="browser.click",
                    capability_tier="interactive",
                    arguments={"selector": "#submit"},
                )
            ]
        )

        decision = enforce_machine_operator_request(request)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "invalid_request")


if __name__ == "__main__":
    unittest.main()
