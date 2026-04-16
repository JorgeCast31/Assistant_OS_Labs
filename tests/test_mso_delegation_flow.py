import unittest
from unittest.mock import patch


class TestMsoDelegationFlow(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator
        from assistant_os.storage.mso_store import clear_mso_store

        reset_dynamic_capabilities()
        clear_operational_mode_override()
        reset_task_registry()
        reset_trace_aggregator()
        clear_mso_store()

    def _request(self, *, domain_payload: dict, risk_level: str = "low") -> dict:
        from assistant_os.contracts import ACTION_BASIC_COGNITIVE_EXECUTION, normalize_request

        return normalize_request(
            text="run bounded cognitive diagnostic",
            metadata={
                "action": ACTION_BASIC_COGNITIVE_EXECUTION,
                "domain": "COGNITIVE",
                "target": "bounded cognitive diagnostic",
                "risk_level": risk_level,
                "requires_confirmation": False,
                "domain_payload": domain_payload,
            },
        )

    def _payload(self, **task_overrides) -> dict:
        return {
            "sovereign_intent": {
                "intent_id": "intent-1",
                "session_id": "session-1",
                "user_request_ref": "request:1",
                "interpreted_goal": "Inspect current operational state.",
                "priority": "normal",
                "persistence_recommendation": "none",
                "risk_posture_hint": "low",
                "delegation_recommendation": "delegate_basic_cognitive_execution",
                "justification_summary": "Need bounded internal analysis.",
                "timestamp": "2026-04-14T00:00:00+00:00",
            },
            "delegation_task": {
                "task_id": "task-1",
                "origin_intent_id": "intent-1",
                "task_type": "BASIC_COGNITIVE_EXECUTION",
                "task_goal": "Read current system state and summarize it.",
                "allowed_operations": ["read_system_state", "summarize_context"],
                "input_refs": ["request:1", "state:current"],
                "scope": {"domain": "COGNITIVE", "max_items": 5},
                "requires_capability": "BASIC_COGNITIVE_EXECUTION",
                "expected_output_schema": {"required_artifact_keys": ["system_state", "summary"]},
                "expiry": "2099-01-01T00:00:00+00:00",
                "trace_id": "trace-task-1",
                **task_overrides,
            },
        }

    @patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None)
    def test_valid_worker_delegation_returns_execution_report(self, _mock_advisory):
        from assistant_os.contracts import RESULT_TYPE_COGNITIVE_EXECUTION
        from assistant_os.core.orchestrator import handle_request

        result = handle_request(self._request(domain_payload=self._payload()))

        self.assertEqual(result["result_type"], RESULT_TYPE_COGNITIVE_EXECUTION)
        self.assertTrue(result["ok"])
        self.assertIn("execution_report", result["data"])
        self.assertEqual(result["data"]["execution_report"]["worker_id"], "local_cognitive_worker")

    @patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None)
    def test_worker_blocked_without_capability_due_to_revocation(self, _mock_advisory):
        from assistant_os.contracts import ACTION_BASIC_COGNITIVE_EXECUTION
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.mso.capability_registry import revoke_capability

        revoke_capability(action=ACTION_BASIC_COGNITIVE_EXECUTION, domain="COGNITIVE", reason="maintenance freeze")
        result = handle_request(self._request(domain_payload=self._payload()))

        self.assertEqual(result["result_type"], "plan_generated")
        self.assertEqual(result["data"]["governance_trace"]["action"], "BLOCK")
        self.assertEqual(result["data"]["governance_trace"]["capability_source"], "revocation")

    @patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None)
    def test_trace_continuity_links_intent_task_capability_and_report(self, _mock_advisory):
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.mso.governance_surface import get_trace_view

        result = handle_request(self._request(domain_payload=self._payload()))
        trace = get_trace_view(result["plan_id"])

        self.assertIsNotNone(trace)
        self.assertEqual(trace.sovereign_intent["intent_id"], "intent-1")
        self.assertEqual(trace.delegation_task["task_id"], "task-1")
        self.assertEqual(trace.execution_capability["execution_class"], "BASIC_COGNITIVE_EXECUTION")
        self.assertEqual(trace.execution_report["task_id"], "task-1")

    @patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None)
    def test_escalation_request_is_returned_when_schema_requires_more(self, _mock_advisory):
        from assistant_os.contracts import RESULT_TYPE_COGNITIVE_EXECUTION
        from assistant_os.core.orchestrator import handle_request

        payload = self._payload(expected_output_schema={"required_artifact_keys": ["system_state", "summary", "extra"]})
        result = handle_request(self._request(domain_payload=payload))

        self.assertEqual(result["result_type"], RESULT_TYPE_COGNITIVE_EXECUTION)
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["data"]["escalation_request"])
        self.assertEqual(result["data"]["escalation_request"]["current_limit_hit"], "expected_output_schema")


if __name__ == "__main__":
    unittest.main()
