import unittest
from unittest.mock import patch

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


class TestMachineOperatorPipeline(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.machine_operator_adapter import reset_machine_operator_backend_health
        from assistant_os.mso.machine_operator_audit import MACHINE_OPERATOR_AUDIT_LOG

        reset_machine_operator_backend_health()
        MACHINE_OPERATOR_AUDIT_LOG.clear()

    def _request(self, **overrides):
        request = {
            "intent_id": "intent-003",
            "correlation_id": "corr-003",
            "capability_name": "browser.snapshot",
            "capability_tier": "read_only",
            "arguments": {"url": "https://example.test"},
            "policy_context": {
                "policy_decision_ref": "policy-003",
                "governance_ref": "gov-003",
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
            "approval_token": None,
        }
        for key, value in overrides.items():
            request[key] = value
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

    def test_valid_request_returns_real_execution_domain_result(self):
        from assistant_os.contracts import RESULT_TYPE_MACHINE_OPERATOR_ACTION
        from assistant_os.pipelines.machine_operator_pipeline import execute

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
        ):
            result = execute(self._plan(), "ctx-machine-1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["result_type"], RESULT_TYPE_MACHINE_OPERATOR_ACTION)
        self.assertEqual(result["domain"], "MACHINE_OPERATOR")
        self.assertEqual(result["data"]["lane_outcome"], "success")
        self.assertTrue(result["data"]["contract_validation"]["ok"])
        self.assertTrue(result["data"]["policy_validation"]["ok"])
        self.assertTrue(result["data"]["backend_execution_attempted"])
        self.assertTrue(result["data"]["backend_execution_performed"])
        self.assertTrue(result["data"]["machine_action_performed"])
        self.assertEqual(result["data"]["backend_state"], "HEALTHY")
        self.assertEqual(result["data"]["backend_error_type"], "")
        self.assertEqual(result["data"]["circuit_state"], "closed")
        self.assertGreaterEqual(result["data"]["backend_latency_ms"], 0)
        self.assertEqual(result["data"]["session_mode"], "ephemeral")
        self.assertFalse(result["data"]["session_reused"])
        self.assertFalse(result["data"]["session_persisted"])
        self.assertFalse(result["data"]["session_retained_after_terminal"])
        self.assertEqual(
            result["data"]["machine_operator_response"]["observation"]["structured_data"]["cleanup_semantics"],
            "no_reusable_session_retained",
        )
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "ok")
        self.assertEqual(result["data"]["machine_operator_response"]["evidence_refs"][0]["uri"], "memory://snapshot/001")
        self.assertEqual(
            result["data"]["machine_operator_response"]["consumed_budget"],
            {
                "steps": 1,
                "duration_ms": 120,
                "output_bytes": 512,
                "side_effects": 0,
            },
        )
        self.assertEqual(result["data"]["machine_operator_response"]["side_effects_declared"], [])

    def test_pipeline_calls_adapter_boundary(self):
        from assistant_os.mso.contracts import (
            MachineOperatorBudgetUsage,
            MachineOperatorObservation,
        )
        from assistant_os.mso.machine_operator_adapter import MachineOperatorAdapterResult
        from assistant_os.pipelines.machine_operator_pipeline import execute

        class FakeAdapter:
            def __init__(self):
                self.calls = []

            def execute(self, request, context):
                self.calls.append((request, context))
                return MachineOperatorAdapterResult(
                    status="ok",
                    observation=MachineOperatorObservation(
                        summary="Fake boundary invoked.",
                        detail="Real pipeline path stayed behind the adapter.",
                        structured_data={},
                    ),
                    evidence_refs=[],
                    consumed_budget=MachineOperatorBudgetUsage(
                        steps=1,
                        duration_ms=25,
                        output_bytes=10,
                        side_effects=0,
                    ),
                    side_effects_declared=[],
                    metadata={
                        "lane_outcome": "success",
                        "backend_status": "completed",
                        "backend_execution_attempted": True,
                        "backend_execution_performed": True,
                        "machine_action_performed": True,
                        "adapter_status": "completed",
                    },
                    audit_event_ids=["audit-fake-001"],
                )

        fake_adapter = FakeAdapter()
        with patch(
            "assistant_os.pipelines.machine_operator_pipeline.DEFAULT_MACHINE_OPERATOR_ADAPTER",
            fake_adapter,
        ):
            result = execute(self._plan(), "ctx-machine-boundary")

        self.assertTrue(result["ok"])
        self.assertEqual(len(fake_adapter.calls), 1)
        self.assertEqual(result["data"]["machine_operator_response"]["observation"]["summary"], "Fake boundary invoked.")
        self.assertEqual(result["data"]["machine_operator_response"]["audit_event_ids"], ["audit-fake-001"])

    def test_valid_request_emits_real_execution_audit_events(self):
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )
        from assistant_os.pipelines.machine_operator_pipeline import execute

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Visible text captured.",
                "detail": "Text read safely.",
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

        request = self._request(capability_name="browser.read_visible_text")
        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            return_value=_FakeResponse(response_body),
        ):
            result = execute(self._plan(request), "ctx-machine-audit")

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        self.assertTrue(result["ok"])
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

    def test_timeout_returns_truthful_failure(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=requests.Timeout(),
        ):
            result = execute(self._plan(), "ctx-machine-timeout")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorExecutionAborted")
        self.assertEqual(result["data"]["lane_outcome"], "execution_aborted")
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "aborted")
        self.assertEqual(result["data"]["backend_status"], "timeout")
        self.assertEqual(result["data"]["adapter_status"], "timeout")
        self.assertTrue(result["data"]["backend_execution_attempted"])
        self.assertFalse(result["data"]["backend_execution_performed"])
        self.assertFalse(result["data"]["machine_action_performed"])
        self.assertEqual(result["data"]["backend_state"], "DEGRADED")
        self.assertEqual(result["data"]["backend_error_type"], "Timeout")
        self.assertEqual(result["data"]["circuit_state"], "closed")
        self.assertGreaterEqual(result["data"]["backend_latency_ms"], 0)
        self.assertEqual(result["data"]["machine_operator_response"]["evidence_refs"], [])
        self.assertEqual(result["data"]["machine_operator_response"]["side_effects_declared"], [])
        self.assertEqual(result["data"]["session_mode"], "ephemeral")
        self.assertEqual(
            result["data"]["machine_operator_response"]["observation"]["structured_data"]["evidence_count"],
            0,
        )

    def test_malformed_url_fails_closed(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        request = self._request(arguments={"url": "https://user@example.test"})
        with patch("assistant_os.mso.machine_operator_adapter.requests.post") as post_mock:
            result = execute(self._plan(request), "ctx-machine-malformed")

        post_mock.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "InvalidMachineOperatorRequest")
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "failed")
        self.assertEqual(result["data"]["backend_status"], "invalid_arguments")

    def test_backend_invalid_envelope_fails_closed(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        response_body = {
            "status": "ok",
            "observation": {
                "summary": "Missing final URL.",
                "detail": "Invalid backend response.",
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
            result = execute(self._plan(), "ctx-machine-invalid-envelope")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorExecutionFailed")
        self.assertEqual(result["data"]["backend_status"], "invalid_backend_response")

    def test_backend_execution_lie_fails_closed(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": "Conflicting execution claims.",
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
                "duration_ms": 120,
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
            result = execute(self._plan(), "ctx-machine-lie")

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["backend_status"], "invalid_backend_response")

    def test_read_visible_text_oversized_payload_is_rejected(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        request = self._request(capability_name="browser.read_visible_text")
        oversized = "X" * 5000
        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Visible text captured.",
                "detail": "Payload too large.",
                "structured_data": {"visible_text": oversized, "is_truncated": False},
            },
            "evidence_refs": [],
            "consumed_budget": {
                "steps": 1,
                "duration_ms": 80,
                "output_bytes": len(oversized.encode("utf-8")),
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
            result = execute(self._plan(request), "ctx-machine-oversized-text")

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["backend_status"], "invalid_backend_response")

    def test_budget_overflow_is_rejected(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": "Budget exceeded.",
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
                "steps": 9,
                "duration_ms": 9999,
                "output_bytes": 9999,
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
            result = execute(self._plan(), "ctx-machine-budget")

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["backend_status"], "invalid_backend_response")

    def test_partial_result_is_not_reported_as_completed(self):
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )
        from assistant_os.pipelines.machine_operator_pipeline import execute

        response_body = {
            "status": "partial",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot partially captured.",
                "detail": "Only part of the page fit in budget.",
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
            result = execute(self._plan(), "ctx-machine-partial")

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorExecutionPartial")
        self.assertEqual(result["data"]["lane_outcome"], "execution_partial")
        self.assertIn(MachineOperatorAuditEventType.MO_STEP_PARTIAL, event_types)
        self.assertNotIn(MachineOperatorAuditEventType.MO_STEP_COMPLETED, event_types)
        self.assertIn(MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED, event_types)

    def test_allowlist_violation_fails_closed_without_execution(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        request = self._request(arguments={"url": "https://blocked.test"})
        with patch("assistant_os.mso.machine_operator_adapter.requests.post") as post_mock:
            result = execute(self._plan(request), "ctx-machine-allowlist")

        post_mock.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorPolicyViolation")
        self.assertEqual(result["data"]["lane_outcome"], "policy_violation")
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "denied")
        self.assertFalse(result["data"]["backend_execution_attempted"])
        self.assertFalse(result["data"]["backend_execution_performed"])
        self.assertFalse(result["data"]["machine_action_performed"])
        self.assertEqual(result["data"]["machine_operator_response"]["evidence_refs"], [])
        self.assertEqual(result["data"]["machine_operator_response"]["side_effects_declared"], [])
        self.assertEqual(
            result["data"]["machine_operator_response"]["observation"]["structured_data"]["evidence_count"],
            0,
        )

    def test_execution_time_approval_rejection_prevents_backend_dispatch(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        request = self._request(capability_name="browser.navigate")
        request["capability_tier"] = "interactive"
        request["policy_context"]["approval_mode"] = "required"
        with patch("assistant_os.mso.machine_operator_adapter.requests.post") as post_mock:
            result = execute(self._plan(request), "ctx-machine-approval")

        post_mock.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "InvalidMachineOperatorRequest")
        self.assertEqual(result["data"]["lane_outcome"], "invalid_request")
        self.assertFalse(result["data"]["backend_execution_attempted"])
        self.assertNotIn("machine_operator_response", result["data"])

    def test_local_abort_maps_to_aborted_result(self):
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )
        from assistant_os.pipelines.machine_operator_pipeline import execute

        request = self._request(arguments={"url": "https://example.test", "abort_requested": True})
        with patch("assistant_os.mso.machine_operator_adapter.requests.post") as post_mock:
            result = execute(self._plan(request), "ctx-machine-abort")

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        post_mock.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorExecutionAborted")
        self.assertEqual(result["data"]["lane_outcome"], "execution_aborted")
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "aborted")
        self.assertFalse(result["data"]["backend_execution_attempted"])
        self.assertIn(MachineOperatorAuditEventType.MO_ABORTED, event_types)
        self.assertNotIn(MachineOperatorAuditEventType.MO_STEP_COMPLETED, event_types)
        self.assertIn(MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED, event_types)
        self.assertEqual(result["data"]["session_mode"], "ephemeral")

    def test_backend_unavailable_maps_to_canonical_failure(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=requests.ConnectionError("backend offline"),
        ):
            result = execute(self._plan(), "ctx-machine-backend-unavailable")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorBackendUnavailable")
        self.assertEqual(result["data"]["lane_outcome"], "backend_unavailable")
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "aborted")
        self.assertTrue(result["data"]["backend_execution_attempted"])
        self.assertFalse(result["data"]["backend_execution_performed"])
        self.assertEqual(result["data"]["backend_state"], "DEGRADED")
        self.assertEqual(result["data"]["backend_error_type"], "ConnectionError")
        self.assertEqual(result["data"]["circuit_state"], "closed")
        self.assertEqual(result["data"]["session_mode"], "ephemeral")

    def test_pipeline_surfaces_circuit_open_without_execution_leakage(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=[
                requests.ConnectionError("backend offline"),
                requests.ConnectionError("backend still offline"),
            ],
        ):
            execute(self._plan(), "ctx-machine-open-1")
            execute(self._plan(), "ctx-machine-open-2")

        with patch("assistant_os.mso.machine_operator_adapter.requests.post") as post_mock:
            result = execute(self._plan(), "ctx-machine-open-3")

        post_mock.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorBackendUnavailable")
        self.assertEqual(result["data"]["lane_outcome"], "backend_unavailable")
        self.assertEqual(result["data"]["backend_status"], "unavailable")
        self.assertEqual(result["data"]["adapter_status"], "circuit_open")
        self.assertFalse(result["data"]["backend_execution_attempted"])
        self.assertFalse(result["data"]["backend_execution_performed"])
        self.assertFalse(result["data"]["machine_action_performed"])
        self.assertEqual(result["data"]["backend_state"], "UNAVAILABLE")
        self.assertEqual(result["data"]["circuit_state"], "open")

    def test_invalid_budget_fails_before_execution(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        request = self._request()
        request["budget"]["max_steps"] = 9
        with patch("assistant_os.mso.machine_operator_adapter.requests.post") as post_mock:
            result = execute(self._plan(request), "ctx-machine-invalid-budget")

        post_mock.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorPolicyViolation")
        self.assertEqual(result["data"]["lane_outcome"], "policy_violation")

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
        from assistant_os.pipelines.machine_operator_pipeline import execute

        plan = self._plan()
        plan["domain_payload"] = dict(self._request())
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
        self.assertEqual(result["data"]["lane_outcome"], "policy_violation")
        self.assertEqual(result["data"]["policy_validation"]["reason_code"], "unknown_capability")
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "denied")
        self.assertFalse(result["data"]["backend_execution_performed"])
        self.assertFalse(result["data"]["machine_action_performed"])

    def test_rejected_request_never_calls_adapter_boundary(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        class FailingAdapter:
            def execute(self, request, context):
                raise AssertionError("adapter should not be invoked for rejected requests")

        with patch(
            "assistant_os.pipelines.machine_operator_pipeline.DEFAULT_MACHINE_OPERATOR_ADAPTER",
            FailingAdapter(),
        ):
            result = execute(
                self._plan(self._request(capability_name="browser.click")),
                "ctx-machine-no-adapter",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorPolicyViolation")

    def test_approval_required_request_without_approval_is_rejected_as_invalid_request(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        request = self._request(
            capability_name="browser.navigate",
            capability_tier="interactive",
            approval_token=None,
        )
        request["policy_context"]["approval_mode"] = "required"
        request["budget"]["max_steps"] = 3
        request["budget"]["max_duration_ms"] = 15000

        result = execute(self._plan(request), "ctx-machine-4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["lane_outcome"], "invalid_request")
        self.assertFalse(result["data"]["contract_validation"]["ok"])
        self.assertIsNone(result["data"]["policy_validation"])
        self.assertNotIn("machine_operator_response", result["data"])

    def test_policy_context_mismatch_is_rejected_without_execution_leakage(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        request = self._request()
        request["policy_context"]["approval_mode"] = "required"
        request["approval_token"] = "approval-003"

        result = execute(self._plan(request), "ctx-machine-5")

        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["lane_outcome"], "policy_violation")
        self.assertEqual(result["data"]["policy_validation"]["reason_code"], "approval_mode_mismatch")
        self.assertEqual(result["data"]["machine_operator_response"]["status"], "denied")
        self.assertFalse(result["data"]["backend_execution_performed"])
        self.assertFalse(result["data"]["machine_action_performed"])

    def test_backend_unavailable_audit_does_not_collapse_into_execution_failed(self):
        from assistant_os.mso.machine_operator_audit import (
            MACHINE_OPERATOR_AUDIT_LOG,
            MachineOperatorAuditEventType,
        )
        from assistant_os.pipelines.machine_operator_pipeline import execute

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post",
            side_effect=requests.ConnectionError("backend offline"),
        ):
            result = execute(self._plan(), "ctx-machine-backend-audit")

        event_types = [event.event_type for event in MACHINE_OPERATOR_AUDIT_LOG.events()]
        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["lane_outcome"], "backend_unavailable")
        self.assertIn(MachineOperatorAuditEventType.MO_BACKEND_UNAVAILABLE, event_types)
        self.assertNotIn(MachineOperatorAuditEventType.MO_EXECUTION_FAILED, event_types)
        self.assertNotIn(MachineOperatorAuditEventType.MO_ABORTED, event_types)
        self.assertIn(MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED, event_types)

    def test_duplicate_evidence_fails_closed_in_pipeline(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

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
            result = execute(self._plan(), "ctx-machine-duplicate-evidence")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorExecutionFailed")
        self.assertEqual(result["data"]["backend_status"], "invalid_backend_response")

    def test_success_path_does_not_retain_session_state_between_requests(self):
        from assistant_os.pipelines.machine_operator_pipeline import execute

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "observation": {
                "summary": "Snapshot captured.",
                "detail": "Independent ephemeral execution.",
                "structured_data": {"page_title": "Example Domain"},
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
                "duration_ms": 120,
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
            first = execute(self._plan(), "ctx-machine-session-1")
            second = execute(self._plan(), "ctx-machine-session-2")

        for result in (first, second):
            self.assertTrue(result["ok"])
            self.assertEqual(result["data"]["session_mode"], "ephemeral")
            self.assertFalse(result["data"]["session_reused"])
            self.assertFalse(result["data"]["session_persisted"])
            self.assertFalse(result["data"]["session_retained_after_terminal"])

    def test_routing_registry_adds_machine_operator_without_affecting_host(self):
        from assistant_os.contracts import ACTION_HOST_LIST_DIRECTORY, ACTION_MACHINE_OPERATOR_EXECUTE
        from assistant_os.core.routing import action_domain, get_pipeline
        from assistant_os.pipelines import host_pipeline, machine_operator_pipeline

        self.assertEqual(action_domain(ACTION_MACHINE_OPERATOR_EXECUTE), "MACHINE_OPERATOR")
        self.assertIs(get_pipeline("MACHINE_OPERATOR"), machine_operator_pipeline.execute)

        self.assertEqual(action_domain(ACTION_HOST_LIST_DIRECTORY), "HOST")
        self.assertIs(get_pipeline("HOST"), host_pipeline.execute)


if __name__ == "__main__":
    unittest.main()
