import http.client
import json
import time
import unittest
from unittest.mock import patch

from assistant_os.config import WEBHOOK_TOKEN
from assistant_os.webhook_server import WebhookHTTPServer, start_server_thread


class TestBackendOperabilityEndpoints(unittest.TestCase):
    server: WebhookHTTPServer
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
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

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        token: str | None = WEBHOOK_TOKEN,
    ) -> tuple[int, dict]:
        headers: dict[str, str] = {}
        payload = None
        if token is not None:
            headers["X-Assistant-Token"] = token
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode("utf-8")

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        conn.close()
        return response.status, json.loads(raw)

    def test_get_agents_registry_returns_ok_and_list(self) -> None:
        status, data = self._request("GET", "/agents/registry")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIsInstance(data["agents"], list)
        self.assertGreaterEqual(len(data["agents"]), 1)
        self.assertTrue(any(item["id"] == "code_executor" for item in data["agents"]))

        agent = data["agents"][0]
        self.assertIn("name", agent)
        self.assertIn("status", agent)
        self.assertIn("capabilities", agent)
        self.assertIn("requires_authority", agent)
        self.assertIn("requires_review", agent)

    def test_get_system_capabilities_returns_ok_and_features(self) -> None:
        status, data = self._request("GET", "/system/capabilities")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("features", data)
        self.assertIn("domains", data)
        self.assertIn("capabilities", data)
        self.assertTrue(data["features"]["authority_artifact"])
        self.assertTrue(data["features"]["replay_prevention"])
        self.assertTrue(data["features"]["runner_enforced"])
        self.assertIn(data["features"]["code_apply_mode"], ("stub", "real", "unknown"))
        self.assertIn(data["features"]["machine_operator"], ("available", "unavailable", "unknown"))
        self.assertIsInstance(data["capabilities"], list)
        self.assertTrue(any(item["id"] == "WORK_QUERY" for item in data["capabilities"]))

    def test_get_mso_state_returns_ok_and_operational_fields(self) -> None:
        status, data = self._request("GET", "/mso/state")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("operational_mode", data)
        self.assertIn("authority_status", data)
        self.assertIn("governance", data)
        self.assertIn("agents_available", data)
        self.assertIn("pending_confirmations", data)
        self.assertIn("active_executions", data)
        self.assertIn("recent_events", data)
        self.assertEqual(data["operational_mode"], "NORMAL")
        self.assertEqual(data["authority_status"], "active")
        self.assertGreaterEqual(data["agents_available"], 1)
        self.assertIsInstance(data["recent_events"], list)

    def test_get_system_assistant_state_returns_snapshot_and_interpretation(self) -> None:
        status, data = self._request("GET", "/system-assistant/state")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("snapshot", data)
        self.assertIn("interpretation", data)
        self.assertIsInstance(data["snapshot"], dict)
        self.assertIsInstance(data["interpretation"], dict)
        self.assertTrue(data["interpretation"]["narrative"])

    def test_get_system_assistant_state_does_not_invoke_kernel(self) -> None:
        with patch("assistant_os.core.orchestrator.handle_request") as kernel_mock:
            status, _ = self._request("GET", "/system-assistant/state")

        self.assertEqual(status, 200)
        kernel_mock.assert_not_called()

    def test_get_system_assistant_state_does_not_invoke_pipelines(self) -> None:
        with (
            patch("assistant_os.pipelines.host_pipeline.execute") as host_pipeline_mock,
            patch("assistant_os.pipelines.machine_operator_pipeline.execute") as mo_pipeline_mock,
        ):
            status, _ = self._request("GET", "/system-assistant/state")

        self.assertEqual(status, 200)
        host_pipeline_mock.assert_not_called()
        mo_pipeline_mock.assert_not_called()

    def test_get_system_assistant_state_does_not_invoke_agent_entrypoints(self) -> None:
        call_tracker: list[object] = []

        def tracking_entrypoint(request: object) -> object:
            call_tracker.append(request)
            return {}

        with patch(
            "assistant_os.agents.registry.AGENT_REGISTRY",
            {
                "test_agent": {
                    "name": "test_agent",
                    "domain": "TEST",
                    "version": "0.0.1",
                    "description": "Test agent",
                    "input_contract": "TestRequest",
                    "output_contract": "TestResult",
                    "requires_review": False,
                    "capability_scope": [],
                    "entrypoint": tracking_entrypoint,
                }
            },
        ):
            status, _ = self._request("GET", "/system-assistant/state")

        self.assertEqual(status, 200)
        self.assertEqual(call_tracker, [])

    def test_get_system_assistant_state_does_not_write_audit_records(self) -> None:
        with patch("assistant_os.storage.mso_store.persist_worker_security_event") as audit_mock:
            status, _ = self._request("GET", "/system-assistant/state")

        self.assertEqual(status, 200)
        audit_mock.assert_not_called()

    def test_get_system_assistant_state_handles_observer_failure_safely(self) -> None:
        with patch("assistant_os.webhook_server.observe_system", side_effect=RuntimeError("boom")):
            status, data = self._request("GET", "/system-assistant/state")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["snapshot"]["status"], "unavailable")
        self.assertGreater(len(data["snapshot"].get("warnings", [])), 0)
        self.assertEqual(data["interpretation"]["status"], "unavailable")
        self.assertNotIn("traceback", json.dumps(data).lower())

    def test_get_system_assistant_state_has_no_authority_fields(self) -> None:
        status, data = self._request("GET", "/system-assistant/state")

        self.assertEqual(status, 200)
        rendered = json.dumps(data)
        self.assertNotIn("execution_mode", rendered)
        self.assertNotIn("governance_verdict", rendered)
        self.assertNotIn("policy_decision", rendered)
        self.assertNotIn("GovernanceVerdict", rendered)
        self.assertNotIn("PolicyDecision", rendered)

    def test_chat_process_surface_is_preserved_in_metadata_and_audit_without_changing_execution_mode(self) -> None:
        captured: dict[str, dict] = {}

        def _fake_handle_request(req: dict) -> dict:
            captured["req"] = req
            return {
                "ok": True,
                "result_type": "plan_confirmation_required",
                "domain": "WORK",
                "message": "Confirmar",
                "data": {
                    "type": "plan_confirmation_required",
                    "plan": {
                        "plan_id": "plan-surface-1",
                        "preview": "Confirmar",
                    },
                    "plan_id": "plan-surface-1",
                    "governance_trace": {
                        "effective_execution_mode": "confirm",
                    },
                },
                "error": None,
            }

        with patch("assistant_os.core.orchestrator.handle_request", side_effect=_fake_handle_request):
            status, data = self._request(
                "POST",
                "/chat/process",
                body={
                    "text": "crea una tarea",
                    "surface": "system_chat",
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(captured["req"]["metadata"]["surface"], "system_chat")
        self.assertEqual(data["audit"]["surface"], "system_chat")
        self.assertEqual(data["audit"]["execution_mode"], "confirm")
        self.assertTrue(data["needs_confirmation"])


    # ── GET /mso/governance/recent ────────────────────────────────────────────

    def _insert_governance_decision(self, governance_ref: str = "test-gov-001", action: str = "ALLOW") -> None:
        from assistant_os.contracts import now_iso
        from assistant_os.mso.contracts import (
            DeterministicDecisionTrace,
            GovernanceDecision,
            GovernanceReason,
        )
        from assistant_os.mso.trace_aggregator import begin_trace_chain

        decision_trace = DeterministicDecisionTrace(
            decision_ref=f"dec-{governance_ref}",
            context_id=f"ctx-{governance_ref}",
            trace_id=f"trace-{governance_ref}",
            plan_id=governance_ref,
            domain="WORK",
            action="create_page",
            execution_mode="FULL_EXECUTE",
            operation="work_create",
            preview="",
            created_at=now_iso(),
        )
        gov_decision = GovernanceDecision(
            governance_ref=governance_ref,
            action=action,
            target_domain="WORK",
            target_action="create_page",
            effective_execution_mode="FULL_EXECUTE",
            risk_level="low",
            justification="test justification",
            reasons=[GovernanceReason(code="test_code", detail="test detail")],
            constraints=[],
            interventions=[],
            capability_mode="allow",
            base_execution_mode="FULL_EXECUTE",
            operational_mode="NORMAL",
            created_at=now_iso(),
        )
        begin_trace_chain(
            task_id=f"task-{governance_ref}",
            context_id=f"ctx-{governance_ref}",
            trace_id=f"trace-{governance_ref}",
            plan_id=governance_ref,
            request_text="test request",
            operation="work_create",
            domain="WORK",
            action="create_page",
            execution_mode="FULL_EXECUTE",
            created_at=now_iso(),
            advisory_trace=None,
            decision_trace=decision_trace,
            governance_decision=gov_decision,
        )

    def test_get_mso_governance_recent_returns_empty_on_fresh_store(self) -> None:
        status, data = self._request("GET", "/mso/governance/recent")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"], "mso_governance")
        self.assertEqual(data["decisions"], [])
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["limit"], 20)
        self.assertTrue(data["ephemeral"])

    def test_get_mso_governance_recent_requires_auth(self) -> None:
        status, data = self._request("GET", "/mso/governance/recent", token=None)

        self.assertEqual(status, 401)

    def test_get_mso_governance_recent_invalid_token(self) -> None:
        status, data = self._request("GET", "/mso/governance/recent", token="wrong-token")

        self.assertEqual(status, 401)

    def test_get_mso_governance_recent_returns_decisions_after_insert(self) -> None:
        self._insert_governance_decision(governance_ref="gov-abc", action="ALLOW")

        status, data = self._request("GET", "/mso/governance/recent")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["count"], 1)
        decision = data["decisions"][0]
        self.assertEqual(decision["governance_ref"], "gov-abc")
        self.assertEqual(decision["action"], "ALLOW")
        self.assertEqual(decision["target_domain"], "WORK")
        self.assertEqual(decision["risk_level"], "low")
        self.assertEqual(decision["operational_mode"], "NORMAL")
        self.assertIn("created_at", decision)
        self.assertIsInstance(decision["reasons"], list)
        self.assertEqual(decision["reasons"][0]["code"], "test_code")

    def test_get_mso_governance_recent_limit_param(self) -> None:
        for i in range(5):
            self._insert_governance_decision(governance_ref=f"gov-limit-{i}")

        status, data = self._request("GET", "/mso/governance/recent?limit=2")

        self.assertEqual(status, 200)
        self.assertEqual(data["limit"], 2)
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["decisions"]), 2)

    def test_get_mso_governance_recent_limit_clamped_to_max(self) -> None:
        status, data = self._request("GET", "/mso/governance/recent?limit=999")

        self.assertEqual(status, 200)
        self.assertEqual(data["limit"], 50)

    def test_get_mso_governance_recent_excludes_internal_fields(self) -> None:
        self._insert_governance_decision(governance_ref="gov-fields")

        status, data = self._request("GET", "/mso/governance/recent")

        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        decision = data["decisions"][0]
        self.assertNotIn("anomaly_signals", decision)
        self.assertNotIn("dynamic_factors", decision)
        self.assertNotIn("capability_mode", decision)
        self.assertNotIn("capability_source", decision)
        self.assertNotIn("base_execution_mode", decision)

    def test_get_mso_governance_recent_is_read_only(self) -> None:
        self._insert_governance_decision(governance_ref="gov-ro")

        _, first = self._request("GET", "/mso/governance/recent")
        _, second = self._request("GET", "/mso/governance/recent")

        self.assertEqual(first["count"], second["count"])
        self.assertEqual(first["decisions"][0]["governance_ref"], second["decisions"][0]["governance_ref"])

    def test_get_mso_governance_recent_serializes_dict_nested_fields(self) -> None:
        """Regression: orchestrator reconstructs GovernanceDecision via GovernanceDecision(**asdict(...)),
        which stores reasons/constraints/interventions as plain dicts instead of typed objects.
        The serializer must handle both without raising AttributeError."""
        from dataclasses import asdict
        from assistant_os.contracts import now_iso
        from assistant_os.mso.contracts import GovernanceDecision, GovernanceReason, GovernanceConstraint, GovernanceIntervention
        from assistant_os.mso.trace_aggregator import _lock, _recent_governance

        typed_decision = GovernanceDecision(
            governance_ref="gov-dict-regression",
            action="BLOCK",
            target_domain="ENERGY",
            target_action="COMMAND",
            effective_execution_mode="blocked",
            risk_level="high",
            justification="capability registry denied",
            reasons=[GovernanceReason(code="CAPABILITY_DENIED", detail="no registered capability")],
            constraints=[GovernanceConstraint(kind="mode_cap", value="blocked")],
            interventions=[GovernanceIntervention(kind="execution_block", value="blocked", reason="capability denied")],
            capability_mode="deny",
            base_execution_mode="FULL_EXECUTE",
            operational_mode="NORMAL",
            created_at=now_iso(),
        )
        # Simulate orchestrator line: GovernanceDecision(**asdict(governance))
        # asdict() converts nested dataclasses to plain dicts; the reconstructed object
        # stores reasons/constraints/interventions as list[dict], not typed instances.
        dict_decision = GovernanceDecision(**asdict(typed_decision))

        with _lock:
            _recent_governance.append(dict_decision)

        status, data = self._request("GET", "/mso/governance/recent")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"], msg=f"Expected ok:true but got: {data}")
        self.assertGreaterEqual(data["count"], 1)

        decision = next(
            (d for d in data["decisions"] if d["governance_ref"] == "gov-dict-regression"),
            None,
        )
        self.assertIsNotNone(decision, "gov-dict-regression not found in response")
        self.assertEqual(decision["action"], "BLOCK")
        self.assertEqual(decision["target_domain"], "ENERGY")
        self.assertEqual(decision["effective_execution_mode"], "blocked")

        self.assertIsInstance(decision["reasons"], list)
        self.assertEqual(len(decision["reasons"]), 1)
        self.assertEqual(decision["reasons"][0]["code"], "CAPABILITY_DENIED")
        self.assertEqual(decision["reasons"][0]["detail"], "no registered capability")

        self.assertIsInstance(decision["constraints"], list)
        self.assertEqual(len(decision["constraints"]), 1)
        self.assertEqual(decision["constraints"][0]["kind"], "mode_cap")
        self.assertEqual(decision["constraints"][0]["value"], "blocked")

        self.assertIsInstance(decision["interventions"], list)
        self.assertEqual(len(decision["interventions"]), 1)
        self.assertEqual(decision["interventions"][0]["kind"], "execution_block")
        self.assertEqual(decision["interventions"][0]["reason"], "capability denied")

        # Excluded internal fields must not be present
        self.assertNotIn("capability_mode", decision)
        self.assertNotIn("base_execution_mode", decision)
        self.assertNotIn("anomaly_signals", decision)
        self.assertNotIn("dynamic_factors", decision)


