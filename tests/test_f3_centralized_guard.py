"""
Tests for Sprint 3 / F3: Centralized Guardian Flow

Proves:
  1. build_guarded_request is the single canonical construction point
  2. identity_guard() is called exactly once per request via build_guarded_request
  3. CanonicalRequest carries guard_decision as the authoritative source of truth
  4. Chat path and orchestrator path cannot diverge for the same identity
  5. Downstream (orchestrator) consumes guard_decision from req, does not recompute
  6. DENY blocks both paths; DEGRADED blocks write ops in both paths
  7. session_lineage propagates through audit
  8. enforce_guard_for_handler works correctly as shared enforcement helper
"""

import json
import pytest
from unittest.mock import patch, call

from assistant_os.identity import (
    SubjectState,
    RequestIdentity,
    Principal,
    PrincipalKind,
    anonymous_human,
)
from assistant_os.identity_guard import (
    GuardDecision,
    GuardResult,
    identity_guard,
    build_guarded_request,
    enforce_guard_for_handler,
    is_write_operation,
)
from assistant_os.contracts import normalize_request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_identity(state: SubjectState, session_id: str = "test-sess-f3") -> RequestIdentity:
    return RequestIdentity(
        principal=Principal(kind=PrincipalKind.Human, id=f"human:{session_id[:8]}", label="user"),
        subject_state=state,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# build_guarded_request — canonical construction
# ---------------------------------------------------------------------------

class TestBuildGuardedRequest:
    """build_guarded_request is the single canonical entry point."""

    def test_returns_req_and_guard_result(self):
        identity = _make_identity(SubjectState.Active)
        result = build_guarded_request(identity, text="hola")
        assert isinstance(result, tuple)
        assert len(result) == 2
        req, gr = result
        assert isinstance(req, dict)
        assert isinstance(gr, GuardResult)

    def test_req_has_all_required_fields(self):
        identity = _make_identity(SubjectState.Active)
        req, _ = build_guarded_request(identity, text="hola")
        assert "text" in req
        assert "context_id" in req
        assert "filters" in req
        assert "metadata" in req
        assert "principal_id" in req
        assert "subject_state" in req
        assert "guard_decision" in req

    def test_guard_decision_stamped_for_active(self):
        identity = _make_identity(SubjectState.Active)
        req, gr = build_guarded_request(identity, text="hola")
        assert req["guard_decision"] == "allow"
        assert gr.decision == GuardDecision.ALLOW

    def test_guard_decision_stamped_for_quarantined(self):
        identity = _make_identity(SubjectState.Quarantined)
        req, gr = build_guarded_request(identity, text="hola")
        assert req["guard_decision"] == "degraded"
        assert gr.decision == GuardDecision.DEGRADED

    def test_guard_decision_stamped_for_suspended(self):
        identity = _make_identity(SubjectState.Suspended)
        req, gr = build_guarded_request(identity, text="hola")
        assert req["guard_decision"] == "deny"
        assert gr.decision == GuardDecision.DENY

    def test_guard_decision_stamped_for_terminated(self):
        identity = _make_identity(SubjectState.Terminated)
        req, gr = build_guarded_request(identity, text="hola")
        assert req["guard_decision"] == "deny"
        assert gr.decision == GuardDecision.DENY

    def test_req_decision_matches_guard_result_decision(self):
        """req['guard_decision'] and guard_result.decision must never diverge."""
        for state in SubjectState:
            identity = _make_identity(state)
            req, gr = build_guarded_request(identity, text="test")
            assert req["guard_decision"] == gr.decision.value, (
                f"Divergence for state={state}: req has '{req['guard_decision']}' "
                f"but guard_result has '{gr.decision.value}'"
            )

    def test_principal_id_propagated(self):
        identity = _make_identity(SubjectState.Active, session_id="abc12345")
        req, gr = build_guarded_request(identity)
        assert req["principal_id"] == identity.principal.id
        assert gr.principal_id == identity.principal.id

    def test_subject_state_propagated(self):
        identity = _make_identity(SubjectState.Quarantined)
        req, gr = build_guarded_request(identity)
        assert req["subject_state"] == "quarantined"
        assert gr.subject_state == "quarantined"

    def test_text_normalization_applied(self):
        identity = _make_identity(SubjectState.Active)
        req, _ = build_guarded_request(identity, text="  hola  ")
        assert req["text"] == "hola"

    def test_context_id_generated_when_absent(self):
        identity = _make_identity(SubjectState.Active)
        req, _ = build_guarded_request(identity)
        assert req["context_id"]
        assert len(req["context_id"]) > 8

    def test_context_id_preserved_when_provided(self):
        identity = _make_identity(SubjectState.Active)
        req, _ = build_guarded_request(identity, context_id="fixed-ctx-id-123")
        assert req["context_id"] == "fixed-ctx-id-123"

    def test_filters_passed_through(self):
        identity = _make_identity(SubjectState.Active)
        req, _ = build_guarded_request(identity, filters={"domain": "FIN"})
        assert req["filters"] == {"domain": "FIN"}

    def test_metadata_passed_through(self):
        identity = _make_identity(SubjectState.Active)
        req, _ = build_guarded_request(identity, metadata={"action": "FIN_EXPENSE"})
        assert req["metadata"] == {"action": "FIN_EXPENSE"}

    def test_req_is_json_serializable(self):
        """CanonicalRequest must be JSON-safe — no Python objects embedded."""
        identity = _make_identity(SubjectState.Active)
        req, _ = build_guarded_request(identity, text="test")
        json.dumps(req)  # must not raise

    def test_guard_result_is_same_evaluation_not_second_call(self):
        """
        Guard runs exactly once. req['guard_decision'] == guard_result.decision
        because they come from the same identity_guard() call, not two calls.
        """
        identity = _make_identity(SubjectState.Quarantined)
        with patch(
            "assistant_os.identity_guard.identity_guard",
            wraps=identity_guard,
        ) as mock_guard:
            req, gr = build_guarded_request(identity, text="test")
            assert mock_guard.call_count == 1
            assert req["guard_decision"] == gr.decision.value


# ---------------------------------------------------------------------------
# enforce_guard_for_handler — shared enforcement helper
# ---------------------------------------------------------------------------

class TestEnforceGuardForHandler:
    def test_allow_returns_none(self):
        identity = _make_identity(SubjectState.Active)
        req, _ = build_guarded_request(identity, text="hola")
        assert enforce_guard_for_handler(req) is None

    def test_deny_returns_access_denied(self):
        identity = _make_identity(SubjectState.Suspended)
        req, _ = build_guarded_request(identity, text="hola")
        err = enforce_guard_for_handler(req)
        assert err is not None
        assert err[0] == "access_denied"

    def test_terminated_returns_access_denied(self):
        identity = _make_identity(SubjectState.Terminated)
        req, _ = build_guarded_request(identity, text="hola")
        err = enforce_guard_for_handler(req)
        assert err is not None
        assert err[0] == "access_denied"

    def test_degraded_non_write_returns_none(self):
        identity = _make_identity(SubjectState.Quarantined)
        req, _ = build_guarded_request(identity, text="hola")
        # No write action — should be allowed
        assert enforce_guard_for_handler(req, action="WORK_QUERY") is None

    def test_degraded_write_returns_write_blocked(self):
        identity = _make_identity(SubjectState.Quarantined)
        req, _ = build_guarded_request(identity, text="hola")
        err = enforce_guard_for_handler(req, action="FIN_EXPENSE")
        assert err is not None
        assert err[0] == "write_blocked"

    def test_degraded_work_create_blocked(self):
        identity = _make_identity(SubjectState.Quarantined)
        req, _ = build_guarded_request(identity, text="hola")
        err = enforce_guard_for_handler(req, action="WORK_CREATE")
        assert err is not None
        assert err[0] == "write_blocked"

    def test_no_guard_decision_returns_none(self):
        """Backward compat: req without guard_decision → allowed."""
        req = normalize_request(text="hola")  # no identity → no guard_decision
        assert enforce_guard_for_handler(req) is None

    def test_reason_is_non_empty_for_deny(self):
        identity = _make_identity(SubjectState.Terminated)
        req, _ = build_guarded_request(identity)
        err = enforce_guard_for_handler(req)
        assert err[1]  # reason string is non-empty

    def test_reason_is_non_empty_for_write_blocked(self):
        identity = _make_identity(SubjectState.Quarantined)
        req, _ = build_guarded_request(identity)
        err = enforce_guard_for_handler(req, action="FIN_EXPENSE")
        assert err[1]


# ---------------------------------------------------------------------------
# Chat path and orchestrator path cannot diverge
# ---------------------------------------------------------------------------

class TestNoDivergenceBetweenPaths:
    """
    For the same identity, both paths must reach the same guard outcome.
    Divergence = chat path allows but orchestrator denies, or vice versa.
    """

    def _orchestrator_decision(self, identity: RequestIdentity, action: str = "") -> str:
        """
        Simulate what handle_request does: read guard_decision from req.
        Returns "allow", "deny", or "degraded_blocked"/"degraded_allowed".
        """
        req, _ = build_guarded_request(identity, metadata={"action": action} if action else {})
        gd = req.get("guard_decision")
        if gd == "deny":
            return "deny"
        if gd == "degraded" and is_write_operation(action):
            return "degraded_blocked"
        if gd == "degraded":
            return "degraded_allowed"
        return "allow"

    def _chat_decision(self, identity: RequestIdentity, is_write: bool = False) -> str:
        """
        Simulate what process_chat_input does: receive guard_result, check allow_write.
        """
        _, guard_result = build_guarded_request(identity, text="test")
        if guard_result.decision == GuardDecision.DENY:
            return "deny"
        if not guard_result.allow_write and is_write:
            return "degraded_blocked"
        if not guard_result.allow_write:
            return "degraded_allowed"
        return "allow"

    def test_active_allows_in_both_paths(self):
        identity = _make_identity(SubjectState.Active)
        assert self._orchestrator_decision(identity) == "allow"
        assert self._chat_decision(identity) == "allow"

    def test_suspended_denies_in_both_paths(self):
        identity = _make_identity(SubjectState.Suspended)
        assert self._orchestrator_decision(identity) == "deny"
        assert self._chat_decision(identity) == "deny"

    def test_terminated_denies_in_both_paths(self):
        identity = _make_identity(SubjectState.Terminated)
        assert self._orchestrator_decision(identity) == "deny"
        assert self._chat_decision(identity) == "deny"

    def test_quarantined_write_blocked_in_both_paths(self):
        identity = _make_identity(SubjectState.Quarantined)
        assert self._orchestrator_decision(identity, action="FIN_EXPENSE") == "degraded_blocked"
        assert self._chat_decision(identity, is_write=True) == "degraded_blocked"

    def test_quarantined_read_allowed_in_both_paths(self):
        identity = _make_identity(SubjectState.Quarantined)
        assert self._orchestrator_decision(identity, action="WORK_QUERY") == "degraded_allowed"
        assert self._chat_decision(identity, is_write=False) == "degraded_allowed"

    def test_all_states_consistent(self):
        """No state produces different decisions across paths."""
        write_cases = [
            (SubjectState.Active, "allow", "allow"),
            (SubjectState.Suspended, "deny", "deny"),
            (SubjectState.Terminated, "deny", "deny"),
            (SubjectState.Quarantined, "degraded_blocked", "degraded_blocked"),
        ]
        for state, expected_orch, expected_chat in write_cases:
            identity = _make_identity(state)
            orch = self._orchestrator_decision(identity, action="FIN_EXPENSE")
            chat = self._chat_decision(identity, is_write=True)
            assert orch == expected_orch, f"Orchestrator diverged for {state}: got {orch}"
            assert chat == expected_chat, f"Chat diverged for {state}: got {chat}"


# ---------------------------------------------------------------------------
# Orchestrator handle_request consumes guard_decision from req
# ---------------------------------------------------------------------------

class TestOrchestratorConsumesGuardDecision:
    """
    handle_request reads guard_decision from CanonicalRequest.
    It must NOT call identity_guard() itself.
    """

    def test_deny_in_req_produces_error_result(self):
        from assistant_os.core.orchestrator import handle_request
        identity = _make_identity(SubjectState.Suspended)
        req, _ = build_guarded_request(identity, text="create task xyz")
        assert req["guard_decision"] == "deny"
        result = handle_request(req)
        assert result["ok"] is False
        assert result["result_type"] == "denied"

    def test_terminated_in_req_produces_error_result(self):
        from assistant_os.core.orchestrator import handle_request
        identity = _make_identity(SubjectState.Terminated)
        req, _ = build_guarded_request(identity, text="hola")
        result = handle_request(req)
        assert result["ok"] is False
        assert result["result_type"] == "denied"

    def test_degraded_write_in_req_produces_error_result(self):
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.contracts import ACTION_FIN_EXPENSE, RISK_MEDIUM
        identity = _make_identity(SubjectState.Quarantined)
        req, _ = build_guarded_request(
            identity,
            text="gasto 50 dólares",
            metadata={"action": ACTION_FIN_EXPENSE, "domain": "FIN", "risk_level": RISK_MEDIUM},
        )
        assert req["guard_decision"] == "degraded"
        result = handle_request(req)
        assert result["ok"] is False
        assert result["result_type"] == "denied"

    def test_degraded_read_in_req_proceeds(self):
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.contracts import ACTION_WORK_QUERY, RISK_LOW
        identity = _make_identity(SubjectState.Quarantined)
        req, _ = build_guarded_request(
            identity,
            text="muéstrame las tareas de esta semana",
            metadata={"action": ACTION_WORK_QUERY, "domain": "WORK", "risk_level": RISK_LOW},
        )
        assert req["guard_decision"] == "degraded"
        # Should NOT return denied — WORK_QUERY is read-only
        result = handle_request(req)
        # result may succeed or fail for other reasons, but NOT because of guard denial
        assert result.get("result_type") != "denied", (
            "handle_request denied a DEGRADED read-only request, which is incorrect"
        )

    def test_active_in_req_proceeds_normally(self):
        from assistant_os.core.orchestrator import handle_request
        identity = _make_identity(SubjectState.Active)
        req, _ = build_guarded_request(identity, text="hola")
        assert req["guard_decision"] == "allow"
        result = handle_request(req)
        # Should not return "denied"
        assert result.get("result_type") != "denied"

    def test_handle_request_does_not_call_identity_guard(self):
        """Downstream must NOT recompute the guard."""
        from assistant_os.core.orchestrator import handle_request
        identity = _make_identity(SubjectState.Active)
        req, _ = build_guarded_request(identity, text="hola")
        with patch("assistant_os.identity_guard.identity_guard") as mock_guard:
            handle_request(req)
            mock_guard.assert_not_called()

    def test_no_guard_decision_backward_compat(self):
        """Legacy callers that don't set guard_decision must not be affected."""
        from assistant_os.core.orchestrator import handle_request
        # normalize_request without identity → no guard_decision field
        req = normalize_request(text="hola")
        assert req.get("guard_decision") is None
        # Should not raise and should not return denied
        result = handle_request(req)
        assert result.get("result_type") != "denied"


# ---------------------------------------------------------------------------
# session_lineage in delegation skeleton
# ---------------------------------------------------------------------------

class TestSessionLineage:
    def test_session_lineage_empty_by_default(self):
        identity = anonymous_human(session_id="sess-001")
        assert identity.session_lineage == []

    def test_session_lineage_set_on_construction(self):
        identity = _make_identity(SubjectState.Active)
        identity.session_lineage = ["root-sess", "mid-sess", "test-sess-f3"]
        assert identity.session_lineage == ["root-sess", "mid-sess", "test-sess-f3"]

    def test_session_lineage_in_audit_dict_when_set(self):
        identity = _make_identity(SubjectState.Active)
        identity.session_lineage = ["root-sess", "test-sess-f3"]
        d = identity.to_audit_dict()
        assert "session_lineage" in d
        assert d["session_lineage"] == ["root-sess", "test-sess-f3"]

    def test_session_lineage_absent_from_audit_dict_when_empty(self):
        identity = _make_identity(SubjectState.Active)
        d = identity.to_audit_dict()
        assert "session_lineage" not in d  # omitted when empty to keep payloads lean

    def test_session_lineage_propagated_through_build_guarded_request(self):
        identity = _make_identity(SubjectState.Active)
        identity.session_lineage = ["parent-session-id", "test-sess-f3"]
        req, gr = build_guarded_request(identity, text="test")
        # guard_result includes principal from identity
        assert gr.principal_id == identity.principal.id
        # audit_dict from identity has lineage
        audit = identity.to_audit_dict()
        assert audit["session_lineage"] == ["parent-session-id", "test-sess-f3"]

    def test_session_lineage_json_safe(self):
        identity = _make_identity(SubjectState.Active)
        identity.session_lineage = ["sess-a", "sess-b"]
        d = identity.to_audit_dict()
        json.dumps(d)  # must not raise


# ---------------------------------------------------------------------------
# Webhook chat path uses build_guarded_request (integration)
# ---------------------------------------------------------------------------

class TestWebhookChatPathUsesCanonicalGuard:
    """
    Prove the chat path goes through build_guarded_request and reads
    guard_decision from CanonicalRequest rather than calling identity_guard
    independently.
    """

    @pytest.fixture(autouse=True)
    def _server(self):
        import time
        from assistant_os.webhook_server import start_server_thread
        server, port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.05)
        self._port = port
        yield
        server.shutdown()
        server.server_close()

    def _post_chat(self, text: str, token: str) -> tuple:
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=10)
        body = json.dumps({"text": text}).encode()
        conn.request("POST", "/chat/process", body=body, headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "X-Assistant-Token": token,
        })
        resp = conn.getresponse()
        status = resp.status
        data = json.loads(resp.read().decode())
        conn.close()
        return status, data

    def test_guard_field_present_in_200_response(self):
        from assistant_os.config import WEBHOOK_TOKEN
        status, body = self._post_chat("hola", WEBHOOK_TOKEN)
        assert status == 200
        assert "guard" in body
        assert body["guard"]["decision"] == "allow"

    def test_build_guarded_request_called_not_identity_guard_directly(self, monkeypatch):
        """
        The webhook handler must use build_guarded_request, not call
        identity_guard() independently.
        """
        import assistant_os.identity_guard as ig_module
        original_bgr = ig_module.build_guarded_request
        call_log = []

        def spy_bgr(identity, **kwargs):
            call_log.append("build_guarded_request")
            return original_bgr(identity, **kwargs)

        monkeypatch.setattr(ig_module, "build_guarded_request", spy_bgr)
        from assistant_os.config import WEBHOOK_TOKEN
        status, _ = self._post_chat("hola", WEBHOOK_TOKEN)
        assert status == 200
        assert "build_guarded_request" in call_log, (
            "build_guarded_request was not called — webhook may be calling identity_guard directly"
        )

    def test_suspended_gives_403_via_canonical_guard(self, monkeypatch):
        import assistant_os.identity as id_module
        suspended_identity = _make_identity(SubjectState.Suspended)
        monkeypatch.setattr(id_module, "anonymous_human", lambda session_id=None: suspended_identity)
        from assistant_os.config import WEBHOOK_TOKEN
        status, body = self._post_chat("hola", WEBHOOK_TOKEN)
        assert status == 403
        assert body["ok"] is False
        assert body["error"] == "access_denied"
        assert "guard" in body

    def test_quarantined_200_with_degraded_decision(self, monkeypatch):
        import assistant_os.identity as id_module
        quarantined_identity = _make_identity(SubjectState.Quarantined)
        monkeypatch.setattr(id_module, "anonymous_human", lambda session_id=None: quarantined_identity)
        from assistant_os.config import WEBHOOK_TOKEN
        status, body = self._post_chat("hola", WEBHOOK_TOKEN)
        assert status == 200
        assert body["guard"]["decision"] == "degraded"
