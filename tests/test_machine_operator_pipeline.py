import unittest


class TestMachineOperatorPipeline(unittest.TestCase):
    def _request(self, **overrides):
        from assistant_os.mso.contracts import (
            MachineOperatorBudget,
            MachineOperatorIntentRequest,
            MachineOperatorPolicyContext,
        )

        request = MachineOperatorIntentRequest(
            intent_id="intent-003",
            correlation_id="corr-003",
            capability_name="browser.snapshot",
            capability_tier="read_only",
            arguments={"url": "https://example.test"},
            policy_context=MachineOperatorPolicyContext(
                policy_decision_ref="policy-003",
                governance_ref="gov-003",
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

    def _plan(self, request=None, **overrides):
        from assistant_os.contracts import ACTION_MACHINE_OPERATOR_EXECUTE, RISK_LOW, make_plan

        plan = make_plan(
            domain="MACHINE_OPERATOR",
            action=ACTION_MACHINE_OPERATOR_EXECUTE,
            target="machine operator request",
            risk_level=RISK_LOW,
            requires_confirmation=False,
            preview="Validate MACHINE_OPERATOR lane request.",
            raw_text="capture a safe snapshot",
        )
        plan["domain_payload"] = {"machine_operator_request": request or self._request()}
        plan.update(overrides)
        return plan

    def test_valid_request_returns_stub_domain_result(self):
        from assistant_os.contracts import RESULT_TYPE_MACHINE_OPERATOR_ACTION
        from assistant_os.pipelines.machine_operator_pipeline import execute

        result = execute(self._plan(), "ctx-machine-1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["result_type"], RESULT_TYPE_MACHINE_OPERATOR_ACTION)
        self.assertEqual(result["domain"], "MACHINE_OPERATOR")
        self.assertEqual(result["data"]["lane_outcome"], "accepted_not_executed")
        self.assertTrue(result["data"]["contract_validation"]["ok"])
        self.assertFalse(result["data"]["backend_execution_performed"])
        self.assertFalse(result["data"]["machine_action_performed"])
        self.assertTrue(result["data"]["policy_validation"]["ok"])
        self.assertEqual(result["data"]["execution_id"], result["plan_id"])
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "aborted")
        self.assertEqual(
            result["data"]["machine_operator_response"]["observation"]["summary"],
            "MACHINE_OPERATOR lane accepted; backend not implemented.",
        )
        self.assertEqual(result["data"]["machine_operator_response"]["evidence_refs"], [])
        self.assertEqual(result["data"]["machine_operator_response"]["audit_event_ids"], [])
        self.assertEqual(result["data"]["machine_operator_response"]["side_effects_declared"], [])

    def test_invalid_request_fails_closed(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        plan = self._plan()
        plan["domain_payload"] = {"machine_operator_request": {"intent_id": "", "capability_name": "browser.snapshot"}}
        result = execute(plan, "ctx-machine-2")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "InvalidMachineOperatorRequest")
        self.assertEqual(result["data"]["lane_outcome"], "invalid_request")
        self.assertFalse(result["data"]["contract_validation"]["ok"])
        self.assertIsNone(result["data"]["policy_validation"])
        self.assertNotIn("machine_operator_response", result["data"])

    def test_missing_canonical_request_wrapper_fails_closed(self):
        from dataclasses import asdict

        from assistant_os.pipelines.machine_operator_pipeline import execute

        plan = self._plan()
        plan["domain_payload"] = asdict(self._request())
        result = execute(plan, "ctx-machine-wrapper")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "InvalidMachineOperatorPayload")

    def test_unknown_capability_is_rejected(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        result = execute(
            self._plan(self._request(capability_name="browser.click")),
            "ctx-machine-3",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorPolicyViolation")
        self.assertEqual(result["data"]["lane_outcome"], "rejected_by_policy")
        self.assertEqual(result["data"]["policy_validation"]["reason_code"], "unknown_capability")
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "denied")
        self.assertFalse(result["data"]["backend_execution_performed"])
        self.assertFalse(result["data"]["machine_action_performed"])

    def test_approval_required_request_without_approval_is_rejected_as_invalid_request(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        request = self._request(
            capability_name="browser.navigate",
            capability_tier="interactive",
            approval_token=None,
        )
        request.policy_context.approval_mode = "required"
        request.budget.max_steps = 3
        request.budget.max_duration_ms = 15000

        result = execute(self._plan(request), "ctx-machine-4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["lane_outcome"], "invalid_request")
        self.assertFalse(result["data"]["contract_validation"]["ok"])
        self.assertIsNone(result["data"]["policy_validation"])
        self.assertNotIn("machine_operator_response", result["data"])

    def test_policy_context_mismatch_is_rejected_without_execution_leakage(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        request = self._request()
        request.policy_context.approval_mode = "required"
        request.approval_token = "approval-003"

        result = execute(self._plan(request), "ctx-machine-5")

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["lane_outcome"], "rejected_by_policy")
        self.assertEqual(result["data"]["policy_validation"]["reason_code"], "approval_mode_mismatch")
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "denied")
        self.assertFalse(result["data"]["backend_execution_performed"])
        self.assertFalse(result["data"]["machine_action_performed"])

    def test_routing_registry_adds_machine_operator_without_affecting_host(self):
        from assistant_os.contracts import ACTION_HOST_LIST_DIRECTORY, ACTION_MACHINE_OPERATOR_EXECUTE
        from assistant_os.core.routing import action_domain, get_pipeline
        from assistant_os.pipelines import host_pipeline, machine_operator_pipeline

        self.assertEqual(action_domain(ACTION_MACHINE_OPERATOR_EXECUTE), "MACHINE_OPERATOR")
        self.assertIs(get_pipeline("MACHINE_OPERATOR"), machine_operator_pipeline.execute)

        self.assertEqual(action_domain(ACTION_HOST_LIST_DIRECTORY), "HOST")
        self.assertIs(get_pipeline("HOST"), host_pipeline.execute)
