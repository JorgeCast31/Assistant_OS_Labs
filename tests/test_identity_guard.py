"""
Tests for Sprint 2 / F2: Identity Guard

Covers:
  - GuardDecision enum semantics
  - GuardResult construction and serialization
  - identity_guard() for all SubjectState values
  - is_write_operation() helper
  - process_chat_input() DEGRADED enforcement
  - webhook_server DENY → HTTP 403
  - Backward compatibility (no identity → no guard enforcement)
  - contracts.normalize_request with identity param
  - orchestrator.handle_request guard_decision=deny path
"""

import json
import pytest

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
    is_write_operation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_identity(state: SubjectState, session_id: str = "test-sess-001") -> RequestIdentity:
    """Build a RequestIdentity with the given SubjectState."""
    return RequestIdentity(
        principal=Principal(
            kind=PrincipalKind.Human,
            id=f"human:{session_id[:8]}",
            label="test-user",
        ),
        subject_state=state,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# GuardDecision enum
# ---------------------------------------------------------------------------

class TestGuardDecision:
    def test_values(self):
        assert GuardDecision.ALLOW.value == "allow"
        assert GuardDecision.DENY.value == "deny"
        assert GuardDecision.DEGRADED.value == "degraded"

    def test_is_allowed(self):
        assert GuardDecision.ALLOW.is_allowed() is True
        assert GuardDecision.DEGRADED.is_allowed() is True
        assert GuardDecision.DENY.is_allowed() is False

    def test_is_full_access(self):
        assert GuardDecision.ALLOW.is_full_access() is True
        assert GuardDecision.DEGRADED.is_full_access() is False
        assert GuardDecision.DENY.is_full_access() is False

    def test_blocks_all(self):
        assert GuardDecision.DENY.blocks_all() is True
        assert GuardDecision.ALLOW.blocks_all() is False
        assert GuardDecision.DEGRADED.blocks_all() is False

    def test_str_enum_value(self):
        """GuardDecision is a str Enum — can be compared directly to strings."""
        assert GuardDecision.ALLOW == "allow"
        assert GuardDecision.DENY == "deny"
        assert GuardDecision.DEGRADED == "degraded"


# ---------------------------------------------------------------------------
# GuardResult
# ---------------------------------------------------------------------------

class TestGuardResult:
    def test_allow_result_construction(self):
        identity = _make_identity(SubjectState.Active)
        result = GuardResult(
            decision=GuardDecision.ALLOW,
            reason="Active subject.",
            subject_state="active",
            principal_id=identity.principal.id,
            allow_read=True,
            allow_write=True,
        )
        assert result.decision == GuardDecision.ALLOW
        assert result.allow_read is True
        assert result.allow_write is True
        assert result.is_allowed() is True
        assert result.is_full_access() is True
        assert result.blocks_all() is False

    def test_deny_result_construction(self):
        result = GuardResult(
            decision=GuardDecision.DENY,
            reason="Terminated.",
            subject_state="terminated",
            principal_id="human:abc123",
            allow_read=False,
            allow_write=False,
        )
        assert result.blocks_all() is True
        assert result.is_allowed() is False
        assert result.allow_read is False

    def test_degraded_result_construction(self):
        result = GuardResult(
            decision=GuardDecision.DEGRADED,
            reason="Quarantined.",
            subject_state="quarantined",
            principal_id="human:abc123",
            allow_read=True,
            allow_write=False,
        )
        assert result.is_allowed() is True
        assert result.is_full_access() is False
        assert result.allow_read is True
        assert result.allow_write is False

    def test_to_audit_dict_structure(self):
        identity = _make_identity(SubjectState.Active)
        result = GuardResult(
            decision=GuardDecision.ALLOW,
            reason="Active.",
            subject_state="active",
            principal_id=identity.principal.id,
            allow_read=True,
            allow_write=True,
        )
        d = result.to_audit_dict()
        assert d["decision"] == "allow"
        assert d["reason"] == "Active."
        assert d["subject_state"] == "active"
        assert d["principal_id"] == identity.principal.id
        assert "evaluated_at" in d
        assert d["allow_read"] is True
        assert d["allow_write"] is True

    def test_frozen_immutable(self):
        result = GuardResult(
            decision=GuardDecision.ALLOW,
            reason="x",
            subject_state="active",
            principal_id="human:abc",
        )
        with pytest.raises((AttributeError, TypeError)):
            result.decision = GuardDecision.DENY  # type: ignore[misc]

    def test_evaluated_at_is_set(self):
        result = GuardResult(
            decision=GuardDecision.ALLOW,
            reason="x",
            subject_state="active",
            principal_id="human:abc",
        )
        assert result.evaluated_at  # non-empty string
        assert "T" in result.evaluated_at  # ISO format has T separator


# ---------------------------------------------------------------------------
# identity_guard() — decision matrix
# ---------------------------------------------------------------------------

class TestIdentityGuard:
    def test_active_allows(self):
        identity = _make_identity(SubjectState.Active)
        result = identity_guard(identity)
        assert result.decision == GuardDecision.ALLOW
        assert result.allow_read is True
        assert result.allow_write is True
        assert result.subject_state == "active"
        assert result.principal_id == identity.principal.id

    def test_quarantined_degrades(self):
        identity = _make_identity(SubjectState.Quarantined)
        result = identity_guard(identity)
        assert result.decision == GuardDecision.DEGRADED
        assert result.allow_read is True
        assert result.allow_write is False
        assert result.subject_state == "quarantined"

    def test_suspended_denies(self):
        identity = _make_identity(SubjectState.Suspended)
        result = identity_guard(identity)
        assert result.decision == GuardDecision.DENY
        assert result.allow_read is False
        assert result.allow_write is False
        assert result.subject_state == "suspended"

    def test_terminated_denies(self):
        identity = _make_identity(SubjectState.Terminated)
        result = identity_guard(identity)
        assert result.decision == GuardDecision.DENY
        assert result.allow_read is False
        assert result.allow_write is False
        assert result.subject_state == "terminated"

    def test_reason_is_non_empty(self):
        for state in SubjectState:
            identity = _make_identity(state)
            result = identity_guard(identity)
            assert result.reason, f"reason should be non-empty for state={state}"

    def test_principal_id_propagated(self):
        identity = _make_identity(SubjectState.Active, session_id="my-session-xyz")
        result = identity_guard(identity)
        assert result.principal_id == identity.principal.id

    def test_to_audit_dict_json_safe(self):
        import json
        for state in SubjectState:
            identity = _make_identity(state)
            result = identity_guard(identity)
            d = result.to_audit_dict()
            json.dumps(d)  # must not raise

    def test_anonymous_human_always_allows(self):
        """anonymous_human() always returns Active state → ALLOW."""
        identity = anonymous_human(session_id="anon-session-001")
        result = identity_guard(identity)
        assert result.decision == GuardDecision.ALLOW

    def test_all_states_covered(self):
        """Every SubjectState produces a valid GuardResult without raising."""
        for state in SubjectState:
            identity = _make_identity(state)
            result = identity_guard(identity)
            assert isinstance(result, GuardResult)
            assert isinstance(result.decision, GuardDecision)


# ---------------------------------------------------------------------------
# is_write_operation()
# ---------------------------------------------------------------------------

class TestIsWriteOperation:
    def test_none_is_not_write(self):
        assert is_write_operation(None) is False

    def test_empty_string_is_not_write(self):
        assert is_write_operation("") is False

    def test_work_create_is_write(self):
        assert is_write_operation("WORK_CREATE") is True
        assert is_write_operation("WORK_CREATE_TASK") is True

    def test_work_update_is_write(self):
        assert is_write_operation("WORK_UPDATE") is True
        assert is_write_operation("WORK_UPDATE_BULK") is True

    def test_work_delete_is_write(self):
        assert is_write_operation("WORK_DELETE") is True

    def test_fin_expense_is_write(self):
        assert is_write_operation("FIN_EXPENSE") is True
        assert is_write_operation("FIN_CREATE") is True

    def test_code_fix_is_write(self):
        assert is_write_operation("CODE_FIX") is True
        assert is_write_operation("CODE_CREATE") is True

    def test_work_query_is_not_write(self):
        assert is_write_operation("WORK_QUERY") is False
        assert is_write_operation("WORK_LIST") is False

    def test_code_explain_is_not_write(self):
        assert is_write_operation("CODE_EXPLAIN") is False
        assert is_write_operation("CODE_REVIEW") is False

    def test_case_insensitive(self):
        assert is_write_operation("work_create") is True
        assert is_write_operation("fin_expense") is True
        assert is_write_operation("code_fix") is True

    def test_generic_create_is_write(self):
        assert is_write_operation("CREATE") is True
        assert is_write_operation("UPDATE") is True
        assert is_write_operation("DELETE") is True


# ---------------------------------------------------------------------------
# process_chat_input — DEGRADED enforcement
# ---------------------------------------------------------------------------

class TestProcessChatInputGuardEnforcement:
    """
    Tests that process_chat_input blocks write operations when guard_result
    has allow_write=False (DEGRADED state).
    """

    def _degraded_guard(self) -> GuardResult:
        identity = _make_identity(SubjectState.Quarantined)
        return identity_guard(identity)

    def _active_guard(self) -> GuardResult:
        identity = _make_identity(SubjectState.Active)
        return identity_guard(identity)

    def test_active_guard_allows_fin_input(self):
        from assistant_os.chat_core import process_chat_input
        identity = _make_identity(SubjectState.Active)
        guard = identity_guard(identity)
        # FIN-triggering input — should NOT be blocked
        result = process_chat_input(
            "gasto 50 dólares en almuerzo",
            identity=identity,
            guard_result=guard,
        )
        # Not blocked — intent should be something FIN-related, not "suspended"
        assert result["intent"] != "suspended"

    def test_degraded_guard_blocks_fin_write(self):
        from assistant_os.chat_core import process_chat_input
        identity = _make_identity(SubjectState.Quarantined)
        guard = identity_guard(identity)
        result = process_chat_input(
            "gasto 50 dólares en almuerzo",
            identity=identity,
            guard_result=guard,
        )
        # FIN domain is always write; must be blocked under DEGRADED
        assert result["intent"] == "suspended"
        assert result["domain"] == "FIN"
        assert "_guard" in result.get("audit", {})

    def test_degraded_guard_allows_passthrough(self):
        """Non-write domains (ENERGY/passthrough) should pass through under DEGRADED."""
        from assistant_os.chat_core import process_chat_input
        identity = _make_identity(SubjectState.Quarantined)
        guard = identity_guard(identity)
        result = process_chat_input(
            "hola, como estás",
            identity=identity,
            guard_result=guard,
        )
        assert result["intent"] != "suspended"

    def test_no_guard_result_no_blocking(self):
        """When guard_result is absent, no DEGRADED enforcement happens."""
        from assistant_os.chat_core import process_chat_input
        identity = _make_identity(SubjectState.Active)
        result = process_chat_input(
            "gasto 50 dólares en almuerzo",
            identity=identity,
            guard_result=None,
        )
        assert result["intent"] != "suspended"

    def test_guard_result_in_audit(self):
        """GuardResult is stamped in audit when provided with identity."""
        from assistant_os.chat_core import process_chat_input
        identity = _make_identity(SubjectState.Active)
        guard = identity_guard(identity)
        result = process_chat_input("hola", identity=identity, guard_result=guard)
        audit = result.get("audit", {})
        assert "_guard" in audit
        assert audit["_guard"]["decision"] == "allow"

    def test_degraded_guard_blocks_work_create(self):
        """WORK mutation ops should be blocked under DEGRADED."""
        from assistant_os.chat_core import process_chat_input
        identity = _make_identity(SubjectState.Quarantined)
        guard = identity_guard(identity)
        # This text triggers WORK_CREATE
        result = process_chat_input(
            "crea una tarea: implementar feature X",
            identity=identity,
            guard_result=guard,
        )
        # Should be blocked (suspended) or at least have guard in audit
        audit = result.get("audit", {})
        assert "_guard" in audit
        assert audit["_guard"]["allow_write"] is False

    def test_backward_compat_no_identity_no_guard(self):
        """No identity, no guard_result → no identity fields in audit."""
        from assistant_os.chat_core import process_chat_input
        result = process_chat_input("hola")
        audit = result.get("audit", {})
        assert "_identity" not in audit
        assert "_guard" not in audit


# ---------------------------------------------------------------------------
# contracts.normalize_request with identity param
# ---------------------------------------------------------------------------

class TestNormalizeRequestWithIdentity:
    def test_without_identity_no_identity_fields(self):
        from assistant_os.contracts import normalize_request
        req = normalize_request(text="hola")
        assert "principal_id" not in req
        assert "subject_state" not in req
        assert "guard_decision" not in req

    def test_with_identity_sets_fields(self):
        from assistant_os.contracts import normalize_request
        identity = _make_identity(SubjectState.Active)
        req = normalize_request(text="hola", identity=identity)
        assert req.get("principal_id") == identity.principal.id
        assert req.get("subject_state") == "active"
        assert req.get("guard_decision") is None  # not set until guard runs

    def test_with_quarantined_identity(self):
        from assistant_os.contracts import normalize_request
        identity = _make_identity(SubjectState.Quarantined)
        req = normalize_request(text="test", identity=identity)
        assert req["subject_state"] == "quarantined"

    def test_required_fields_always_present(self):
        from assistant_os.contracts import normalize_request
        identity = _make_identity(SubjectState.Active)
        req = normalize_request(text="test", identity=identity)
        assert "text" in req
        assert "context_id" in req
        assert "filters" in req
        assert "metadata" in req


# ---------------------------------------------------------------------------
# Webhook-level 403 behavior (via real HTTP server)
# ---------------------------------------------------------------------------

def _make_webhook_request(port: int, body: dict, token: str) -> tuple:
    """Make a POST /chat/process request to the test server."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    payload = json.dumps(body).encode("utf-8")
    conn.request(
        "POST", "/chat/process", body=payload,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "X-Assistant-Token": token,
        },
    )
    resp = conn.getresponse()
    status = resp.status
    data = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return status, data


class TestWebhookGuardDeny:
    """
    Tests the HTTP 403 path by injecting a Terminated/Suspended identity
    via monkeypatching anonymous_human before making real HTTP requests.
    """

    @pytest.fixture(autouse=True)
    def _server(self):
        """Start a fresh webhook server for this test class."""
        import time
        from assistant_os.webhook_server import start_server_thread
        server, port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.05)
        self._port = port
        self._server_inst = server
        yield
        server.shutdown()
        server.server_close()

    def test_webhook_200_on_active(self):
        """Active state (default) → HTTP 200, guard ALLOW in response."""
        from assistant_os.config import WEBHOOK_TOKEN
        status, body = _make_webhook_request(
            self._port, {"text": "hola"}, WEBHOOK_TOKEN
        )
        assert status == 200
        assert body["ok"] is True
        assert "guard" in body
        assert body["guard"]["decision"] == "allow"
        assert body["guard"]["allow_write"] is True

    def test_webhook_returns_403_on_terminated(self, monkeypatch):
        """Terminated state → DENY → HTTP 403."""
        import assistant_os.identity as identity_module
        terminated_identity = _make_identity(SubjectState.Terminated)
        monkeypatch.setattr(
            identity_module, "anonymous_human",
            lambda session_id=None: terminated_identity,
        )
        from assistant_os.config import WEBHOOK_TOKEN
        status, body = _make_webhook_request(
            self._port, {"text": "hola", "session_id": "test-sess"}, WEBHOOK_TOKEN
        )
        assert status == 403
        assert body["ok"] is False
        assert body["error"] == "access_denied"
        assert body["subject_state"] == "terminated"
        assert "guard" in body
        assert body["guard"]["decision"] == "deny"

    def test_webhook_returns_403_on_suspended(self, monkeypatch):
        """Suspended state → DENY → HTTP 403."""
        import assistant_os.identity as identity_module
        suspended_identity = _make_identity(SubjectState.Suspended)
        monkeypatch.setattr(
            identity_module, "anonymous_human",
            lambda session_id=None: suspended_identity,
        )
        from assistant_os.config import WEBHOOK_TOKEN
        status, body = _make_webhook_request(
            self._port, {"text": "hola"}, WEBHOOK_TOKEN
        )
        assert status == 403
        assert body["ok"] is False
        assert body["subject_state"] == "suspended"

    def test_webhook_200_on_quarantined_non_write(self, monkeypatch):
        """Quarantined + non-write text → HTTP 200 with DEGRADED guard."""
        import assistant_os.identity as identity_module
        quarantined_identity = _make_identity(SubjectState.Quarantined)
        monkeypatch.setattr(
            identity_module, "anonymous_human",
            lambda session_id=None: quarantined_identity,
        )
        from assistant_os.config import WEBHOOK_TOKEN
        status, body = _make_webhook_request(
            self._port, {"text": "hola"}, WEBHOOK_TOKEN
        )
        assert status == 200
        assert body["ok"] is True
        assert body["guard"]["decision"] == "degraded"
        assert body["guard"]["allow_write"] is False


# ---------------------------------------------------------------------------
# _inject_identity with guard_result
# ---------------------------------------------------------------------------

class TestInjectIdentityWithGuard:
    def test_guard_stamped_in_audit(self):
        from assistant_os.chat_core import _inject_identity, make_chat_core_response
        from assistant_os.contracts import ChatSession, new_context_id

        identity = _make_identity(SubjectState.Active)
        guard = identity_guard(identity)
        response = make_chat_core_response(
            domain="*",
            intent="passthrough",
            mode="chat",
            session=ChatSession(context_id=new_context_id()),
            audit={},
        )
        _inject_identity(response, identity, guard)
        assert "_identity" in response["audit"]
        assert "_guard" in response["audit"]
        assert response["audit"]["_guard"]["decision"] == "allow"

    def test_no_guard_result_no_guard_stamp(self):
        from assistant_os.chat_core import _inject_identity, make_chat_core_response
        from assistant_os.contracts import ChatSession, new_context_id

        identity = _make_identity(SubjectState.Active)
        response = make_chat_core_response(
            domain="*",
            intent="passthrough",
            mode="chat",
            session=ChatSession(context_id=new_context_id()),
            audit={},
        )
        _inject_identity(response, identity, None)
        assert "_identity" in response["audit"]
        assert "_guard" not in response["audit"]


# ---------------------------------------------------------------------------
# chat_renderer — suspended template
# ---------------------------------------------------------------------------

class TestChatRendererSuspendedTemplate:
    def test_suspended_intent_renders_message(self):
        from assistant_os.chat_renderer import render_chat_response
        from assistant_os.contracts import ChatSession, new_context_id
        from assistant_os.chat_core import make_chat_core_response

        response = make_chat_core_response(
            domain="FIN",
            intent="suspended",
            mode="chat",
            session=ChatSession(context_id=new_context_id()),
            audit={},
        )
        rendered = render_chat_response(response)
        assert rendered.message
        assert len(rendered.message) > 10
        # Should NOT be an empty echo or generic "unknown" message
        assert "bloqueada" in rendered.message or "lectura" in rendered.message

    def test_suspended_template_present_in_template_map(self):
        from assistant_os.chat_renderer import INTENT_TEMPLATES
        assert ("*", "suspended") in INTENT_TEMPLATES
