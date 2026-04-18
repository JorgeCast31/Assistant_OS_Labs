import unittest
from unittest.mock import Mock, patch

import requests


class _FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class TestMachineOperatorAdapter(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.machine_operator_audit import MACHINE_OPERATOR_AUDIT_LOG

        MACHINE_OPERATOR_AUDIT_LOG.clear()

    def _request(self, **overrides):
        from assistant_os.mso.contracts import (
            MachineOperatorBudget,
            MachineOperatorIntentRequest,
            MachineOperatorPolicyContext,
        )

        request = MachineOperatorIntentRequest(
            intent_id="intent-adapter-001",
            correlation_id="corr-adapter-001",
            capability_name="browser.snapshot",
            capability_tier="read_only",
            arguments={"url": "https://example.test"},
            policy_context=MachineOperatorPolicyContext(
                policy_decision_ref="policy-adapter-001",
                governance_ref="gov-adapter-001",
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

    def _context(self):
        from assistant_os.mso.machine_operator_adapter import MachineOperatorAdapterContext

        return MachineOperatorAdapterContext(
            plan_id="plan-adapter-001",
            execution_id="exec-adapter-001",
            trace_id="trace-adapter-001",
            policy_decision_ref="policy-adapter-001",
            capability_name="browser.snapshot",
            capability_tier="read_only",
            policy_reason_code="allowed",
            policy_message="MACHINE_OPERATOR capability allowed: browser.snapshot",
        )

    def test_stub_adapter_remains_available(self):
        from assistant_os.mso.machine_operator_adapter import StubMachineOperatorAdapter

        result = StubMachineOperatorAdapter().execute(self._request(), self._context())

        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "backend_unavailable")
        self.assertFalse(result.metadata["backend_execution_performed"])
        self.assertFalse(result.metadata["machine_action_performed"])
        self.assertEqual(result.evidence_refs, [])
        self.assertEqual(result.side_effects_declared, [])

    def test_live_adapter_executes_tier_a_request(self):
        from assistant_os.mso.machine_operator_adapter import (
            OpenClawGatewayMachineOperatorAdapter,
            execute_machine_operator,
        )
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": "Page snapshot collected through the machine operator backend.",
                "structured_data": {"page_title": "Example Domain"},
            },
            "evidence_refs": [
                {
                    "ref_id": "evidence-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/001",
                    "description": "Structured page snapshot",
                    "media_type": "application/json",
                }
            ],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 120,
                "output_bytes": 512,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "backend_execution_performed": True,
            "machine_action_performed": True,
        }

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ) as post_mock:
            result = execute_machine_operator(self._request(), self._context())

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        self.assertIsInstance(
            __import__(
                "assistant_os.mso.machine_operator_adapter",
                fromlist=["DEFAULT_MACHINE_OPERATOR_ADAPTER"],
            ).DEFAULT_MACHINE_OPERATOR_ADAPTER,
            OpenClawGatewayMachineOperatorAdapter,
        )
        self.assertTrue(post_mock.called)
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.metadata["backend_execution_attempted"])
        self.assertTrue(result.metadata["backend_execution_performed"])
        self.assertTrue(result.metadata["machine_action_performed"])
        self.assertEqual(result.metadata["lane_outcome"], "success")
        self.assertEqual(result.observation.summary, "Snapshot captured.")
        self.assertEqual(result.consumed_budget.steps, 1)
        self.assertEqual(result.evidence_refs[0].uri, "memory://snapshot/001")
        self.assertEqual(result.side_effects_declared, [])
        self.assertEqual(result.metadata["session_mode"], "ephemeral")
        self.assertFalse(result.metadata["session_reused"])
        self.assertFalse(result.metadata["session_persisted"])
        self.assertFalse(result.metadata["session_retained_after_terminal"])
        self.assertEqual(result.observation.structured_data["cleanup_semantics"], "no_reusable_session_retained")
        self.assertEqual(result.observation.structured_data["evidence_count"], 1)
        self.assertEqual(
            event_types,
            [
                MachineOperatorAuditEventType.MO_INTENT_RECEIVED,
                MachineOperatorAuditEventType.MO_POLICY_EVALUATED,
                MachineOperatorAuditEventType.MO_STEP_STARTED,
                MachineOperatorAuditEventType.MO_STEP_COMPLETED,
                MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED,
            ],
        )

    def test_runtime_allowlist_violation_blocks_transport(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )

        request = self._request(arguments={"url": "https://blocked.test"})
        post_mock = Mock()
        with patch("assistant_os.mso.machine_operator_adapter.requests.post", post_mock):
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, self._context())

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        post_mock.assert_not_called()
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.metadata["lane_outcome"], "policy_violation")
        self.assertFalse(result.metadata["backend_execution_attempted"])
        self.assertFalse(result.metadata["backend_execution_performed"])
        self.assertEqual(result.evidence_refs, [])
        self.assertEqual(result.side_effects_declared, [])
        self.assertEqual(
            event_types,
            [
                MachineOperatorAuditEventType.MO_INTENT_RECEIVED,
                MachineOperatorAuditEventType.MO_POLICY_EVALUATED,
                MachineOperatorAuditEventType.MO_EXECUTION_SKIPPED,
                MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED,
            ],
        )

    def test_url_prefix_allowlist_is_matched_structurally(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        request = self._request(
            arguments={"url": "https://example.test/allowed-evil"},
        )
        request.policy_context.allowlist_refs = ["url_prefix:https://example.test/allowed"]
        post_mock = Mock()
        with patch("assistant_os.mso.machine_operator_adapter.requests.post", post_mock):
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, self._context())

        post_mock.assert_not_called()
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.metadata["backend_status"], "allowlist_blocked")

    def test_malformed_url_fails_closed_before_transport(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        request = self._request(arguments={"url": "https://user@example.test"})
        post_mock = Mock()
        with patch("assistant_os.mso.machine_operator_adapter.requests.post", post_mock):
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, self._context())

        post_mock.assert_not_called()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["backend_status"], "invalid_arguments")

    def test_timeout_returns_truthful_failure(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=requests.Timeout(),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._request(),
                self._context(),
            )

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["backend_status"], "timed_out")
        self.assertTrue(result.metadata["backend_execution_attempted"])
        self.assertFalse(result.metadata["backend_execution_performed"])
        self.assertFalse(result.metadata["machine_action_performed"])
        self.assertEqual(result.evidence_refs, [])
        self.assertEqual(result.side_effects_declared, [])
        self.assertEqual(result.consumed_budget.side_effects, 0)
        self.assertEqual(result.observation.structured_data["evidence_count"], 0)
        self.assertEqual(result.observation.structured_data["session_mode"], "ephemeral")
        self.assertEqual(
            event_types,
            [
                MachineOperatorAuditEventType.MO_INTENT_RECEIVED,
                MachineOperatorAuditEventType.MO_POLICY_EVALUATED,
                MachineOperatorAuditEventType.MO_STEP_STARTED,
                MachineOperatorAuditEventType.MO_EXECUTION_FAILED,
                MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED,
            ],
        )

    def test_backend_final_url_outside_allowlist_fails_closed(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        response_body = {
            "status": "ok",
            "final_url": "https://blocked.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": "Backend reported a redirect.",
                "structured_data": {"page_title": "Blocked"},
            },
            "evidence_refs": [
                {
                    "ref_id": "evidence-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/blocked",
                }
            ],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 100,
                "output_bytes": 128,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "backend_execution_performed": True,
            "machine_action_performed": True,
        }

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(self._request(), self._context())

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["backend_status"], "invalid_backend_response")

    def test_backend_execution_claim_inconsistency_fails_closed(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": "Payload says execution succeeded.",
                "structured_data": {"page_title": "Example"},
            },
            "evidence_refs": [
                {
                    "ref_id": "evidence-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/001",
                }
            ],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 100,
                "output_bytes": 128,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "backend_execution_performed": False,
            "machine_action_performed": False,
        }

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(self._request(), self._context())

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["backend_status"], "invalid_backend_response")

    def test_read_visible_text_requires_bounded_schema(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        request = self._request(capability_name="browser.read_visible_text")
        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Visible text captured.",
                "detail": "Missing schema field.",
                "structured_data": {"is_truncated": False},
            },
            "evidence_refs": [],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 80,
                "output_bytes": 32,
                "side_effects": 0,
            },
            "side_effects_declared": [],
        }

        context = self._context()
        context.capability_name = "browser.read_visible_text"
        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, context)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["backend_status"], "invalid_backend_response")

    def test_budget_overflow_is_rejected(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": "Budget overflow.",
                "structured_data": {"page_title": "Example"},
            },
            "evidence_refs": [
                {
                    "ref_id": "evidence-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/001",
                }
            ],
            "consumed_budget": {
                "steps": 3,
                "duration_ms": 9000,
                "output_bytes": 5000,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "backend_execution_performed": True,
            "machine_action_performed": True,
        }

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(self._request(), self._context())

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["backend_status"], "invalid_backend_response")

    def test_execution_time_approval_rejection_blocks_transport(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )

        request = self._request(capability_name="browser.navigate")
        request.capability_tier = "interactive"
        request.policy_context.approval_mode = "required"
        context = self._context()
        context.capability_name = "browser.navigate"
        context.capability_tier = "interactive"
        post_mock = Mock()
        with patch("assistant_os.mso.machine_operator_adapter.requests.post", post_mock):
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, context)

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        post_mock.assert_not_called()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["lane_outcome"], "invalid_request")
        self.assertEqual(result.metadata["backend_status"], "not_executed")
        self.assertFalse(result.metadata["backend_execution_attempted"])
        self.assertEqual(
            event_types,
            [
                MachineOperatorAuditEventType.MO_INTENT_RECEIVED,
                MachineOperatorAuditEventType.MO_POLICY_EVALUATED,
                MachineOperatorAuditEventType.MO_EXECUTION_SKIPPED,
                MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED,
            ],
        )

    def test_local_abort_stops_before_backend_dispatch(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )

        request = self._request(arguments={"url": "https://example.test", "abort_requested": True})
        post_mock = Mock()
        with patch("assistant_os.mso.machine_operator_adapter.requests.post", post_mock):
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, self._context())

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        post_mock.assert_not_called()
        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "execution_aborted")
        self.assertEqual(result.metadata["backend_status"], "aborted")
        self.assertFalse(result.metadata["backend_execution_attempted"])
        self.assertEqual(
            event_types,
            [
                MachineOperatorAuditEventType.MO_INTENT_RECEIVED,
                MachineOperatorAuditEventType.MO_POLICY_EVALUATED,
                MachineOperatorAuditEventType.MO_EXECUTION_SKIPPED,
                MachineOperatorAuditEventType.MO_ABORTED,
                MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED,
            ],
        )

    def test_backend_unavailable_maps_separately_from_execution_failure(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=requests.ConnectionError("backend offline"),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._request(),
                self._context(),
            )

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "backend_unavailable")
        self.assertEqual(result.metadata["backend_status"], "unavailable")
        self.assertTrue(result.metadata["backend_execution_attempted"])
        self.assertNotIn(MachineOperatorAuditEventType.MO_STEP_COMPLETED, event_types)
        self.assertIn(MachineOperatorAuditEventType.MO_BACKEND_UNAVAILABLE, event_types)
        self.assertNotIn(MachineOperatorAuditEventType.MO_EXECUTION_FAILED, event_types)
        self.assertNotIn(MachineOperatorAuditEventType.MO_ABORTED, event_types)
        self.assertIn(MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED, event_types)

    def test_partial_uses_partial_audit_event(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )

        response_body = {
            "status": "partial",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot partially captured.",
                "detail": "Output truncated by backend budget.",
                "structured_data": {"page_title": "Example"},
            },
            "evidence_refs": [
                {
                    "ref_id": "evidence-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/partial",
                }
            ],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 120,
                "output_bytes": 256,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "backend_execution_performed": True,
            "machine_action_performed": True,
        }

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(self._request(), self._context())

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        self.assertEqual(result.status, "partial")
        self.assertIn(MachineOperatorAuditEventType.MO_STEP_PARTIAL, event_types)
        self.assertNotIn(MachineOperatorAuditEventType.MO_STEP_COMPLETED, event_types)
        self.assertIn(MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED, event_types)

    def test_backend_reported_abort_does_not_claim_completion(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )

        response_body = {
            "status": "aborted",
            "observation": {
                "summary": "Backend aborted execution.",
                "detail": "The execution was canceled before completion.",
                "structured_data": {},
            },
            "evidence_refs": [],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 50,
                "output_bytes": 0,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "backend_execution_performed": False,
            "machine_action_performed": False,
        }

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(self._request(), self._context())

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "execution_aborted")
        self.assertNotIn(MachineOperatorAuditEventType.MO_STEP_COMPLETED, event_types)
        self.assertIn(MachineOperatorAuditEventType.MO_ABORTED, event_types)
        self.assertIn(MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED, event_types)

    def test_context_mismatch_fails_closed_before_transport(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        context = self._context()
        context.capability_name = "browser.navigate"
        context.capability_tier = "interactive"
        post_mock = Mock()
        with patch("assistant_os.mso.machine_operator_adapter.requests.post", post_mock):
            result = OpenClawGatewayMachineOperatorAdapter().execute(self._request(), context)

        post_mock.assert_not_called()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["lane_outcome"], "invalid_request")
        self.assertEqual(result.metadata["backend_status"], "invalid_context")
        self.assertEqual(result.observation.structured_data["session_mode"], "ephemeral")

    def test_duplicate_evidence_refs_fail_closed(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": "Duplicate evidence should fail.",
                "structured_data": {"page_title": "Example"},
            },
            "evidence_refs": [
                {
                    "ref_id": "evidence-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/001",
                },
                {
                    "ref_id": "evidence-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/002",
                },
            ],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 120,
                "output_bytes": 128,
                "side_effects": 0,
            },
            "side_effects_declared": [],
        }

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(self._request(), self._context())

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["backend_status"], "invalid_backend_response")

    def test_malformed_evidence_optional_field_fails_closed(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": "Malformed evidence metadata.",
                "structured_data": {"page_title": "Example"},
            },
            "evidence_refs": [
                {
                    "ref_id": "evidence-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/001",
                    "description": 123,
                }
            ],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 120,
                "output_bytes": 128,
                "side_effects": 0,
            },
            "side_effects_declared": [],
        }

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(self._request(), self._context())

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["backend_status"], "invalid_backend_response")

    def test_gateway_execute_url_rejects_backslashes(self):
        from assistant_os.mso.machine_operator_adapter import _gateway_execute_url

        with patch("assistant_os.mso.machine_operator_adapter.config.OPENCLAW_GATEWAY_URL", "ws://127.0.0.1:18789\\gateway"):
            with self.assertRaisesRegex(ValueError, "URL separators"):
                _gateway_execute_url()

    def test_gateway_execute_url_uses_posix_path_rules(self):
        from assistant_os.mso.machine_operator_adapter import _gateway_execute_url

        with patch("assistant_os.mso.machine_operator_adapter.config.OPENCLAW_GATEWAY_URL", "ws://127.0.0.1:18789/base/"):
            self.assertEqual(
                _gateway_execute_url(),
                "http://127.0.0.1:18789/base/v1/machine-operator/execute",
            )


if __name__ == "__main__":
    unittest.main()
