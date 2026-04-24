import os
import unittest
from urllib.parse import urlparse
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
        from assistant_os.mso.machine_operator_adapter import reset_machine_operator_backend_health
        from assistant_os.mso.machine_operator_audit import MACHINE_OPERATOR_AUDIT_LOG

        reset_machine_operator_backend_health()
        MACHINE_OPERATOR_AUDIT_LOG.clear()

    def _approval(self, **overrides):
        approval = {
            "approval_id": "approval-adapter-001",
            "approved_for": "single_step",
            "capability_scope": ["browser.navigate"],
            "expires_at": "2030-01-01T00:00:00+00:00",
            "issued_by": "reviewer:test",
            "reason": "Explicit bounded approval.",
        }
        approval.update(overrides)
        return approval

    def _workflow_approval(self, **overrides):
        approval = self._approval(
            approval_id="approval-workflow-adapter-001",
            approved_for="workflow",
            capability_scope=["browser.snapshot", "browser.read_visible_text"],
        )
        approval.update(overrides)
        return approval

    def _request(self, **overrides):
        request = {
            "intent_id": "intent-adapter-001",
            "correlation_id": "corr-adapter-001",
            "capability_name": "browser.snapshot",
            "capability_tier": "read_only",
            "arguments": {"url": "https://example.test"},
            "policy_context": {
                "policy_decision_ref": "policy-adapter-001",
                "governance_ref": "gov-adapter-001",
                "execution_mode": "auto",
                "approval_mode": "none",
                "constraints": ["bounded_scope"],
                "allowlist_refs": ["allowlist:web-safe"],
                "secret_refs": [],
            },
            "budget": {
                "max_steps": 2,
                "max_duration_ms": 8000,
                "max_output_bytes": 4096,
                "max_side_effects": 0,
            },
            "requested_side_effects": [],
            "approval": None,
        }
        for key, value in overrides.items():
            request[key] = value
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

    def _workflow_request(self, **overrides):
        request = {
            "intent_id": "intent-workflow-adapter-001",
            "correlation_id": "corr-workflow-adapter-001",
            "workflow_steps": [
                {
                    "capability_name": "browser.snapshot",
                    "capability_tier": "read_only",
                    "arguments": {"url": "https://example.test"},
                },
                {
                    "capability_name": "browser.read_visible_text",
                    "capability_tier": "read_only",
                    "arguments": {"url": "https://example.test"},
                },
            ],
            "policy_context": {
                "policy_decision_ref": "policy-workflow-adapter-001",
                "governance_ref": "gov-workflow-adapter-001",
                "execution_mode": "auto",
                "approval_mode": "none",
                "constraints": ["bounded_scope"],
                "allowlist_refs": ["allowlist:web-safe"],
                "secret_refs": [],
            },
            "budget": {
                "max_steps": 2,
                "max_duration_ms": 16000,
                "max_output_bytes": 4096,
                "max_side_effects": 0,
            },
            "requested_side_effects": [],
            "approval": None,
        }
        for key, value in overrides.items():
            request[key] = value
        return request

    def _workflow_context(self, **overrides):
        from assistant_os.mso.machine_operator_adapter import MachineOperatorAdapterContext

        context = MachineOperatorAdapterContext(
            plan_id="plan-workflow-adapter-001",
            execution_id="exec-workflow-adapter-001",
            trace_id="trace-workflow-adapter-001",
            policy_decision_ref="policy-workflow-adapter-001",
            capability_name="workflow:browser.snapshot->browser.read_visible_text",
            capability_tier="read_only",
            policy_reason_code="allowed",
            policy_message="MACHINE_OPERATOR workflow allowed: browser.snapshot -> browser.read_visible_text",
        )
        for key, value in overrides.items():
            setattr(context, key, value)
        return context

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
        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(result.status, "ok")
        self.assertNotIn("headers", post_mock.call_args.kwargs)
        self.assertTrue(result.metadata["backend_execution_attempted"])
        self.assertTrue(result.metadata["backend_execution_performed"])
        self.assertTrue(result.metadata["machine_action_performed"])
        self.assertEqual(result.metadata["lane_outcome"], "success")
        self.assertFalse(payload["execution"]["require_credentials"])
        self.assertEqual(result.observation.summary, "Snapshot captured.")
        self.assertEqual(result.consumed_budget.steps, 1)
        self.assertEqual(result.evidence_refs[0].uri, "memory://snapshot/001")
        self.assertEqual(result.side_effects_declared, [])
        self.assertEqual(result.metadata["session_mode"], "ephemeral")
        self.assertFalse(result.metadata["session_reused"])
        self.assertFalse(result.metadata["session_persisted"])
        self.assertFalse(result.metadata["session_retained_after_terminal"])
        self.assertEqual(result.metadata["backend_state"], "HEALTHY")
        self.assertEqual(result.metadata["backend_error_type"], "")
        self.assertEqual(result.metadata["circuit_state"], "closed")
        self.assertGreaterEqual(result.metadata["backend_latency_ms"], 0)
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

    def test_header_token_auth_attaches_configured_header(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

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
                    "ref_id": "evidence-auth-header-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/auth-header-001",
                    "description": "Structured page snapshot",
                    "media_type": "application/json",
                }
            ],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 120,
                "output_bytes": 128,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "backend_execution_performed": True,
            "machine_action_performed": True,
        }

        with patch.multiple(
            "assistant_os.mso.machine_operator_adapter.config",
            OPENCLAW_GATEWAY_AUTH_MODE="header_token",
            OPENCLAW_GATEWAY_AUTH_HEADER_NAME="X-OpenClaw-Token",
            OPENCLAW_GATEWAY_AUTH_TOKEN_ENV_VAR="OPENCLAW_GATEWAY_AUTH_TOKEN",
        ), patch.dict(
            os.environ,
            {"OPENCLAW_GATEWAY_AUTH_TOKEN": "gateway-boundary-token"},
            clear=False,
        ), patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ) as post_mock:
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._request(),
                self._context(),
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(
            post_mock.call_args.kwargs["headers"],
            {"X-OpenClaw-Token": "gateway-boundary-token"},
        )

    def test_header_token_auth_missing_token_fails_closed_before_dispatch(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter
        from assistant_os.mso.machine_operator_audit import MACHINE_OPERATOR_AUDIT_LOG

        with patch.multiple(
            "assistant_os.mso.machine_operator_adapter.config",
            OPENCLAW_GATEWAY_AUTH_MODE="header_token",
            OPENCLAW_GATEWAY_AUTH_HEADER_NAME="X-OpenClaw-Token",
            OPENCLAW_GATEWAY_AUTH_TOKEN_ENV_VAR="OPENCLAW_GATEWAY_AUTH_TOKEN",
        ), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCLAW_GATEWAY_AUTH_TOKEN", None)
            with patch("assistant_os.mso.machine_operator_adapter.requests.post") as post_mock:
                result = OpenClawGatewayMachineOperatorAdapter().execute(
                    self._request(),
                    self._context(),
                )

        post_mock.assert_not_called()
        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "execution_aborted")
        self.assertEqual(result.metadata["backend_status"], "transport_auth_invalid")
        self.assertEqual(result.metadata["adapter_status"], "transport_auth_invalid")
        self.assertFalse(result.metadata["backend_execution_attempted"])
        self.assertIn("OPENCLAW_GATEWAY_AUTH_TOKEN", result.observation.detail)
        audit_details = " ".join(event.detail for event in MACHINE_OPERATOR_AUDIT_LOG.events())
        self.assertNotIn("gateway-boundary-token", audit_details)

    def test_header_token_auth_missing_header_name_fails_closed_before_dispatch(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        with patch.multiple(
            "assistant_os.mso.machine_operator_adapter.config",
            OPENCLAW_GATEWAY_AUTH_MODE="header_token",
            OPENCLAW_GATEWAY_AUTH_HEADER_NAME="",
            OPENCLAW_GATEWAY_AUTH_TOKEN_ENV_VAR="OPENCLAW_GATEWAY_AUTH_TOKEN",
        ), patch.dict(
            os.environ,
            {"OPENCLAW_GATEWAY_AUTH_TOKEN": "gateway-boundary-token"},
            clear=False,
        ), patch("assistant_os.mso.machine_operator_adapter.requests.post") as post_mock:
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._request(),
                self._context(),
            )

        post_mock.assert_not_called()
        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "execution_aborted")
        self.assertEqual(result.metadata["backend_status"], "transport_auth_invalid")
        self.assertIn("OPENCLAW_GATEWAY_AUTH_HEADER_NAME", result.observation.detail)

    def test_transport_private_fields_and_token_do_not_leak_from_backend(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter
        from assistant_os.mso.machine_operator_audit import MACHINE_OPERATOR_AUDIT_LOG

        transport_token = "gateway-boundary-token"
        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": f"Internal token echo {transport_token} should be redacted.",
                "structured_data": {
                    "page_title": "Example Domain",
                    "workflow_execution_id": "wf-001",
                    "auth_token": transport_token,
                    "transport_auth_mode": "header_token",
                },
            },
            "metadata": {
                "workflow_execution_id": "wf-001",
                "auth_token": transport_token,
                "transport_auth_mode": "header_token",
            },
            "evidence_refs": [
                {
                    "ref_id": "evidence-redaction-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/redaction-001",
                    "description": "Structured page snapshot",
                    "media_type": "application/json",
                }
            ],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 120,
                "output_bytes": 128,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "backend_execution_performed": True,
            "machine_action_performed": True,
        }

        with patch.multiple(
            "assistant_os.mso.machine_operator_adapter.config",
            OPENCLAW_GATEWAY_AUTH_MODE="header_token",
            OPENCLAW_GATEWAY_AUTH_HEADER_NAME="X-OpenClaw-Token",
            OPENCLAW_GATEWAY_AUTH_TOKEN_ENV_VAR="OPENCLAW_GATEWAY_AUTH_TOKEN",
        ), patch.dict(
            os.environ,
            {"OPENCLAW_GATEWAY_AUTH_TOKEN": transport_token},
            clear=False,
        ), patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._request(),
                self._context(),
            )

        audit_details = " ".join(event.detail for event in MACHINE_OPERATOR_AUDIT_LOG.events())
        self.assertEqual(result.status, "ok")
        self.assertNotIn("workflow_execution_id", result.metadata)
        self.assertNotIn("transport_auth_mode", result.metadata)
        self.assertNotIn("auth_token", result.metadata)
        self.assertEqual(result.observation.structured_data["page_title"], "Example Domain")
        self.assertNotIn("workflow_execution_id", result.observation.structured_data)
        self.assertNotIn("transport_auth_mode", result.observation.structured_data)
        self.assertNotIn("auth_token", result.observation.structured_data)
        self.assertIn("[redacted]", result.observation.detail)
        self.assertNotIn(transport_token, result.observation.detail)
        self.assertNotIn(transport_token, str(result.metadata))
        self.assertNotIn(transport_token, audit_details)

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
        request["policy_context"]["allowlist_refs"] = ["url_prefix:https://example.test/allowed"]
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
        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "execution_aborted")
        self.assertEqual(result.metadata["backend_status"], "timeout")
        self.assertTrue(result.metadata["backend_execution_attempted"])
        self.assertFalse(result.metadata["backend_execution_performed"])
        self.assertFalse(result.metadata["machine_action_performed"])
        self.assertEqual(result.metadata["adapter_status"], "timeout")
        self.assertEqual(result.metadata["backend_state"], "DEGRADED")
        self.assertEqual(result.metadata["backend_error_type"], "Timeout")
        self.assertEqual(result.metadata["circuit_state"], "closed")
        self.assertGreaterEqual(result.metadata["backend_latency_ms"], 0)
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
                MachineOperatorAuditEventType.MO_ABORTED,
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
        request["capability_tier"] = "interactive"
        request["policy_context"]["approval_mode"] = "required"
        context = self._context()
        context.capability_name = "browser.navigate"
        context.capability_tier = "interactive"
        post_mock = Mock()
        with patch("assistant_os.mso.machine_operator_adapter.requests.post", post_mock):
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, context)

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        post_mock.assert_not_called()
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.metadata["lane_outcome"], "policy_violation")
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

    def test_secret_refs_rejection_blocks_transport(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        request = self._request()
        request["policy_context"]["secret_refs"] = ["secret:test"]
        post_mock = Mock()

        with patch("assistant_os.mso.machine_operator_adapter.requests.post", post_mock):
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, self._context())

        post_mock.assert_not_called()
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.metadata["lane_outcome"], "policy_violation")
        self.assertEqual(result.metadata["adapter_status"], "rejected_by_policy")
        self.assertFalse(result.metadata["backend_execution_attempted"])

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
        self.assertEqual(result.metadata["backend_state"], "DEGRADED")
        self.assertEqual(result.metadata["backend_error_type"], "ConnectionError")
        self.assertEqual(result.metadata["circuit_state"], "closed")
        self.assertNotIn(MachineOperatorAuditEventType.MO_STEP_COMPLETED, event_types)
        self.assertIn(MachineOperatorAuditEventType.MO_BACKEND_UNAVAILABLE, event_types)
        self.assertNotIn(MachineOperatorAuditEventType.MO_EXECUTION_FAILED, event_types)
        self.assertNotIn(MachineOperatorAuditEventType.MO_ABORTED, event_types)
        self.assertIn(MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED, event_types)
        self.assertTrue(
            any("error_type=ConnectionError" in event.detail for event in MACHINE_OPERATOR_AUDIT_LOG.events())
        )

    def test_backend_becomes_unavailable_after_repeated_failures(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        adapter = OpenClawGatewayMachineOperatorAdapter()
        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                requests.ConnectionError("backend offline"),
                requests.ConnectionError("backend still offline"),
            ],
        ):
            first = adapter.execute(self._request(), self._context())
            second = adapter.execute(self._request(), self._context())

        self.assertEqual(first.metadata["backend_state"], "DEGRADED")
        self.assertEqual(first.metadata["circuit_state"], "closed")
        self.assertEqual(second.metadata["backend_state"], "UNAVAILABLE")
        self.assertEqual(second.metadata["circuit_state"], "open")

    def test_circuit_breaker_blocks_execution_when_backend_is_unavailable(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )

        adapter = OpenClawGatewayMachineOperatorAdapter()
        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                requests.ConnectionError("backend offline"),
                requests.ConnectionError("backend still offline"),
            ],
        ):
            adapter.execute(self._request(), self._context())
            adapter.execute(self._request(), self._context())

        MACHINE_OPERATOR_AUDIT_LOG.clear()
        with patch("assistant_os.mso.machine_operator_adapter.requests.post") as post_mock:
            result = adapter.execute(self._request(), self._context())

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        post_mock.assert_not_called()
        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "backend_unavailable")
        self.assertEqual(result.metadata["backend_status"], "unavailable")
        self.assertEqual(result.metadata["adapter_status"], "circuit_open")
        self.assertEqual(result.metadata["backend_state"], "UNAVAILABLE")
        self.assertEqual(result.metadata["circuit_state"], "open")
        self.assertFalse(result.metadata["backend_execution_attempted"])
        self.assertFalse(result.metadata["backend_execution_performed"])
        self.assertFalse(result.metadata["machine_action_performed"])
        self.assertIn(MachineOperatorAuditEventType.MO_BACKEND_UNAVAILABLE, event_types)
        self.assertNotIn(MachineOperatorAuditEventType.MO_STEP_STARTED, event_types)

    def test_gateway_failures_are_not_retried(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=requests.ConnectionError("backend offline"),
        ) as post_mock:
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._request(),
                self._context(),
            )

        self.assertEqual(post_mock.call_count, 1)
        self.assertEqual(result.metadata["backend_error_type"], "ConnectionError")

    def test_backend_recovers_from_unavailable_after_cooldown_probe(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": "Backend recovered after cooldown.",
                "structured_data": {"page_title": "Example Domain"},
            },
            "evidence_refs": [
                {
                    "ref_id": "evidence-recovery-001",
                    "evidence_type": "artifact",
                    "uri": "memory://snapshot/recovery",
                    "description": "Recovered structured page snapshot",
                    "media_type": "application/json",
                }
            ],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 120,
                "output_bytes": 128,
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "backend_execution_performed": True,
            "machine_action_performed": True,
        }

        adapter = OpenClawGatewayMachineOperatorAdapter()
        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                requests.ConnectionError("backend offline"),
                requests.ConnectionError("backend still offline"),
            ],
        ):
            adapter.execute(self._request(), self._context())
            adapter.execute(self._request(), self._context())

        adapter._backend_health.last_failure_timestamp -= 31.0

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = adapter.execute(self._request(), self._context())

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metadata["backend_state"], "HEALTHY")
        self.assertEqual(result.metadata["circuit_state"], "closed")
        self.assertEqual(adapter._backend_health.consecutive_failures, 0)

    def test_backend_probe_failure_keeps_unavailable_without_retry_loop(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        adapter = OpenClawGatewayMachineOperatorAdapter()
        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                requests.ConnectionError("backend offline"),
                requests.ConnectionError("backend still offline"),
            ],
        ):
            adapter.execute(self._request(), self._context())
            adapter.execute(self._request(), self._context())

        adapter._backend_health.last_failure_timestamp -= 31.0

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=requests.ConnectionError("probe failed"),
        ) as post_mock:
            result = adapter.execute(self._request(), self._context())

        self.assertEqual(post_mock.call_count, 1)
        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "backend_unavailable")
        self.assertEqual(result.metadata["backend_state"], "UNAVAILABLE")
        self.assertEqual(result.metadata["circuit_state"], "open")

    def test_backend_is_not_permanently_locked_after_cooldown(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        adapter = OpenClawGatewayMachineOperatorAdapter()
        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                requests.ConnectionError("backend offline"),
                requests.ConnectionError("backend still offline"),
            ],
        ):
            adapter.execute(self._request(), self._context())
            adapter.execute(self._request(), self._context())

        adapter._backend_health.last_failure_timestamp -= 31.0

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
        ) as post_mock:
            adapter.execute(self._request(), self._context())

        self.assertEqual(post_mock.call_count, 1)

    def test_single_step_workflow_executes_with_workflow_shape(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        request = self._workflow_request(
            workflow_steps=[
                {
                    "capability_name": "browser.snapshot",
                    "capability_tier": "read_only",
                    "arguments": {"url": "https://example.test"},
                }
            ],
            budget={
                "max_steps": 1,
                "max_duration_ms": 8000,
                "max_output_bytes": 4096,
                "max_side_effects": 0,
            },
        )
        context = self._workflow_context(
            capability_name="browser.snapshot",
            policy_message="MACHINE_OPERATOR capability allowed: browser.snapshot",
        )

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(
                {
                    "status": "ok",
                    "final_url": "https://example.test/",
                    "observation": {
                        "summary": "Snapshot captured.",
                        "detail": "Single-step workflow completed successfully.",
                        "structured_data": {"page_title": "Example Domain"},
                    },
                    "evidence_refs": [
                        {
                            "ref_id": "workflow-single-evidence-001",
                            "evidence_type": "artifact",
                            "uri": "memory://workflow/single-snapshot-001",
                            "description": "Single-step workflow snapshot",
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
            ),
        ) as post_mock:
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, context)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metadata["lane_outcome"], "success")
        self.assertEqual(result.metadata["workflow_step_count"], 1)
        self.assertEqual(result.metadata["workflow_capabilities"], ["browser.snapshot"])
        self.assertEqual(len(result.metadata["step_results"]), 1)
        self.assertEqual(result.metadata["step_results"][0]["step_index"], 0)
        self.assertFalse(result.metadata["session_reused"])
        payload = post_mock.call_args.kwargs["json"]
        self.assertFalse(payload["execution"]["reuse_session"])
        self.assertEqual(
            payload["execution"]["workflow_execution_id"],
            "exec-workflow-adapter-001:workflow",
        )
        self.assertTrue(payload["execution"]["close_session"])

    def test_multi_step_workflow_success_reuses_internal_session(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        response_bodies = [
            _FakeResponse(
                {
                    "status": "ok",
                    "final_url": "https://example.test/",
                    "observation": {
                        "summary": "Snapshot captured.",
                        "detail": "Step one completed successfully.",
                        "structured_data": {"page_title": "Example Domain"},
                    },
                    "evidence_refs": [
                        {
                            "ref_id": "workflow-evidence-001",
                            "evidence_type": "artifact",
                            "uri": "memory://workflow/snapshot-001",
                            "description": "Workflow snapshot",
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
            ),
            _FakeResponse(
                {
                    "status": "ok",
                    "final_url": "https://example.test/",
                    "observation": {
                        "summary": "Visible text captured.",
                        "detail": "Step two completed successfully.",
                        "structured_data": {"visible_text": "Example Domain", "is_truncated": False},
                    },
                    "evidence_refs": [],
                    "consumed_budget": {
                        "steps": 1,
                        "duration_ms": 80,
                        "output_bytes": 64,
                        "side_effects": 0,
                    },
                    "side_effects_declared": [],
                    "backend_execution_performed": True,
                    "machine_action_performed": True,
                }
            ),
        ]

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=response_bodies,
        ) as post_mock:
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._workflow_request(),
                self._workflow_context(),
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metadata["lane_outcome"], "success")
        self.assertEqual(result.metadata["workflow_step_count"], 2)
        self.assertEqual(
            result.metadata["workflow_capabilities"],
            ["browser.snapshot", "browser.read_visible_text"],
        )
        self.assertEqual(len(result.metadata["step_results"]), 2)
        self.assertEqual(result.metadata["step_results"][0]["status"], "ok")
        self.assertEqual(result.metadata["step_results"][1]["status"], "ok")
        self.assertFalse(result.metadata["session_reused"])
        self.assertEqual(post_mock.call_count, 2)
        first_payload = post_mock.call_args_list[0].kwargs["json"]
        second_payload = post_mock.call_args_list[1].kwargs["json"]
        self.assertFalse(first_payload["execution"]["reuse_session"])
        self.assertTrue(second_payload["execution"]["reuse_session"])
        self.assertEqual(
            first_payload["execution"]["workflow_execution_id"],
            "exec-workflow-adapter-001:workflow",
        )
        self.assertEqual(
            second_payload["execution"]["workflow_execution_id"],
            "exec-workflow-adapter-001:workflow",
        )
        self.assertNotIn("close_session", first_payload["execution"])
        self.assertTrue(second_payload["execution"]["close_session"])

    def test_interactive_workflow_derives_step_local_approval_and_policy_context(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        request = self._workflow_request(
            workflow_steps=[
                {
                    "capability_name": "browser.navigate",
                    "capability_tier": "interactive",
                    "arguments": {"url": "https://example.test"},
                },
                {
                    "capability_name": "browser.snapshot",
                    "capability_tier": "read_only",
                    "arguments": {"url": "https://example.test"},
                },
            ],
            policy_context={
                "policy_decision_ref": "policy-workflow-adapter-001",
                "governance_ref": "gov-workflow-adapter-001",
                "execution_mode": "auto",
                "approval_mode": "required",
                "constraints": ["bounded_scope"],
                "allowlist_refs": ["allowlist:web-safe"],
                "secret_refs": [],
            },
            budget={
                "max_steps": 5,
                "max_duration_ms": 23000,
                "max_output_bytes": 4096,
                "max_side_effects": 0,
            },
            approval=self._workflow_approval(
                capability_scope=["browser.navigate", "browser.snapshot"]
            ),
        )
        context = self._workflow_context(
            capability_name="workflow:browser.navigate->browser.snapshot",
            capability_tier="interactive",
            policy_message="MACHINE_OPERATOR workflow allowed: browser.navigate -> browser.snapshot",
        )
        response_bodies = [
            _FakeResponse(
                {
                    "status": "ok",
                    "final_url": "https://example.test/",
                    "observation": {
                        "summary": "Navigation completed.",
                        "detail": "Interactive navigation succeeded.",
                        "structured_data": {"page_title": "Example Domain"},
                    },
                    "evidence_refs": [],
                    "consumed_budget": {
                        "steps": 1,
                        "duration_ms": 120,
                        "output_bytes": 64,
                        "side_effects": 0,
                    },
                    "side_effects_declared": [],
                    "backend_execution_performed": True,
                    "machine_action_performed": True,
                }
            ),
            _FakeResponse(
                {
                    "status": "ok",
                    "final_url": "https://example.test/",
                    "observation": {
                        "summary": "Snapshot captured.",
                        "detail": "Read-only follow-up succeeded.",
                        "structured_data": {"page_title": "Example Domain"},
                    },
                    "evidence_refs": [
                        {
                            "ref_id": "workflow-interactive-evidence-001",
                            "evidence_type": "artifact",
                            "uri": "memory://workflow/interactive-snapshot-001",
                            "description": "Workflow snapshot",
                            "media_type": "application/json",
                        }
                    ],
                    "consumed_budget": {
                        "steps": 1,
                        "duration_ms": 80,
                        "output_bytes": 128,
                        "side_effects": 0,
                    },
                    "side_effects_declared": [],
                    "backend_execution_performed": True,
                    "machine_action_performed": True,
                }
            ),
        ]

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=response_bodies,
        ) as post_mock:
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, context)

        self.assertEqual(result.status, "ok")
        self.assertEqual(post_mock.call_count, 2)
        first_payload = post_mock.call_args_list[0].kwargs["json"]
        second_payload = post_mock.call_args_list[1].kwargs["json"]
        self.assertEqual(first_payload["policy"]["approval_mode"], "required")
        self.assertEqual(first_payload["capability_name"], "browser.navigate")
        self.assertEqual(first_payload["execution"]["workflow_execution_id"], "exec-workflow-adapter-001:workflow")
        self.assertFalse(first_payload["execution"]["reuse_session"])
        self.assertEqual(second_payload["policy"]["approval_mode"], "none")
        self.assertEqual(second_payload["capability_name"], "browser.snapshot")
        self.assertEqual(second_payload["execution"]["workflow_execution_id"], "exec-workflow-adapter-001:workflow")
        self.assertTrue(second_payload["execution"]["reuse_session"])
        self.assertNotIn("close_session", first_payload["execution"])
        self.assertTrue(second_payload["execution"]["close_session"])

    def test_first_step_invalid_request_aborts_workflow(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        request = self._workflow_request(
            workflow_steps=[
                {
                    "capability_name": "browser.snapshot",
                    "capability_tier": "read_only",
                    "arguments": {"url": "https://user@example.test"},
                }
            ],
            budget={
                "max_steps": 1,
                "max_duration_ms": 8000,
                "max_output_bytes": 4096,
                "max_side_effects": 0,
            },
        )
        context = self._workflow_context(
            capability_name="browser.snapshot",
            policy_message="MACHINE_OPERATOR capability allowed: browser.snapshot",
        )

        with patch("assistant_os.mso.machine_operator_adapter.requests.post") as post_mock:
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, context)

        post_mock.assert_not_called()
        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "invalid_request")
        self.assertEqual(result.metadata["backend_status"], "invalid_arguments")
        self.assertEqual(len(result.metadata["step_results"]), 1)
        self.assertEqual(result.metadata["step_results"][0]["status"], "failed")
        self.assertEqual(result.metadata["step_results"][0]["lane_outcome"], "invalid_request")

    def test_multi_step_workflow_partial_when_later_step_fails(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                _FakeResponse(
                    {
                        "status": "ok",
                        "final_url": "https://example.test/",
                        "observation": {
                            "summary": "Snapshot captured.",
                            "detail": "First step succeeded.",
                            "structured_data": {"page_title": "Example Domain"},
                        },
                        "evidence_refs": [
                            {
                                "ref_id": "workflow-evidence-001",
                                "evidence_type": "artifact",
                                "uri": "memory://workflow/snapshot-001",
                                "description": "Workflow snapshot",
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
                ),
                _FakeResponse(
                    {
                        "status": "failed",
                        "observation": {
                            "summary": "Visible text capture failed.",
                            "detail": "Backend failed on step two.",
                            "structured_data": {},
                        },
                        "evidence_refs": [],
                        "consumed_budget": {
                            "steps": 1,
                            "duration_ms": 40,
                            "output_bytes": 0,
                            "side_effects": 0,
                        },
                        "side_effects_declared": [],
                        "backend_execution_performed": False,
                        "machine_action_performed": False,
                    }
                ),
            ],
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._workflow_request(),
                self._workflow_context(),
            )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.metadata["lane_outcome"], "execution_partial")
        self.assertEqual(len(result.metadata["step_results"]), 2)
        self.assertEqual(result.metadata["step_results"][0]["status"], "ok")
        self.assertEqual(result.metadata["step_results"][1]["status"], "failed")
        self.assertEqual(len(result.evidence_refs), 1)
        self.assertEqual(result.consumed_budget.steps, 2)

    def test_multi_step_workflow_aborts_on_first_step_failure(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        post_mock = Mock(
            side_effect=[
                _FakeResponse(
                    {
                        "status": "failed",
                        "observation": {
                            "summary": "Snapshot failed.",
                            "detail": "First step failed before workflow progress.",
                            "structured_data": {},
                        },
                        "evidence_refs": [],
                        "consumed_budget": {
                            "steps": 1,
                            "duration_ms": 40,
                            "output_bytes": 0,
                            "side_effects": 0,
                        },
                        "side_effects_declared": [],
                        "backend_execution_performed": False,
                        "machine_action_performed": False,
                    }
                )
            ]
        )

        with patch("assistant_os.mso.machine_operator_adapter.requests.post", post_mock):
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._workflow_request(),
                self._workflow_context(),
            )

        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "execution_aborted")
        self.assertEqual(len(result.metadata["step_results"]), 1)
        self.assertEqual(result.metadata["step_results"][0]["status"], "failed")
        self.assertEqual(post_mock.call_count, 1)

    def test_multi_step_workflow_aborts_when_budget_is_exhausted_mid_sequence(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                _FakeResponse(
                    {
                        "status": "ok",
                        "final_url": "https://example.test/",
                        "observation": {
                            "summary": "Snapshot captured.",
                            "detail": "First step used the full step budget.",
                            "structured_data": {"page_title": "Example Domain"},
                        },
                        "evidence_refs": [
                            {
                                "ref_id": "workflow-evidence-001",
                                "evidence_type": "artifact",
                                "uri": "memory://workflow/snapshot-001",
                                "description": "Workflow snapshot",
                                "media_type": "application/json",
                            }
                        ],
                        "consumed_budget": {
                            "steps": 2,
                            "duration_ms": 120,
                            "output_bytes": 512,
                            "side_effects": 0,
                        },
                        "side_effects_declared": [],
                        "backend_execution_performed": True,
                        "machine_action_performed": True,
                    }
                )
            ],
        ) as post_mock:
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._workflow_request(),
                self._workflow_context(),
            )

        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.metadata["lane_outcome"], "execution_aborted")
        self.assertEqual(result.metadata["backend_status"], "budget_exhausted")
        self.assertEqual(len(result.metadata["step_results"]), 1)
        self.assertEqual(post_mock.call_count, 1)

    def test_multi_step_workflow_succeeds_at_exact_budget_boundary(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        request = self._workflow_request(
            budget={
                "max_steps": 2,
                "max_duration_ms": 200,
                "max_output_bytes": 4096,
                "max_side_effects": 0,
            }
        )

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                _FakeResponse(
                    {
                        "status": "ok",
                        "final_url": "https://example.test/",
                        "observation": {
                            "summary": "Snapshot captured.",
                            "detail": "First step used part of the workflow budget.",
                            "structured_data": {"page_title": "Example Domain"},
                        },
                        "evidence_refs": [
                            {
                                "ref_id": "workflow-evidence-001",
                                "evidence_type": "artifact",
                                "uri": "memory://workflow/snapshot-budget-001",
                                "description": "Workflow snapshot",
                                "media_type": "application/json",
                            }
                        ],
                        "consumed_budget": {
                            "steps": 1,
                            "duration_ms": 80,
                            "output_bytes": 512,
                            "side_effects": 0,
                        },
                        "side_effects_declared": [],
                        "backend_execution_performed": True,
                        "machine_action_performed": True,
                    }
                ),
                _FakeResponse(
                    {
                        "status": "ok",
                        "final_url": "https://example.test/",
                        "observation": {
                            "summary": "Visible text captured.",
                            "detail": "Second step used the remaining workflow budget exactly.",
                            "structured_data": {"visible_text": "Example Domain", "is_truncated": False},
                        },
                        "evidence_refs": [],
                        "consumed_budget": {
                            "steps": 1,
                            "duration_ms": 120,
                            "output_bytes": 64,
                            "side_effects": 0,
                        },
                        "side_effects_declared": [],
                        "backend_execution_performed": True,
                        "machine_action_performed": True,
                    }
                ),
            ],
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                request,
                self._workflow_context(),
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.consumed_budget.steps, 2)
        self.assertEqual(result.consumed_budget.duration_ms, 200)

    def test_multi_step_workflow_duplicate_evidence_across_steps_fails_closed(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        request = self._workflow_request(
            workflow_steps=[
                {
                    "capability_name": "browser.snapshot",
                    "capability_tier": "read_only",
                    "arguments": {"url": "https://example.test"},
                },
                {
                    "capability_name": "browser.screenshot",
                    "capability_tier": "read_only",
                    "arguments": {"url": "https://example.test"},
                },
            ]
        )
        context = self._workflow_context()
        context.capability_name = "workflow:browser.snapshot->browser.screenshot"

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                _FakeResponse(
                    {
                        "status": "ok",
                        "final_url": "https://example.test/",
                        "observation": {
                            "summary": "Snapshot captured.",
                            "detail": "First step succeeded.",
                            "structured_data": {"page_title": "Example Domain"},
                        },
                        "evidence_refs": [
                            {
                                "ref_id": "duplicate-evidence-001",
                                "evidence_type": "artifact",
                                "uri": "memory://workflow/snapshot-001",
                                "description": "Workflow snapshot",
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
                ),
                _FakeResponse(
                    {
                        "status": "ok",
                        "final_url": "https://example.test/",
                        "observation": {
                            "summary": "Screenshot captured.",
                            "detail": "Second step returned duplicate evidence.",
                            "structured_data": {"image_count": 1},
                        },
                        "evidence_refs": [
                            {
                                "ref_id": "duplicate-evidence-001",
                                "evidence_type": "artifact",
                                "uri": "memory://workflow/screenshot-001",
                                "description": "Workflow screenshot",
                                "media_type": "image/png",
                            }
                        ],
                        "consumed_budget": {
                            "steps": 1,
                            "duration_ms": 90,
                            "output_bytes": 256,
                            "side_effects": 0,
                        },
                        "side_effects_declared": [],
                        "backend_execution_performed": True,
                        "machine_action_performed": True,
                    }
                ),
            ],
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, context)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["lane_outcome"], "execution_failed")
        self.assertEqual(result.metadata["backend_status"], "invalid_workflow_result")
        self.assertEqual(len(result.metadata["step_results"]), 2)
        self.assertEqual(result.metadata["step_results"][1]["status"], "failed")

    def test_multi_step_workflow_duplicate_evidence_uri_across_steps_fails_closed(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        request = self._workflow_request(
            workflow_steps=[
                {
                    "capability_name": "browser.snapshot",
                    "capability_tier": "read_only",
                    "arguments": {"url": "https://example.test"},
                },
                {
                    "capability_name": "browser.screenshot",
                    "capability_tier": "read_only",
                    "arguments": {"url": "https://example.test"},
                },
            ]
        )
        context = self._workflow_context(capability_name="workflow:browser.snapshot->browser.screenshot")

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                _FakeResponse(
                    {
                        "status": "ok",
                        "final_url": "https://example.test/",
                        "observation": {
                            "summary": "Snapshot captured.",
                            "detail": "First step succeeded.",
                            "structured_data": {"page_title": "Example Domain"},
                        },
                        "evidence_refs": [
                            {
                                "ref_id": "duplicate-uri-evidence-001",
                                "evidence_type": "artifact",
                                "uri": "memory://workflow/shared-artifact",
                                "description": "Workflow snapshot",
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
                ),
                _FakeResponse(
                    {
                        "status": "ok",
                        "final_url": "https://example.test/",
                        "observation": {
                            "summary": "Screenshot captured.",
                            "detail": "Second step returned duplicate evidence URI.",
                            "structured_data": {"image_count": 1},
                        },
                        "evidence_refs": [
                            {
                                "ref_id": "duplicate-uri-evidence-002",
                                "evidence_type": "artifact",
                                "uri": "memory://workflow/shared-artifact",
                                "description": "Workflow screenshot",
                                "media_type": "image/png",
                            }
                        ],
                        "consumed_budget": {
                            "steps": 1,
                            "duration_ms": 90,
                            "output_bytes": 256,
                            "side_effects": 0,
                        },
                        "side_effects_declared": [],
                        "backend_execution_performed": True,
                        "machine_action_performed": True,
                    }
                ),
            ],
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(request, context)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.metadata["lane_outcome"], "execution_failed")
        self.assertEqual(result.metadata["backend_status"], "invalid_workflow_result")
        self.assertEqual(len(result.metadata["step_results"]), 2)
        self.assertEqual(result.metadata["step_results"][1]["status"], "failed")

    def test_backend_unavailable_mid_workflow_surfaces_partial(self):
        from assistant_os.mso.machine_operator_adapter import OpenClawGatewayMachineOperatorAdapter

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                _FakeResponse(
                    {
                        "status": "ok",
                        "final_url": "https://example.test/",
                        "observation": {
                            "summary": "Snapshot captured.",
                            "detail": "First step succeeded.",
                            "structured_data": {"page_title": "Example Domain"},
                        },
                        "evidence_refs": [
                            {
                                "ref_id": "workflow-evidence-001",
                                "evidence_type": "artifact",
                                "uri": "memory://workflow/snapshot-unavailable-001",
                                "description": "Workflow snapshot",
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
                ),
                requests.ConnectionError("backend offline"),
            ],
        ):
            result = OpenClawGatewayMachineOperatorAdapter().execute(
                self._workflow_request(),
                self._workflow_context(),
            )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.metadata["lane_outcome"], "execution_partial")
        self.assertEqual(result.metadata["backend_status"], "unavailable")
        self.assertEqual(result.metadata["backend_error_type"], "ConnectionError")
        self.assertEqual(len(result.metadata["step_results"]), 2)
        self.assertEqual(result.metadata["step_results"][0]["status"], "ok")
        self.assertEqual(result.metadata["step_results"][1]["status"], "aborted")
        self.assertEqual(result.metadata["step_results"][1]["lane_outcome"], "backend_unavailable")

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

        with patch("assistant_os.mso.machine_operator_adapter.config.OPENCLAW_GATEWAY_URL", "ws://127.0.0.1:18790\\gateway"):
            with self.assertRaisesRegex(ValueError, "URL separators"):
                _gateway_execute_url()

    def test_gateway_execute_url_uses_posix_path_rules(self):
        from assistant_os.mso.machine_operator_adapter import _gateway_execute_url

        with patch("assistant_os.mso.machine_operator_adapter.config.OPENCLAW_GATEWAY_URL", "ws://127.0.0.1:18790/base/"):
            self.assertEqual(
                _gateway_execute_url(),
                "http://127.0.0.1:18790/base/v1/machine-operator/execute",
            )

    def test_gateway_default_port_matches_openclaw_backend_default(self):
        from assistant_os.mso.machine_operator_adapter import _gateway_execute_url
        from assistant_os.openclaw_backend.config import OPENCLAW_BACKEND_PORT

        execute_url = _gateway_execute_url()
        self.assertEqual(urlparse(execute_url).port, OPENCLAW_BACKEND_PORT)


if __name__ == "__main__":
    unittest.main()
