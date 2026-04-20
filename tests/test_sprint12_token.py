"""
Sprint 12 — Capability Token Tests.

Validates the process-local capability token layer:
  PolicyDecision(APPROVED) → issue_token → verify_token → consume_token → execute

Coverage
--------
Unit tests — token_models.py:
  - TokenStatus, OperationBinding, CapabilityToken construction and immutability

Unit tests — token_issuer.py:
  - issue_token: fields, registry, uniqueness, TTL

Unit tests — token_verifier.py:
  - verify_token: happy path, expired, consumed, binding mismatch, never-issued
  - consume_token: single-use enforcement
  - Ordering: all three check steps

Integration tests — orchestrator.handle_request():
  - Token issued only on APPROVED policy decision
  - Denied policy path never issues a usable token
  - Execution paths (AUTO) verify + consume before dispatch
  - Non-execution paths (CONFIRM, PLAN_GENERATED) do not consume the token
  - Confirmed plan path (Phase 3C) requires and consumes its own token
"""

from __future__ import annotations

import time
import pytest


# ===========================================================================
# Helpers
# ===========================================================================

def _make_binding(
    principal_id="user-1",
    subject_state="active",
    action_type="read",
    capability=None,
    operation_key="ctx-test",
):
    from assistant_os.capabilities.token_models import OperationBinding
    return OperationBinding(
        principal_id=principal_id,
        subject_state=subject_state,
        action_type=action_type,
        capability=capability,
        operation_key=operation_key,
    )


def _issue(binding=None, ttl_seconds=300.0):
    from assistant_os.capabilities.token_issuer import issue_token
    if binding is None:
        binding = _make_binding()
    return issue_token(binding, ttl_seconds=ttl_seconds)


def _reset():
    from assistant_os.capabilities.token_issuer import _reset_registry
    _reset_registry()


def _verify(token, binding=None):
    from assistant_os.capabilities.token_verifier import verify_token
    if binding is None:
        binding = _make_binding()
    return verify_token(token, binding)


def _consume(token):
    from assistant_os.capabilities.token_verifier import consume_token
    consume_token(token)


