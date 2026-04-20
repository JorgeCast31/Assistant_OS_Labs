"""
Sprint ALFA — Invariant tests for the minimal coherent canonical core.

Goal: prove that "any real execution passes through a single, consistent,
governed route" by testing the four ALFA closures:

  Section 1 — FROZEN mode: OperationalMode has FROZEN, governance blocks all execution
  Section 2 — Kill-switch governance gate in /chat/process
  Section 3 — Confirm replay governance check (FROZEN/DEGRADED blocks confirmed plans)
  Section 4 — Kill-switch endpoint /admin/governance/mode (structure + auth)
  Section 5 — Canonical route invariants (OpenClaw subordinate, bypasses dead)
"""

import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Section 1 — FROZEN mode in OperationalMode + governance gate
# ---------------------------------------------------------------------------

class TestFrozenOperationalMode(unittest.TestCase):
    """FROZEN is a valid OperationalMode and governance blocks execution on it."""

    def test_frozen_in_operational_mode_literal(self):
        """'FROZEN' must be part of the OperationalMode Literal."""
        from assistant_os.mso.contracts import OperationalMode
        import typing
        args = typing.get_args(OperationalMode)
        self.assertIn("FROZEN", args, "OperationalMode must include 'FROZEN'")

    def test_frozen_blocks_before_capability_check(self):
        """FROZEN governance decision must arrive before any capability check."""
        from assistant_os.mso.governance_engine import evaluate_governance
        from assistant_os.mso.contracts import RiskEvaluation, SystemStateSnapshot, GovernanceReason
        from assistant_os.contracts import EXECUTION_MODE_AUTO, EXECUTION_MODE_BLOCKED, now_iso

        # Build a minimal snapshot with FROZEN mode
        snap = MagicMock(spec=SystemStateSnapshot)
        snap.operational_mode = "FROZEN"
        snap.operational_mode_source = "manual"
        snap.recent_anomaly_signals = []
        snap.domain_operational_states = []

        risk = RiskEvaluation(
            level="low",
            operational_mode="FROZEN",
            base_risk="low",
            reasons=[],
            anomaly_detected=False,
        )

        decision = evaluate_governance(
            action="WORK_QUERY",
            domain="WORK",
            base_execution_mode=EXECUTION_MODE_AUTO,
            risk=risk,
            created_at=now_iso(),
            system_state=snap,
        )

        self.assertEqual(decision.effective_execution_mode, EXECUTION_MODE_BLOCKED)
        self.assertIn("FROZEN", decision.justification)

    def test_frozen_blocks_even_low_risk_whitelisted_action(self):
        """FROZEN must block even a whitelisted auto action."""
        from assistant_os.mso.governance_engine import evaluate_governance
        from assistant_os.mso.contracts import RiskEvaluation, SystemStateSnapshot
        from assistant_os.contracts import EXECUTION_MODE_AUTO, EXECUTION_MODE_BLOCKED, now_iso

        snap = MagicMock(spec=SystemStateSnapshot)
        snap.operational_mode = "FROZEN"
        snap.operational_mode_source = "manual"
        snap.recent_anomaly_signals = []
        snap.domain_operational_states = []

        risk = RiskEvaluation(
            level="low",
            operational_mode="FROZEN",
            base_risk="low",
            reasons=[],
            anomaly_detected=False,
        )

        # WORK_QUERY is normally allowed as auto
        decision = evaluate_governance(
            action="WORK_QUERY",
            domain="WORK",
            base_execution_mode=EXECUTION_MODE_AUTO,
            risk=risk,
            created_at=now_iso(),
            system_state=snap,
        )
        self.assertEqual(decision.effective_execution_mode, EXECUTION_MODE_BLOCKED)

    def test_frozen_action_is_block(self):
        """GovernanceDecision.action must be 'BLOCK' under FROZEN."""
        from assistant_os.mso.governance_engine import evaluate_governance
        from assistant_os.mso.contracts import RiskEvaluation, SystemStateSnapshot
        from assistant_os.contracts import EXECUTION_MODE_AUTO, now_iso

        snap = MagicMock(spec=SystemStateSnapshot)
        snap.operational_mode = "FROZEN"
        snap.operational_mode_source = "manual"
        snap.recent_anomaly_signals = []
        snap.domain_operational_states = []

        risk = RiskEvaluation(
            level="low", operational_mode="FROZEN", base_risk="low",
            reasons=[], anomaly_detected=False,
        )

        decision = evaluate_governance(
            action="FIN_EXPENSE", domain="FIN",
            base_execution_mode=EXECUTION_MODE_AUTO,
            risk=risk, created_at=now_iso(), system_state=snap,
        )
        self.assertEqual(decision.action, "BLOCK")

    def test_normal_mode_is_still_valid(self):
        """Ensure NORMAL mode still passes through governance unaffected."""
        from assistant_os.mso.governance_engine import evaluate_governance
        from assistant_os.mso.contracts import RiskEvaluation, SystemStateSnapshot
        from assistant_os.contracts import EXECUTION_MODE_AUTO, now_iso

        snap = MagicMock(spec=SystemStateSnapshot)
        snap.operational_mode = "NORMAL"
        snap.operational_mode_source = "derived"
        snap.recent_anomaly_signals = []
        snap.domain_operational_states = []

        risk = RiskEvaluation(
            level="low", operational_mode="NORMAL", base_risk="low",
            reasons=[], anomaly_detected=False,
        )

        decision = evaluate_governance(
            action="WORK_QUERY", domain="WORK",
            base_execution_mode=EXECUTION_MODE_AUTO,
            risk=risk, created_at=now_iso(), system_state=snap,
        )
        self.assertEqual(decision.effective_execution_mode, EXECUTION_MODE_AUTO)

    def test_system_state_set_and_get_frozen(self):
        """set_operational_mode accepts FROZEN without raising."""
        from assistant_os.mso.system_state import (
            set_operational_mode,
            get_operational_mode_override,
            clear_operational_mode_override,
        )
        try:
            set_operational_mode("FROZEN", reason="test freeze")
            mode, reason = get_operational_mode_override()
            self.assertEqual(mode, "FROZEN")
            self.assertEqual(reason, "test freeze")
        finally:
            clear_operational_mode_override()

    def test_snapshot_reflects_frozen_override(self):
        """build_system_state_snapshot returns FROZEN when override is set."""
        from assistant_os.mso.system_state import (
            set_operational_mode,
            build_system_state_snapshot,
            clear_operational_mode_override,
        )
        try:
            set_operational_mode("FROZEN", reason="alfa test")
            snap = build_system_state_snapshot()
            self.assertEqual(snap.operational_mode, "FROZEN")
        finally:
            clear_operational_mode_override()


