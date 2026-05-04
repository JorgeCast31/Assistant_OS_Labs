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
        # Check for exact JSON key pattern — prevents false match on
        # "effective_execution_mode" which is a legitimate read-only descriptor.
        self.assertNotIn('"execution_mode":', rendered)
        self.assertNotIn("governance_verdict", rendered)
        self.assertNotIn("policy_decision", rendered)
        self.assertNotIn("GovernanceVerdict", rendered)
        self.assertNotIn("PolicyDecision", rendered)

    def test_get_system_assistant_state_snapshot_includes_governance_summary(self) -> None:
        status, data = self._request("GET", "/system-assistant/state")

        self.assertEqual(status, 200)
        snapshot = data.get("snapshot", {})
        self.assertIn("governance_status_summary", snapshot)
        gov = snapshot["governance_status_summary"]
        if gov is not None:
            self.assertIn("operational_mode", gov)
            self.assertIn("active_revocation_count", gov)
            self.assertIn("hardened_domain_count", gov)

    def test_get_system_assistant_state_governance_summary_fail_soft(self) -> None:
        with patch(
            "assistant_os.system_assistant.observer._read_governance_status_summary",
            side_effect=RuntimeError("governance surface down"),
        ):
            status, data = self._request("GET", "/system-assistant/state")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        snapshot = data.get("snapshot", {})
        self.assertIsNone(snapshot.get("governance_status_summary"))
        warnings = snapshot.get("warnings", [])
        self.assertTrue(
            any("governance" in w.lower() for w in warnings),
            f"Expected governance warning, got: {warnings}",
        )

    def test_get_system_assistant_state_recent_governance_field_present(self) -> None:
        status, data = self._request("GET", "/system-assistant/state")

        self.assertEqual(status, 200)
        snapshot = data.get("snapshot", {})
        self.assertIn("recent_governance", snapshot)
        recent = snapshot["recent_governance"]
        # recent_governance is list or None depending on source availability
        self.assertTrue(recent is None or isinstance(recent, list))

    def test_get_system_assistant_state_is_read_only(self) -> None:
        """Two successive reads must return consistent snapshot shapes."""
        _, data_a = self._request("GET", "/system-assistant/state")
        _, data_b = self._request("GET", "/system-assistant/state")

        self.assertTrue(data_a["ok"])
        self.assertTrue(data_b["ok"])
        # Governance summary keys must be present in both or absent in both
        snap_a = data_a.get("snapshot", {})
        snap_b = data_b.get("snapshot", {})
        self.assertEqual("governance_status_summary" in snap_a, "governance_status_summary" in snap_b)

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

    # -----------------------------------------------------------------
    # S-AUTH-SURFACE-01B: GET /mso/authority/status
    # -----------------------------------------------------------------

    def test_get_mso_authority_status_requires_auth(self) -> None:
        status, _ = self._request("GET", "/mso/authority/status", token=None)
        self.assertEqual(status, 401)

    def test_get_mso_authority_status_invalid_token(self) -> None:
        status, _ = self._request("GET", "/mso/authority/status", token="wrong-token")
        self.assertEqual(status, 401)

    def test_get_mso_authority_status_valid_auth_returns_ok_and_source(self) -> None:
        status, data = self._request("GET", "/mso/authority/status")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"], "authority_status")

    def test_get_mso_authority_status_includes_capabilities_counts_and_note(self) -> None:
        _, data = self._request("GET", "/mso/authority/status")
        self.assertIn("capabilities", data)
        self.assertIn("counts", data)
        self.assertIn("note", data)
        self.assertIsInstance(data["capabilities"], list)
        self.assertIsInstance(data["counts"], dict)

    def test_get_mso_authority_status_no_forbidden_fields(self) -> None:
        _, data = self._request("GET", "/mso/authority/status")
        serialized = json.dumps(data).lower()
        for forbidden in (
            "token",
            "signature",
            "authority_artifact",
            "execution_mode",
            "policy_decision",
            "governance_verdict",
            "approved",
            "authorized",
            "safe_to_apply",
            "ready_to_execute",
        ):
            self.assertNotIn(forbidden, serialized,
                             f"/mso/authority/status leaked forbidden field: {forbidden}")

    def test_get_mso_authority_status_post_not_200(self) -> None:
        status, _ = self._request("POST", "/mso/authority/status")
        self.assertNotEqual(status, 200)

    def test_get_mso_authority_status_fail_soft_on_producer_exception(self) -> None:
        with patch("assistant_os.mso.authority_status.get_authority_status",
                   side_effect=RuntimeError("authority producer unavailable")):
            status, data = self._request("GET", "/mso/authority/status")

        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["source"], "authority_status")
        self.assertEqual(data["capabilities"], [])
        self.assertEqual(data["counts"]["total"], 0)
        self.assertEqual(data["counts"]["allow"], 0)
        self.assertEqual(data["counts"]["confirm_only"], 0)
        self.assertEqual(data["counts"]["deny"], 0)
        self.assertEqual(data["counts"]["blocked"], 0)
        self.assertEqual(data["counts"]["active_grants"], 0)
        self.assertEqual(data["counts"]["active_revocations"], 0)
        self.assertIn("error", data)
        self.assertIn("does not grant execution permission", data["note"].lower())

    def test_get_mso_authority_status_calls_get_authority_status_not_registry(self) -> None:
        with patch("assistant_os.mso.authority_status.get_authority_status") as mock_fn:
            mock_fn.return_value = {
                "source": "authority_status",
                "feature_enabled": True,
                "last_health_check": "2026-01-01T00:00:00+00:00",
                "note": "Authority status is read-only posture, not execution permission.",
                "capabilities": [],
                "counts": {
                    "total": 0,
                    "allow": 0,
                    "confirm_only": 0,
                    "deny": 0,
                    "blocked": 0,
                    "active_grants": 0,
                    "active_revocations": 0,
                },
            }
            status, _ = self._request("GET", "/mso/authority/status")

        self.assertEqual(status, 200)
        mock_fn.assert_called_once()

    # -----------------------------------------------------------------
    # S-RESULT-OBS-01C: GET /mso/outcome/status
    # -----------------------------------------------------------------

    def test_get_mso_outcome_status_requires_auth_and_does_not_invoke_producer(self) -> None:
        with patch("assistant_os.mso.outcome_status.build_outcome_status") as mock_fn:
            status, _ = self._request("GET", "/mso/outcome/status", token=None)

        self.assertEqual(status, 401)
        mock_fn.assert_not_called()

    def test_get_mso_outcome_status_valid_auth_found_envelope(self) -> None:
        with patch("assistant_os.mso.outcome_status.build_outcome_status") as mock_fn:
            mock_fn.return_value = {
                "ok": True,
                "found": True,
                "query": {"plan_id": "plan-1", "context_id": "", "trace_id": "", "execution_id": ""},
                "outcome": {"status": "completed"},
                "correlation": {"plan_id": "plan-1"},
                "sources": {"trace_chain": True},
                "source_errors": [],
            }
            status, data = self._request("GET", "/mso/outcome/status?plan_id=plan-1")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertTrue(data["found"])
        self.assertEqual(data["source"], "outcome_status")
        self.assertEqual(
            data["note"],
            "Outcome status is observational; it does not grant execution permission.",
        )

    def test_get_mso_outcome_status_no_params_returns_not_found_with_note(self) -> None:
        status, data = self._request("GET", "/mso/outcome/status")

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertFalse(data["found"])
        self.assertEqual(data["outcome"]["status"], "not_found")
        self.assertEqual(data["source"], "outcome_status")
        self.assertIn("does not grant execution permission", data["note"])

    def test_get_mso_outcome_status_fail_soft_on_producer_exception(self) -> None:
        with patch(
            "assistant_os.mso.outcome_status.build_outcome_status",
            side_effect=RuntimeError("secret token traceback password raw_text"),
        ):
            status, data = self._request("GET", "/mso/outcome/status?plan_id=plan-1")

        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["source"], "outcome_status")
        self.assertEqual(data["error"], "outcome_status_unavailable")
        self.assertIn("does not grant execution permission", data["note"])
        self.assertNotIn("traceback", json.dumps(data).lower())

    def test_get_mso_outcome_status_post_method_not_allowed(self) -> None:
        status, _ = self._request("POST", "/mso/outcome/status")

        self.assertEqual(status, 405)

    def test_get_mso_outcome_status_forwards_query_params(self) -> None:
        with patch("assistant_os.mso.outcome_status.build_outcome_status") as mock_fn:
            mock_fn.return_value = {
                "ok": True,
                "found": False,
                "query": {},
                "outcome": {"status": "not_found"},
                "correlation": {},
                "sources": {},
                "source_errors": [],
            }
            status, _ = self._request(
                "GET",
                "/mso/outcome/status?plan_id=plan-1&context_id=ctx-1&trace_id=trace-1&execution_id=exec-1",
            )

        self.assertEqual(status, 200)
        mock_fn.assert_called_once_with(
            plan_id="plan-1",
            context_id="ctx-1",
            trace_id="trace-1",
            execution_id="exec-1",
        )

    def test_get_mso_outcome_status_fail_soft_response_has_no_sensitive_fields(self) -> None:
        with patch(
            "assistant_os.mso.outcome_status.build_outcome_status",
            side_effect=RuntimeError("token secret password raw_text traceback"),
        ):
            status, data = self._request("GET", "/mso/outcome/status?execution_id=exec-1")

        self.assertEqual(status, 200)
        serialized = json.dumps(data).lower()
        for forbidden in ("token", "secret", "password", "raw_text", "traceback"):
            self.assertNotIn(forbidden, serialized)

    def test_get_mso_outcome_status_source_and_note_all_paths(self) -> None:
        with patch("assistant_os.mso.outcome_status.build_outcome_status") as mock_fn:
            mock_fn.return_value = {
                "ok": True,
                "found": True,
                "query": {},
                "outcome": {"status": "completed"},
                "correlation": {},
                "sources": {},
                "source_errors": [],
            }
            _, found = self._request("GET", "/mso/outcome/status?plan_id=found")

        _, not_found = self._request("GET", "/mso/outcome/status")

        with patch("assistant_os.mso.outcome_status.build_outcome_status", side_effect=RuntimeError("boom")):
            _, producer_error = self._request("GET", "/mso/outcome/status?plan_id=boom")

        for data in (found, not_found, producer_error):
            self.assertEqual(data["source"], "outcome_status")
            self.assertEqual(
                data["note"],
                "Outcome status is observational; it does not grant execution permission.",
            )

    # -----------------------------------------------------------------
    # S-CODE-READINESS-01B: GET /code/readiness
    # -----------------------------------------------------------------

    def test_get_code_readiness_requires_auth(self) -> None:
        status, _ = self._request("GET", "/code/readiness", token=None)
        self.assertEqual(status, 401)

    def test_get_code_readiness_invalid_token(self) -> None:
        status, _ = self._request("GET", "/code/readiness", token="wrong-token")
        self.assertEqual(status, 401)

    def test_get_code_readiness_returns_envelope(self) -> None:
        status, data = self._request("GET", "/code/readiness")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"], "code_readiness")
        self.assertEqual(data["domain"], "CODE")
        self.assertIs(data["feature_enabled"], True)

    def test_get_code_readiness_contains_note_not_authority(self) -> None:
        _, data = self._request("GET", "/code/readiness")
        self.assertIn("note", data)
        self.assertIn("authority", data["note"].lower())

    def test_get_code_readiness_contains_apply_execution_mode(self) -> None:
        _, data = self._request("GET", "/code/readiness")
        self.assertIn("apply_execution_mode", data)
        self.assertIn(data["apply_execution_mode"], ("stub", "real"))

    def test_get_code_readiness_contains_capabilities(self) -> None:
        _, data = self._request("GET", "/code/readiness")
        self.assertIn("code_capabilities", data)
        self.assertIsInstance(data["code_capabilities"], list)
        for cap in data["code_capabilities"]:
            self.assertEqual(cap["domain"], "CODE")

    def test_get_code_readiness_has_no_authority_fields(self) -> None:
        _, data = self._request("GET", "/code/readiness")
        for forbidden in (
            "execution_mode",
            "effective_execution_mode",
            "governance_verdict",
            "governance_decision",
            "policy_decision",
            "authorized",
            "approved",
        ):
            self.assertNotIn(forbidden, data,
                             f"/code/readiness leaked authority field: {forbidden}")

    def test_get_code_readiness_post_method_not_allowed(self) -> None:
        # The TestGovernanceStatusEndpoint helper does not accept body; the
        # routing check on the server runs before any body is read, so a
        # bare POST exercises the same path. Webhook returns 405 (or other
        # non-2xx) for POST on read-only paths.
        status, _ = self._request("POST", "/code/readiness")
        self.assertNotEqual(status, 200)

    def test_get_code_readiness_fail_soft_on_producer_exception(self) -> None:
        # If the producer raises, the endpoint must still return a structured
        # envelope (ok=False) rather than a 500 traceback.
        with patch("assistant_os.codeops.readiness.get_code_readiness",
                   side_effect=RuntimeError("boom")):
            status, data = self._request("GET", "/code/readiness")
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["source"], "code_readiness")
        self.assertEqual(data["domain"], "CODE")
        self.assertIn("error", data)
        self.assertIn("note", data)

    def test_get_code_readiness_does_not_create_executions(self) -> None:
        # Calling the endpoint must not append to the executions registry.
        # We verify by counting executions before and after.
        from assistant_os.api import code_api as _code_api
        before = len(_code_api.handle_list_executions().get("executions", []))
        _, _ = self._request("GET", "/code/readiness")
        after = len(_code_api.handle_list_executions().get("executions", []))
        self.assertEqual(before, after)

    # -----------------------------------------------------------------
    # S-CONFIRM-FLOW-01B: GET /confirm/pending
    # -----------------------------------------------------------------

    def test_get_confirm_pending_requires_auth(self) -> None:
        status, _ = self._request("GET", "/confirm/pending", token=None)
        self.assertEqual(status, 401)

    def test_get_confirm_pending_invalid_token(self) -> None:
        status, _ = self._request("GET", "/confirm/pending", token="invalid-token")
        self.assertEqual(status, 401)

    def test_get_confirm_pending_valid_auth_returns_ok_and_source(self) -> None:
        status, data = self._request("GET", "/confirm/pending")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"], "confirm_flow")

    def test_get_confirm_pending_response_shape(self) -> None:
        _, data = self._request("GET", "/confirm/pending")
        self.assertIn("pending_count", data)
        self.assertIn("expired_pending_count", data)
        self.assertIn("pending", data)
        self.assertIsInstance(data["pending"], list)
        self.assertIn("note", data)
        self.assertIn("confirm", data["note"].lower())

    def test_get_confirm_pending_limit_param_passed(self) -> None:
        with patch("assistant_os.confirm_flow.readiness.get_confirm_flow_summary") as mock_fn:
            mock_fn.return_value = {
                "source": "confirm_flow",
                "feature_enabled": True,
                "last_health_check": "2026-01-01T00:00:00+00:00",
                "note": "observability only",
                "pending_count": 0,
                "expired_pending_count": 0,
                "pending": [],
            }
            _, _ = self._request("GET", "/confirm/pending?limit=5")
        mock_fn.assert_called_once_with(limit=5)

    def test_get_confirm_pending_limit_clamped_high(self) -> None:
        with patch("assistant_os.confirm_flow.readiness.get_confirm_flow_summary") as mock_fn:
            mock_fn.return_value = {
                "source": "confirm_flow",
                "feature_enabled": True,
                "last_health_check": "2026-01-01T00:00:00+00:00",
                "note": "observability only",
                "pending_count": 0,
                "expired_pending_count": 0,
                "pending": [],
            }
            _, _ = self._request("GET", "/confirm/pending?limit=999")
        mock_fn.assert_called_once_with(limit=50)

    def test_get_confirm_pending_invalid_limit_falls_back_to_default(self) -> None:
        with patch("assistant_os.confirm_flow.readiness.get_confirm_flow_summary") as mock_fn:
            mock_fn.return_value = {
                "source": "confirm_flow",
                "feature_enabled": True,
                "last_health_check": "2026-01-01T00:00:00+00:00",
                "note": "observability only",
                "pending_count": 0,
                "expired_pending_count": 0,
                "pending": [],
            }
            _, _ = self._request("GET", "/confirm/pending?limit=notanint")
        mock_fn.assert_called_once_with(limit=10)

    def test_get_confirm_pending_no_forbidden_authority_fields(self) -> None:
        _, data = self._request("GET", "/confirm/pending")
        for forbidden in (
            "plan",
            "raw_text",
            "execution_plan",
            "policy_decision",
            "authorized",
            "approved",
            "ready_to_confirm",
            "safe_to_apply",
            "execution_mode",
            "governance_verdict",
        ):
            self.assertNotIn(forbidden, data,
                             f"/confirm/pending leaked forbidden field: {forbidden}")

    def test_get_confirm_pending_post_not_200(self) -> None:
        status, _ = self._request("POST", "/confirm/pending")
        self.assertNotEqual(status, 200)

    def test_get_confirm_pending_fail_soft_on_producer_exception(self) -> None:
        with patch("assistant_os.confirm_flow.readiness.get_confirm_flow_summary",
                   side_effect=RuntimeError("store unavailable")):
            status, data = self._request("GET", "/confirm/pending")
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["source"], "confirm_flow")
        self.assertIn("error", data)
        self.assertIn("note", data)
        self.assertEqual(data["pending_count"], 0)
        self.assertEqual(data["pending"], [])

    def test_get_confirm_pending_calls_get_confirm_flow_summary_not_context_store(self) -> None:
        with patch("assistant_os.confirm_flow.readiness.get_confirm_flow_summary") as mock_fn:
            mock_fn.return_value = {
                "source": "confirm_flow",
                "feature_enabled": True,
                "last_health_check": "2026-01-01T00:00:00+00:00",
                "note": "observability only",
                "pending_count": 0,
                "expired_pending_count": 0,
                "pending": [],
            }
            status, data = self._request("GET", "/confirm/pending")
        self.assertEqual(status, 200)
        mock_fn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