@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure a clean token registry before each test."""
    _reset()
    yield
    _reset()


# ===========================================================================
# Unit tests — token_models
# ===========================================================================

class TestTokenStatus:
    def test_active_value(self):
        from assistant_os.capabilities.token_models import TokenStatus
        assert TokenStatus.ACTIVE.value == "active"

    def test_consumed_value(self):
        from assistant_os.capabilities.token_models import TokenStatus
        assert TokenStatus.CONSUMED.value == "consumed"

    def test_expired_value(self):
        from assistant_os.capabilities.token_models import TokenStatus
        assert TokenStatus.EXPIRED.value == "expired"

    def test_is_str_enum(self):
        from assistant_os.capabilities.token_models import TokenStatus
        assert isinstance(TokenStatus.ACTIVE, str)


class TestOperationBinding:
    def test_construction(self):
        b = _make_binding(
            principal_id="user-x",
            subject_state="active",
            action_type="write",
            capability="write_files",
            operation_key="ctx-abc",
        )
        assert b.principal_id == "user-x"
        assert b.subject_state == "active"
        assert b.action_type == "write"
        assert b.capability == "write_files"
        assert b.operation_key == "ctx-abc"

    def test_none_capability_allowed(self):
        b = _make_binding(capability=None)
        assert b.capability is None

    def test_is_frozen(self):
        b = _make_binding()
        with pytest.raises((AttributeError, TypeError)):
            b.principal_id = "hacked"  # type: ignore[misc]


class TestCapabilityToken:
    def test_construction_fields(self):
        b = _make_binding()
        token = _issue(b)
        assert token.principal_id == b.principal_id
        assert token.subject_state == b.subject_state
        assert token.action_type == b.action_type
        assert token.capability == b.capability
        assert token.operation_key == b.operation_key

    def test_status_is_active_at_construction(self):
        from assistant_os.capabilities.token_models import TokenStatus
        token = _issue()
        assert token.status == TokenStatus.ACTIVE

    def test_has_valid_uuid_token_id(self):
        import uuid
        token = _issue()
        # Should not raise
        parsed = uuid.UUID(token.token_id)
        assert str(parsed) == token.token_id

    def test_expires_at_is_after_issued_at(self):
        token = _issue(ttl_seconds=300.0)
        assert token.expires_at > token.issued_at
        assert token.expires_at - token.issued_at == pytest.approx(300.0, abs=0.1)

    def test_is_frozen(self):
        token = _issue()
        with pytest.raises((AttributeError, TypeError)):
            token.status = "consumed"  # type: ignore[misc]


# ===========================================================================
# Unit tests — token_issuer
# ===========================================================================

class TestIssueToken:
    def test_issued_token_is_in_registry(self):
        from assistant_os.capabilities.token_issuer import _token_registry
        token = _issue()
        assert token.token_id in _token_registry

    def test_issued_token_registry_status_is_active(self):
        from assistant_os.capabilities.token_issuer import _token_registry
        token = _issue()
        assert _token_registry[token.token_id] == "active"

    def test_two_tokens_have_distinct_ids(self):
        b = _make_binding()
        t1 = _issue(b)
        t2 = _issue(b)
        assert t1.token_id != t2.token_id

    def test_two_tokens_for_same_binding_both_registered(self):
        from assistant_os.capabilities.token_issuer import _token_registry
        b = _make_binding()
        t1 = _issue(b)
        t2 = _issue(b)
        assert t1.token_id in _token_registry
        assert t2.token_id in _token_registry

    def test_ttl_controls_expiry_window(self):
        token = _issue(ttl_seconds=60.0)
        assert token.expires_at - token.issued_at == pytest.approx(60.0, abs=0.1)

    def test_reset_registry_clears_all_tokens(self):
        from assistant_os.capabilities.token_issuer import _token_registry
        _issue()
        _issue()
        _reset()
        assert len(_token_registry) == 0


# ===========================================================================
# Unit tests — token_verifier: verify_token
# ===========================================================================

class TestVerifyToken:
    """verify_token: happy path and all failure modes."""

    def test_fresh_token_verifies(self):
        b = _make_binding()
        token = _issue(b)
        assert _verify(token, b) is True

    def test_never_issued_token_fails(self):
        """A CapabilityToken not in the registry (constructed manually) → False."""
        from assistant_os.capabilities.token_models import (
            CapabilityToken, OperationBinding, TokenStatus,
        )
        now = time.monotonic()
        fake_binding = _make_binding()
        fake_token = CapabilityToken(
            token_id="00000000-0000-0000-0000-000000000000",
            principal_id=fake_binding.principal_id,
            subject_state=fake_binding.subject_state,
            action_type=fake_binding.action_type,
            capability=fake_binding.capability,
            operation_key=fake_binding.operation_key,
            issued_at=now,
            expires_at=now + 300,
            status=TokenStatus.ACTIVE,
        )
        # Not in registry → denied
        assert _verify(fake_token, fake_binding) is False

    def test_expired_token_fails(self):
        """Token with TTL=0 expires immediately."""
        b = _make_binding()
        token = _issue(b, ttl_seconds=-1.0)  # already expired
        assert _verify(token, b) is False

    def test_expired_token_registry_is_updated_to_expired(self):
        from assistant_os.capabilities.token_issuer import _token_registry
        b = _make_binding()
        token = _issue(b, ttl_seconds=-1.0)
        _verify(token, b)  # triggers expiry detection
        assert _token_registry[token.token_id] == "expired"

    def test_consumed_token_fails(self):
        b = _make_binding()
        token = _issue(b)
        _consume(token)
        assert _verify(token, b) is False

    def test_principal_id_mismatch_fails(self):
        b_issue = _make_binding(principal_id="user-a")
        b_verify = _make_binding(principal_id="user-b")
        token = _issue(b_issue)
        assert _verify(token, b_verify) is False

    def test_subject_state_mismatch_fails(self):
        b_issue = _make_binding(subject_state="active")
        b_verify = _make_binding(subject_state="quarantined")
        token = _issue(b_issue)
        assert _verify(token, b_verify) is False

    def test_action_type_mismatch_fails(self):
        b_issue = _make_binding(action_type="read")
        b_verify = _make_binding(action_type="write")
        token = _issue(b_issue)
        assert _verify(token, b_verify) is False

    def test_capability_mismatch_fails(self):
        b_issue = _make_binding(capability="execute_code")
        b_verify = _make_binding(capability="write_files")
        token = _issue(b_issue)
        assert _verify(token, b_verify) is False

    def test_capability_none_vs_value_fails(self):
        b_issue = _make_binding(capability=None)
        b_verify = _make_binding(capability="write_files")
        token = _issue(b_issue)
        assert _verify(token, b_verify) is False

    def test_operation_key_mismatch_fails(self):
        b_issue = _make_binding(operation_key="ctx-original")
        b_verify = _make_binding(operation_key="ctx-different")
        token = _issue(b_issue)
        assert _verify(token, b_verify) is False

    def test_verify_does_not_consume(self):
        """verify_token alone does NOT consume the token."""
        b = _make_binding()
        token = _issue(b)
        assert _verify(token, b) is True
        assert _verify(token, b) is True  # still valid — not consumed

    def test_verify_check_order_step1_before_step2(self):
        """Consumed + expired: step 1 (registry) fires before step 2 (expiry)."""
        from assistant_os.capabilities.token_issuer import _token_registry
        b = _make_binding()
        token = _issue(b, ttl_seconds=-1.0)  # expired
        _consume(token)  # also consumed
        # Step 1 sees CONSUMED → False; never reaches step 2
        result = _verify(token, b)
        assert result is False
        # Registry should still be CONSUMED, not EXPIRED (step 1 returned early)
        assert _token_registry[token.token_id] == "consumed"


# ===========================================================================
# Unit tests — token_verifier: consume_token
# ===========================================================================

class TestConsumeToken:
    """consume_token: single-use enforcement."""

    def test_consume_marks_registry_as_consumed(self):
        from assistant_os.capabilities.token_issuer import _token_registry
        token = _issue()
        _consume(token)
        assert _token_registry[token.token_id] == "consumed"

    def test_consume_prevents_reverification(self):
        b = _make_binding()
        token = _issue(b)
        assert _verify(token, b) is True
        _consume(token)
        assert _verify(token, b) is False

    def test_double_consume_is_idempotent(self):
        """Consuming twice is safe (no exception, still consumed)."""
        from assistant_os.capabilities.token_issuer import _token_registry
        token = _issue()
        _consume(token)
        _consume(token)
        assert _token_registry[token.token_id] == "consumed"

    def test_consume_does_not_affect_other_tokens(self):
        b = _make_binding()
        t1 = _issue(b)
        t2 = _issue(b)
        _consume(t1)
        assert _verify(t2, b) is True  # t2 unaffected


# ===========================================================================
# Unit tests — single-use enforcement (issue → verify → consume → verify)
# ===========================================================================

class TestSingleUse:
    def test_issued_verified_consumed_reused_is_denied(self):
        """Full lifecycle: ACTIVE → verified → CONSUMED → denied."""
        b = _make_binding()
        token = _issue(b)
        assert _verify(token, b) is True
        _consume(token)
        assert _verify(token, b) is False

    def test_two_distinct_tokens_are_independent(self):
        """Consuming one token does not affect the other."""
        b = _make_binding()
        t1 = _issue(b)
        t2 = _issue(b)
        assert _verify(t1, b) is True
        assert _verify(t2, b) is True
        _consume(t1)
        assert _verify(t1, b) is False
        assert _verify(t2, b) is True


# ===========================================================================
# Integration tests — orchestrator.handle_request() with token layer
# ===========================================================================

def _req(subject_state="active", guard_decision="allow", action_type="read", **extra):
    """Minimal CanonicalRequest that passes policy."""
    return {
        "text": "test request",
        "context_id": f"ctx-s12-{subject_state}-{action_type}",
        "filters": {},
        "metadata": {},
        "principal_id": "user-s12",
        "subject_state": subject_state,
        "guard_decision": guard_decision,
        "action_type": action_type,
        **extra,
    }


class TestTokenIssuedOnlyForApproved:
    """Token issuance correlates with PolicyDecision.APPROVED."""

    def test_approved_request_issues_token(self):
        """
        An approved request (active + allow + read) must result in a token being
        registered — we detect this by checking that a new entry appears in the registry.
        """
        from assistant_os.capabilities.token_issuer import _token_registry
        _reset()
        before_count = len(_token_registry)
        from assistant_os.core.orchestrator import handle_request
        handle_request(_req("active", "allow", "read"))
        # At least one new token should be in the registry
        assert len(_token_registry) > before_count

    def test_denied_request_does_not_add_usable_token_to_registry(self):
        """
        A denied request (guard_decision='deny') hits the policy gate and returns
        before the token issuance block.  No valid ACTIVE token should be added.
        """
        from assistant_os.capabilities.token_issuer import _token_registry
        _reset()
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("active", "deny", "read"))
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        # No ACTIVE token should have been registered (denied before issuance)
        assert all(v != "active" for v in _token_registry.values())


class TestTokenConsumedOnExecution:
    """Tokens are consumed exactly once on execution paths (AUTO mode)."""

    def test_auto_execution_consumes_token(self):
        """
        When a pipeline fires (AUTO mode), the token is consumed.
        We detect this by checking that no ACTIVE tokens remain after the call.
        """
        from assistant_os.capabilities.token_issuer import _token_registry
        from assistant_os.capabilities.token_models import TokenStatus
        _reset()
        from assistant_os.core.orchestrator import handle_request
        # Use an action that goes AUTO (cognitive execution path)
        req = _req("active", "allow", "read")
        req["metadata"] = {"action": "BASIC_COGNITIVE_EXECUTION"}
        handle_request(req)
        # All tokens issued during this call should be CONSUMED (or EXPIRED)
        active_tokens = [t for t, s in _token_registry.items() if s == TokenStatus.ACTIVE.value]
        assert len(active_tokens) == 0

    def test_non_execution_plan_confirmation_path_token_not_consumed(self):
        """
        When execution_mode returns CONFIRM (plan_confirmation_required),
        the token is NOT consumed because no pipeline fires.
        """
        from assistant_os.capabilities.token_issuer import _token_registry
        from assistant_os.capabilities.token_models import TokenStatus
        _reset()
        from assistant_os.core.orchestrator import handle_request
        # A structured request that triggers CONFIRM (requires_confirmation=True)
        req = _req("active", "allow", "write")
        req["metadata"] = {
            "action": "FIN_EXPENSE",
            "requires_confirmation": True,
        }
        result = handle_request(req)
        # Should be plan_confirmation_required — no execution
        assert result["result_type"] == "plan_confirmation_required"
        # Token issued but NOT consumed (non-execution path)
        # (May be ACTIVE because token was never verified+consumed)
        active_tokens = [t for t, s in _token_registry.items() if s == TokenStatus.ACTIVE.value]
        assert len(active_tokens) >= 1  # token is still active (not consumed)


class TestDeniedPolicyNeverIssuesToken:
    """Policy denials must not issue tokens (token issuance is post-APPROVED only)."""

    def test_suspended_denied_no_active_token(self):
        from assistant_os.capabilities.token_issuer import _token_registry
        from assistant_os.capabilities.token_models import TokenStatus
        _reset()
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("suspended", "allow", "read"))
        assert result["ok"] is False
        active = [v for v in _token_registry.values() if v == TokenStatus.ACTIVE.value]
        assert len(active) == 0

    def test_guard_deny_no_active_token(self):
        from assistant_os.capabilities.token_issuer import _token_registry
        from assistant_os.capabilities.token_models import TokenStatus
        _reset()
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("active", "deny", "read"))
        assert result["ok"] is False
        active = [v for v in _token_registry.values() if v == TokenStatus.ACTIVE.value]
        assert len(active) == 0

    def test_capability_denied_no_active_token(self):
        from assistant_os.capabilities.token_issuer import _token_registry
        from assistant_os.capabilities.token_models import TokenStatus
        _reset()
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("quarantined", "allow", "execute"))
        assert result["ok"] is False
        assert result["error"]["type"] == "capability_denied"
        active = [v for v in _token_registry.values() if v == TokenStatus.ACTIVE.value]
        assert len(active) == 0


class TestConfirmedPlanRequiresToken:
    """The confirm path (Phase 3C) also verifies+consumes a token."""

    def test_confirm_path_registers_and_consumes_token(self):
        """
        A confirm request also passes through policy → issues token → verifies
        before _execute_confirmed_plan.  The token is consumed on the confirm call.

        We test this indirectly: after a confirm call (even one that fails with
        PlanNotFound), the token for that call should be consumed.
        """
        from assistant_os.capabilities.token_issuer import _token_registry
        from assistant_os.capabilities.token_models import TokenStatus
        _reset()
        from assistant_os.core.orchestrator import handle_request
        req = _req("active", "allow", "read")
        req["metadata"] = {"confirm_plan_id": "nonexistent-plan-id-xyz"}
        result = handle_request(req)
        # Plan not found → confirm error, but token was still issued + consumed
        # (the gate passed, pipeline failed because plan doesn't exist)
        assert result["result_type"] == "confirm_error"
        # Token should be consumed (not ACTIVE) because confirm path executed
        active = [v for v in _token_registry.values() if v == TokenStatus.ACTIVE.value]
        assert len(active) == 0


class TestTokenValidation:
    """verify_token behavior seen from the orchestrator's perspective."""

    def test_tampered_operation_key_would_fail(self):
        """
        Directly verify that if operation_key doesn't match the token,
        verification fails — proving the orchestrator's binding is tied to context_id.
        """
        from assistant_os.capabilities.token_models import OperationBinding
        from assistant_os.capabilities.token_issuer import issue_token
        from assistant_os.capabilities.token_verifier import verify_token

        correct_binding = _make_binding(operation_key="ctx-real")
        token = issue_token(correct_binding)

        tampered_binding = _make_binding(operation_key="ctx-attacker")
        assert verify_token(token, tampered_binding) is False
        assert verify_token(token, correct_binding) is True

    def test_mismatched_principal_would_fail(self):
        """Tokens are bound to principal_id — another principal cannot use them."""
        from assistant_os.capabilities.token_models import OperationBinding
        from assistant_os.capabilities.token_issuer import issue_token
        from assistant_os.capabilities.token_verifier import verify_token

        alice = _make_binding(principal_id="alice")
        bob_claim = _make_binding(principal_id="bob")
        token = issue_token(alice)
        assert verify_token(token, bob_claim) is False

    def test_reused_single_use_token_fails_second_verify(self):
        """Single-use: after verify+consume, the same token cannot be re-verified."""
        from assistant_os.capabilities.token_issuer import issue_token
        from assistant_os.capabilities.token_verifier import verify_token, consume_token

        b = _make_binding()
        token = issue_token(b)
        assert verify_token(token, b) is True
        consume_token(token)
        assert verify_token(token, b) is False


class TestBackwardCompatibility:
    """Legacy callers without guard fields still work end-to-end."""

    def test_legacy_caller_no_guard_fields_reaches_result(self):
        """
        Legacy callers that omit subject_state/guard_decision/action_type:
        - Policy APPROVED (empty fields pass all steps)
        - Token issued with empty strings + None capability
        - Non-execution result returned (not a denied result)
        """
        from assistant_os.capabilities.token_issuer import _token_registry
        _reset()
        from assistant_os.core.orchestrator import handle_request
        req = {
            "text": "What is the status?",
            "context_id": "ctx-legacy-s12",
            "filters": {},
            "metadata": {},
        }
        result = handle_request(req)
        assert result.get("result_type") != "denied"
        # A token was issued (registry is not empty)
        assert len(_token_registry) > 0