# ---------------------------------------------------------------------------
# Section 2 — Governance gate in /chat/process
# ---------------------------------------------------------------------------

class TestChatProcessGovernanceGate(unittest.TestCase):
    """
    /chat/process must be blocked when the system is FROZEN or DEGRADED.

    The gate was added to close B1: chat_core executes mutations (Notion,
    Sheets) directly without going through handle_request / policy / token.
    The governance gate is the minimum closure that closes this bypass for ALFA.
    """

    def _source_check(self, keyword: str) -> bool:
        """Check that keyword appears in _handle_chat_process source body."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._handle_chat_process)
        return keyword in src

    def test_frozen_keyword_present_in_chat_process(self):
        """_handle_chat_process source must contain FROZEN governance check."""
        self.assertTrue(
            self._source_check("FROZEN"),
            "_handle_chat_process must check for FROZEN operational mode",
        )

    def test_degraded_keyword_present_in_chat_process(self):
        """_handle_chat_process source must check DEGRADED mode."""
        self.assertTrue(
            self._source_check("DEGRADED"),
            "_handle_chat_process must check for DEGRADED operational mode",
        )

    def test_governance_snapshot_called_in_chat_process(self):
        """build_system_state_snapshot must be imported/called in chat process."""
        self.assertTrue(
            self._source_check("build_system_state_snapshot"),
            "_handle_chat_process must call build_system_state_snapshot",
        )

    def test_503_returned_when_frozen(self):
        """Live /chat/process must return 503 when system is FROZEN."""
        import http.client, json, threading, time, http.server
        from assistant_os.webhook_server import WebhookHandler
        from assistant_os.mso.system_state import set_operational_mode, clear_operational_mode_override
        from assistant_os.config import WEBHOOK_TOKEN

        server = http.server.HTTPServer(("127.0.0.1", 0), WebhookHandler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        time.sleep(0.05)

        try:
            set_operational_mode("FROZEN", reason="test")
            conn = http.client.HTTPConnection("127.0.0.1", port)
            body = json.dumps({"text": "crea una tarea de prueba"}).encode()
            conn.request("POST", "/chat/process", body, {
                "Content-Type": "application/json",
                "X-Assistant-Token": WEBHOOK_TOKEN,
            })
            resp = conn.getresponse()
            data = json.loads(resp.read())
            self.assertEqual(resp.status, 503)
            self.assertFalse(data["ok"])
            self.assertIn(data.get("error"), ("governance_blocked", "governance_check_failed"))
        finally:
            clear_operational_mode_override()
            server.shutdown()

    def test_503_returned_when_degraded(self):
        """Live /chat/process must return 503 when system is DEGRADED."""
        import http.client, json, threading, time, http.server
        from assistant_os.webhook_server import WebhookHandler
        from assistant_os.mso.system_state import set_operational_mode, clear_operational_mode_override
        from assistant_os.config import WEBHOOK_TOKEN

        server = http.server.HTTPServer(("127.0.0.1", 0), WebhookHandler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        time.sleep(0.05)

        try:
            set_operational_mode("DEGRADED", reason="test")
            conn = http.client.HTTPConnection("127.0.0.1", port)
            body = json.dumps({"text": "crea una tarea"}).encode()
            conn.request("POST", "/chat/process", body, {
                "Content-Type": "application/json",
                "X-Assistant-Token": WEBHOOK_TOKEN,
            })
            resp = conn.getresponse()
            data = json.loads(resp.read())
            self.assertEqual(resp.status, 503)
            self.assertFalse(data["ok"])
        finally:
            clear_operational_mode_override()
            server.shutdown()


# ---------------------------------------------------------------------------
# Section 3 — Confirm replay governance check
# ---------------------------------------------------------------------------

class TestConfirmReplayGovernanceCheck(unittest.TestCase):
    """
    _execute_confirmed_plan must block when system is FROZEN or DEGRADED
    at confirm time — even if the plan was originally approved.
    """

    def _source_check(self, keyword: str) -> bool:
        import inspect
        from assistant_os.core import orchestrator
        src = inspect.getsource(orchestrator._execute_confirmed_plan)
        return keyword in src

    def test_frozen_check_present_in_execute_confirmed_plan(self):
        """_execute_confirmed_plan must contain FROZEN governance check."""
        self.assertTrue(
            self._source_check("FROZEN"),
            "_execute_confirmed_plan must check FROZEN before executing pipeline",
        )

    def test_degraded_check_present_in_execute_confirmed_plan(self):
        """_execute_confirmed_plan must contain DEGRADED governance check."""
        self.assertTrue(
            self._source_check("DEGRADED"),
            "_execute_confirmed_plan must check DEGRADED before executing pipeline",
        )

    def test_governance_snapshot_in_confirm_path(self):
        """_execute_confirmed_plan must import/use build_system_state_snapshot."""
        self.assertTrue(
            self._source_check("build_system_state_snapshot"),
            "_execute_confirmed_plan must call build_system_state_snapshot",
        )

    def test_confirm_blocked_when_frozen(self):
        """When system is FROZEN, _execute_confirmed_plan returns GovernanceBlocked error."""
        from assistant_os.mso.system_state import (
            set_operational_mode,
            clear_operational_mode_override,
        )
        from assistant_os.context_store import store_pending_plan, clear_store
        from assistant_os.contracts import make_plan, ACTION_WORK_CREATE
        from assistant_os.core.orchestrator import _execute_confirmed_plan

        clear_store()
        plan = make_plan(domain="WORK", action=ACTION_WORK_CREATE, target="test task")
        plan_id = plan["plan_id"]
        store_pending_plan(plan_id, plan, "WORK_CREATE")

        try:
            set_operational_mode("FROZEN", reason="alfa test")
            result = _execute_confirmed_plan(plan_id, "ctx-frozen-test")

            self.assertFalse(result["ok"])
            self.assertIn("GovernanceBlocked", result.get("error", {}).get("type", ""))
            self.assertIn("FROZEN", result.get("message", ""))
        finally:
            clear_operational_mode_override()
            clear_store()

    def test_confirm_blocked_when_degraded(self):
        """When system is DEGRADED, _execute_confirmed_plan returns GovernanceBlocked error."""
        from assistant_os.mso.system_state import (
            set_operational_mode,
            clear_operational_mode_override,
        )
        from assistant_os.context_store import store_pending_plan, clear_store
        from assistant_os.contracts import make_plan, ACTION_WORK_CREATE
        from assistant_os.core.orchestrator import _execute_confirmed_plan

        clear_store()
        plan = make_plan(domain="WORK", action=ACTION_WORK_CREATE, target="test task")
        plan_id = plan["plan_id"]
        store_pending_plan(plan_id, plan, "WORK_CREATE")

        try:
            set_operational_mode("DEGRADED", reason="alfa test")
            result = _execute_confirmed_plan(plan_id, "ctx-degraded-test")

            self.assertFalse(result["ok"])
            self.assertIn("GovernanceBlocked", result.get("error", {}).get("type", ""))
            self.assertIn("DEGRADED", result.get("message", ""))
        finally:
            clear_operational_mode_override()
            clear_store()

    def test_confirm_proceeds_when_normal(self):
        """When system is NORMAL, _execute_confirmed_plan proceeds to pipeline."""
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.context_store import store_pending_plan, clear_store
        from assistant_os.contracts import (
            make_plan, ACTION_WORK_QUERY,
            make_domain_result, RESULT_TYPE_WORK_QUERY,
        )
        from assistant_os.core.orchestrator import _execute_confirmed_plan

        clear_store()
        clear_operational_mode_override()

        plan = make_plan(domain="WORK", action=ACTION_WORK_QUERY, target="test")
        plan_id = plan["plan_id"]
        store_pending_plan(plan_id, plan, "WORK_QUERY")

        with patch("assistant_os.pipelines.work_pipeline._work_query_execute") as mock_exec:
            mock_exec.return_value = make_domain_result(
                ok=True, result_type=RESULT_TYPE_WORK_QUERY,
                domain="WORK", message="ok", data={},
            )
            result = _execute_confirmed_plan(plan_id, "ctx-normal-test")

        # Pipeline was reached (plan not blocked by governance)
        mock_exec.assert_called_once()
        self.assertTrue(result["ok"])

        clear_store()


# ---------------------------------------------------------------------------
# Section 4 — Kill-switch endpoint /admin/governance/mode
# ---------------------------------------------------------------------------

class TestGovernanceModeEndpoint(unittest.TestCase):
    """
    POST /admin/governance/mode must be reachable, auth-gated, and functional.
    """

    def _make_server(self):
        import http.server
        import threading, time
        from assistant_os.webhook_server import WebhookHandler
        server = http.server.HTTPServer(("127.0.0.1", 0), WebhookHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.05)
        return server, port

    def _request(self, port, body: dict, *, admin_token: str = ""):
        import http.client, json
        from assistant_os.config import WEBHOOK_TOKEN
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        if admin_token:
            headers["X-Assistant-Admin-Token"] = admin_token
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("POST", "/admin/governance/mode",
                     json.dumps(body).encode(), headers)
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())

    def test_endpoint_exists_in_do_post(self):
        """POST /admin/governance/mode route must be registered in do_POST."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler.do_POST)
        self.assertIn("/admin/governance/mode", src)

    def test_handler_method_exists(self):
        """_handle_governance_mode method must exist on WebhookHandler."""
        from assistant_os.webhook_server import WebhookHandler
        self.assertTrue(
            hasattr(WebhookHandler, "_handle_governance_mode"),
            "WebhookHandler must have _handle_governance_mode method",
        )

    def test_401_without_auth(self):
        """Returns 401 when X-Assistant-Token header is missing."""
        import http.client, json
        server, port = self._make_server()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request("POST", "/admin/governance/mode",
                         json.dumps({"mode": "FROZEN", "reason": "test"}).encode(),
                         {"Content-Type": "application/json"})  # no X-Assistant-Token
            resp = conn.getresponse()
            self.assertIn(resp.status, (401, 403))
        finally:
            server.shutdown()

    def test_set_frozen_and_clear(self):
        """Endpoint sets FROZEN and returns mode; NORMAL clears it.

        When WEBHOOK_ADMIN_TOKEN is empty in config, any non-empty admin token
        passes Layer 2 (permissive fallback — same as schema endpoints).
        """
        from assistant_os.mso.system_state import clear_operational_mode_override
        server, port = self._make_server()
        try:
            # Set FROZEN — pass any non-empty token (WEBHOOK_ADMIN_TOKEN="" → permissive)
            status, data = self._request(
                port,
                {"mode": "FROZEN", "reason": "alfa kill-switch test"},
                admin_token="any-token-when-not-configured",
            )
            self.assertEqual(status, 200, data)
            self.assertTrue(data["ok"])
            self.assertEqual(data["mode"], "FROZEN")
            self.assertFalse(data["cleared"])

            # Clear
            status2, data2 = self._request(
                port,
                {"mode": "NORMAL", "reason": ""},
                admin_token="any-token-when-not-configured",
            )
            self.assertEqual(status2, 200, data2)
            self.assertTrue(data2["cleared"])
        finally:
            clear_operational_mode_override()
            server.shutdown()

    def test_invalid_mode_returns_400(self):
        """Unknown mode value returns 400."""
        server, port = self._make_server()
        try:
            status, data = self._request(
                port,
                {"mode": "APOCALYPSE", "reason": "test"},
                admin_token="any-token-when-not-configured",
            )
            self.assertEqual(status, 400)
            # _make_json_error returns {"status": "error", ...} shape
            self.assertIn(data.get("status"), ("error",))
        finally:
            server.shutdown()

    def test_non_normal_requires_reason(self):
        """Setting a non-NORMAL mode without a reason returns 400."""
        server, port = self._make_server()
        try:
            status, data = self._request(
                port,
                {"mode": "FROZEN"},  # no reason
                admin_token="any-token-when-not-configured",
            )
            self.assertEqual(status, 400)
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# Section 5 — Canonical route invariants
# ---------------------------------------------------------------------------

