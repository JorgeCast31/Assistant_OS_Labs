import unittest


class TestMachineOperatorContracts(unittest.TestCase):
    def _request(self, **overrides):
        from assistant_os.mso.contracts import (
            MachineOperatorBudget,
            MachineOperatorIntentRequest,
            MachineOperatorPolicyContext,
        )

        request = MachineOperatorIntentRequest(
            intent_id="intent-001",
            correlation_id="corr-001",
            capability_name="browser.inspect_dom",
            capability_tier="interactive",
            arguments={"url": "https://example.test"},
            policy_context=MachineOperatorPolicyContext(
                policy_decision_ref="policy-001",
                governance_ref="gov-001",
                execution_mode="confirm_only",
                approval_mode="required",
                constraints=["bounded_scope", "explicit_approval"],
            ),
            budget=MachineOperatorBudget(
                max_steps=5,
                max_duration_ms=30000,
                max_output_bytes=65536,
                max_side_effects=1,
            ),
            approval_token="approval-001",
        )
        for key, value in overrides.items():
            setattr(request, key, value)
        return request

    def _response(self, **overrides):
        from assistant_os.mso.contracts import (
            MachineOperatorBudgetUsage,
            MachineOperatorEvidenceRef,
            MachineOperatorIntentResponse,
            MachineOperatorObservation,
            MachineOperatorSideEffectDeclaration,
        )

        response = MachineOperatorIntentResponse(
            intent_id="intent-001",
            correlation_id="corr-001",
            status="ok",
            observation=MachineOperatorObservation(
                summary="DOM snapshot collected",
                detail="Page title and visible controls were observed.",
                structured_data={"title": "Example Domain"},
            ),
            evidence_refs=[
                MachineOperatorEvidenceRef(
                    ref_id="evidence-001",
                    evidence_type="artifact",
                    uri="memory://artifact/dom-snapshot",
                    description="Structured DOM snapshot",
                )
            ],
            consumed_budget=MachineOperatorBudgetUsage(
                steps=2,
                duration_ms=1200,
                output_bytes=2048,
                side_effects=0,
            ),
            side_effects_declared=[],
            audit_event_ids=["audit-001", "audit-002"],
        )
        for key, value in overrides.items():
            setattr(response, key, value)
        return response

    def test_validate_machine_operator_request_accepts_dataclass_payload(self):
        from assistant_os.mso.contracts import validate_machine_operator_request

        ok, error = validate_machine_operator_request(self._request())

        self.assertTrue(ok)
        self.assertEqual(error, "")

    def test_validate_machine_operator_request_requires_approval_token_when_policy_demands_it(self):
        from assistant_os.mso.contracts import validate_machine_operator_request

        request = self._request(approval_token=None)
        ok, error = validate_machine_operator_request(request)

        self.assertFalse(ok)
        self.assertIn("approval_token", error)

    def test_validate_machine_operator_request_rejects_invalid_capability_tier(self):
        from assistant_os.mso.contracts import validate_machine_operator_request

        payload = {
            "intent_id": "intent-001",
            "correlation_id": "corr-001",
            "capability_name": "browser.inspect_dom",
            "capability_tier": "browser_native",
            "arguments": {},
            "policy_context": {
                "policy_decision_ref": "policy-001",
                "governance_ref": "gov-001",
                "execution_mode": "confirm_only",
                "approval_mode": "none",
                "constraints": [],
                "allowlist_refs": [],
                "secret_refs": [],
            },
            "budget": {
                "max_steps": 1,
                "max_duration_ms": 1000,
                "max_output_bytes": 0,
                "max_side_effects": 0,
            },
            "requested_side_effects": [],
            "approval_token": None,
        }

        ok, error = validate_machine_operator_request(payload)

        self.assertFalse(ok)
        self.assertIn("capability_tier", error)

    def test_validate_machine_operator_response_accepts_dataclass_payload(self):
        from assistant_os.mso.contracts import validate_machine_operator_response

        ok, error = validate_machine_operator_response(self._response())

        self.assertTrue(ok)
        self.assertEqual(error, "")

    def test_validate_machine_operator_request_rejects_missing_explicit_side_effect_field(self):
        from assistant_os.mso.contracts import validate_machine_operator_request

        payload = {
            "intent_id": "intent-001",
            "correlation_id": "corr-001",
            "capability_name": "browser.snapshot",
            "capability_tier": "read_only",
            "arguments": {"url": "https://example.test"},
            "policy_context": {
                "policy_decision_ref": "policy-001",
                "governance_ref": "gov-001",
                "execution_mode": "auto",
                "approval_mode": "none",
                "constraints": ["bounded_scope"],
                "allowlist_refs": ["allowlist:web-safe"],
                "secret_refs": [],
            },
            "budget": {
                "max_steps": 1,
                "max_duration_ms": 1000,
                "max_output_bytes": 0,
                "max_side_effects": 0,
            },
            "approval_token": None,
        }

        ok, error = validate_machine_operator_request(payload)

        self.assertFalse(ok)
        self.assertIn("requested_side_effects", error)

    def test_validate_machine_operator_request_rejects_unknown_top_level_field(self):
        from assistant_os.mso.contracts import validate_machine_operator_request

        payload = {
            "intent_id": "intent-001",
            "correlation_id": "corr-001",
            "capability_name": "browser.snapshot",
            "capability_tier": "read_only",
            "arguments": {"url": "https://example.test"},
            "policy_context": {
                "policy_decision_ref": "policy-001",
                "governance_ref": "gov-001",
                "execution_mode": "auto",
                "approval_mode": "none",
                "constraints": ["bounded_scope"],
                "allowlist_refs": ["allowlist:web-safe"],
                "secret_refs": [],
            },
            "budget": {
                "max_steps": 1,
                "max_duration_ms": 1000,
                "max_output_bytes": 0,
                "max_side_effects": 0,
            },
            "requested_side_effects": [],
            "approval_token": None,
            "unexpected": True,
        }

        ok, error = validate_machine_operator_request(payload)

        self.assertFalse(ok)
        self.assertIn("unknown fields", error)

    def test_validate_machine_operator_response_rejects_invalid_status(self):
        from assistant_os.mso.contracts import validate_machine_operator_response

        payload = {
            "intent_id": "intent-001",
            "correlation_id": "corr-001",
            "status": "timeout",
            "observation": {"summary": "No-op", "detail": "", "structured_data": {}},
            "evidence_refs": [],
            "consumed_budget": {
                "steps": 0,
                "duration_ms": 0,
                "output_bytes": 0,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "audit_event_ids": [],
        }

        ok, error = validate_machine_operator_response(payload)

        self.assertFalse(ok)
        self.assertIn("status", error)

    def test_validate_machine_operator_response_rejects_invalid_evidence_shape(self):
        from assistant_os.mso.contracts import validate_machine_operator_response

        payload = {
            "intent_id": "intent-001",
            "correlation_id": "corr-001",
            "status": "partial",
            "observation": {"summary": "Observed partial page state", "detail": "", "structured_data": {}},
            "evidence_refs": [{
                "ref_id": "",
                "evidence_type": "artifact",
                "uri": "memory://artifact",
                "description": "",
                "media_type": "",
                "digest": "",
            }],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 250,
                "output_bytes": 64,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "audit_event_ids": ["audit-001"],
        }

        ok, error = validate_machine_operator_response(payload)

        self.assertFalse(ok)
        self.assertIn("MachineOperatorEvidenceRef", error)

    def test_validate_machine_operator_response_rejects_non_json_like_structured_data(self):
        from assistant_os.mso.contracts import validate_machine_operator_response

        payload = {
            "intent_id": "intent-001",
            "correlation_id": "corr-001",
            "status": "ok",
            "observation": {
                "summary": "Structured payload",
                "detail": "",
                "structured_data": {"invalid": object()},
            },
            "evidence_refs": [],
            "consumed_budget": {
                "steps": 0,
                "duration_ms": 0,
                "output_bytes": 0,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "audit_event_ids": ["audit-001"],
        }

        ok, error = validate_machine_operator_response(payload)

        self.assertFalse(ok)
        self.assertIn("structured_data", error)

    def test_state_transition_matrix_allows_requested_to_each_canonical_terminal_state(self):
        from assistant_os.mso.contracts import (
            MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE,
            MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED,
            MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED,
            MACHINE_OPERATOR_OUTCOME_EXECUTION_PARTIAL,
            MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST,
            MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION,
            MACHINE_OPERATOR_OUTCOME_SUCCESS,
            MACHINE_OPERATOR_STATE_REQUESTED,
            is_machine_operator_transition_allowed,
        )

        for outcome in (
            MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST,
            MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION,
            MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE,
            MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED,
            MACHINE_OPERATOR_OUTCOME_EXECUTION_PARTIAL,
            MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED,
            MACHINE_OPERATOR_OUTCOME_SUCCESS,
        ):
            self.assertTrue(is_machine_operator_transition_allowed(MACHINE_OPERATOR_STATE_REQUESTED, outcome))

    def test_state_transition_matrix_rejects_terminal_to_terminal_hops(self):
        from assistant_os.mso.contracts import (
            MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED,
            MACHINE_OPERATOR_OUTCOME_SUCCESS,
            is_machine_operator_transition_allowed,
        )

        self.assertFalse(is_machine_operator_transition_allowed(MACHINE_OPERATOR_OUTCOME_SUCCESS, MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED))

    def test_validate_machine_operator_response_rejects_unknown_field(self):
        from assistant_os.mso.contracts import validate_machine_operator_response

        payload = {
            "intent_id": "intent-001",
            "correlation_id": "corr-001",
            "status": "ok",
            "observation": {
                "summary": "Structured payload",
                "detail": "",
                "structured_data": {},
            },
            "evidence_refs": [],
            "consumed_budget": {
                "steps": 0,
                "duration_ms": 0,
                "output_bytes": 0,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "audit_event_ids": ["audit-001"],
            "unexpected": "field",
        }

        ok, error = validate_machine_operator_response(payload)

        self.assertFalse(ok)
        self.assertIn("unknown fields", error)


if __name__ == "__main__":
    unittest.main()