# ── GET /mso/governance/status ────────────────────────────────────────────────

class TestGovernanceStatusEndpoint(unittest.TestCase):
    server: WebhookHTTPServer
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        import time
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
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

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = WEBHOOK_TOKEN,
    ) -> tuple[int, dict]:
        headers: dict[str, str] = {}
        if token is not None:
            headers["X-Assistant-Token"] = token
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request(method, path, headers=headers)
        res = conn.getresponse()
        status = res.status
        data = json.loads(res.read().decode())
        conn.close()
        return status, data

    def test_get_mso_governance_status_returns_normal_on_fresh_store(self) -> None:
        status, data = self._request("GET", "/mso/governance/status")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"], "mso_governance")
        self.assertEqual(data["operational_mode"], "NORMAL")
        self.assertIn("operational_mode_reason", data)
        self.assertIn("operational_mode_source", data)
        self.assertIn("hardened_domains", data)
        self.assertIsInstance(data["hardened_domains"], list)
        self.assertEqual(data["hardened_domain_count"], 0)
        self.assertEqual(data["active_revocation_count"], 0)
        self.assertTrue(data["ephemeral"])

    def test_get_mso_governance_status_requires_auth(self) -> None:
        status, _data = self._request("GET", "/mso/governance/status", token=None)

        self.assertEqual(status, 401)

    def test_get_mso_governance_status_invalid_token(self) -> None:
        status, _data = self._request("GET", "/mso/governance/status", token="wrong-token")

        self.assertEqual(status, 401)

    def test_get_mso_governance_status_returns_frozen_when_override_active(self) -> None:
        from assistant_os.mso.system_state import set_operational_mode

        set_operational_mode("FROZEN", reason="test freeze")

        status, data = self._request("GET", "/mso/governance/status")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["operational_mode"], "FROZEN")
        self.assertEqual(data["operational_mode_reason"], "test freeze")
        self.assertIn(data["operational_mode_source"], ("manual", "override"))

    def test_get_mso_governance_status_is_read_only(self) -> None:
        _, first = self._request("GET", "/mso/governance/status")
        _, second = self._request("GET", "/mso/governance/status")

        self.assertEqual(first["operational_mode"], second["operational_mode"])


if __name__ == "__main__":
    unittest.main()