class TestCanonicalRouteInvariantsALFA(unittest.TestCase):
    """
    Structural invariants that must hold for ALFA coherence.
    """

    def test_four_bypass_methods_raise_runtime_error(self):
        """All 4 neutered bypass methods must raise RuntimeError (A2-FIX)."""
        from assistant_os.webhook_server import WebhookHandler
        handler = MagicMock(spec=WebhookHandler)
        plan = {}

        for method_name in (
            "_execute_work_create",
            "_execute_work_delete",
            "_execute_work_update",
            "_execute_work_update_bulk",
        ):
            method = getattr(WebhookHandler, method_name)
            with self.subTest(method=method_name):
                with self.assertRaises(RuntimeError, msg=f"{method_name} must raise RuntimeError"):
                    method(handler, plan, "ctx-test")

    def test_handle_request_is_canonical_dispatcher(self):
        """handle_request must call evaluate_policy before any execution."""
        import inspect
        from assistant_os.core.orchestrator import handle_request
        src = inspect.getsource(handle_request)
        self.assertIn("evaluate_policy", src)
        self.assertIn("_require_token", src)
        self.assertIn("issue_token", src)

    def test_execute_confirmed_plan_single_use_remove_before_execute(self):
        """_execute_confirmed_plan removes plan BEFORE pipeline executes."""
        import inspect
        from assistant_os.core import orchestrator
        src = inspect.getsource(orchestrator._execute_confirmed_plan)
        # remove_pending_plan must appear before pipeline(plan, context_id)
        remove_pos = src.find("remove_pending_plan")
        pipeline_pos = src.find("return pipeline(plan, context_id)")
        self.assertGreater(pipeline_pos, remove_pos,
            "remove_pending_plan must come before pipeline execution")

    def test_openclaw_is_subordinate_to_host_pipeline(self):
        """OpenClaw is only invoked from within host_pipeline.execute — not directly."""
        import inspect
        from assistant_os.pipelines import host_pipeline
        src = inspect.getsource(host_pipeline)
        # openclaw is only called from within _dispatch, which is called by execute
        self.assertIn("execute_host_action_via_openclaw", src)
        # verify it is NOT imported in webhook_server
        import pathlib
        ws_src = pathlib.Path(
            "assistant_os/webhook_server.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("openclaw", ws_src.lower().replace("# openclaw", ""),
            "webhook_server must not import openclaw directly")

    def test_chat_core_execution_helpers_exist_but_are_fenced(self):
        """
        chat_core._execute_work_delete / _execute_work_item exist (they are
        the direct-execution helpers that are now fenced by the governance
        gate in _handle_chat_process before process_chat_input is called).
        """
        import inspect
        from assistant_os import chat_core
        src = inspect.getsource(chat_core)
        # These helpers still exist (they are not removed yet — ALFA doesn't
        # restructure chat_core; it fences the entry point instead)
        self.assertIn("def _execute_work_delete", src)
        self.assertIn("def _execute_work_item", src)
        # The fence is in _handle_chat_process, not in chat_core itself
        from assistant_os.webhook_server import WebhookHandler
        handler_src = inspect.getsource(WebhookHandler._handle_chat_process)
        self.assertIn("governance_blocked", handler_src)

    def test_governance_mode_endpoint_in_do_post_routing_table(self):
        """/admin/governance/mode is routed in do_POST."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler.do_POST)
        self.assertIn("/admin/governance/mode", src)
        self.assertIn("_handle_governance_mode", src)

    def test_frozen_check_before_capability_in_governance_engine(self):
        """
        In governance_engine.evaluate_governance, the FROZEN check must come
        before capability.is_revoked — FROZEN dominates all other decisions.
        """
        import inspect
        from assistant_os.mso import governance_engine
        src = inspect.getsource(governance_engine.evaluate_governance)

        frozen_pos = src.find("FROZEN")
        revoked_pos = src.find("capability.is_revoked")
        self.assertLess(frozen_pos, revoked_pos,
            "FROZEN check must appear before capability.is_revoked in evaluate_governance")


if __name__ == "__main__":
    unittest.main()
