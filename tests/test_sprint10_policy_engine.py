"""
Sprint 10 — Policy Engine Tests.

Validates the unified authorization layer: evaluate_policy(context) → PolicyDecision.

Coverage
--------
Unit tests — policy_models.py:
  - PolicyOutcome, PolicyReason enum values (stable tokens)
  - PolicyContext construction and immutability
  - PolicyDecision.error_type property for every reason

Unit tests — policy_engine.py (evaluate_policy in isolation):
  Step 1: subject_state hard stop (suspended, terminated)
  Step 2: guard_decision hard stop ("deny")
  Step 4: capability evaluation (quarantined + execute → denied)
  Step 5: DEGRADED path (write-like → NEEDS_CONSENT, read-like → QUARANTINED)
  Step 6: APPROVED (all checks pass)
  Ordering guarantees (step 1 before step 2, step 2 before step 4, etc.)

Integration tests — orchestrator.handle_request() with policy engine active:
  - Every execution path passes through policy_engine (no manual auth blocks remain)
  - Backward compatibility: legacy callers (no guard fields) still reach execution
  - All error types match what prior tests expected

Scope
-----
  Unit tests: policy/ modules in isolation.
  Integration tests: orchestrator.handle_request() — gate position, not downstream execution.
"""

from __future__ import annotations

import pytest


# ===========================================================================
# Helpers
# ===========================================================================

def _ctx(subject_state="active", guard_decision="allow", action_type="read", principal_id=""):
    """Shorthand PolicyContext factory."""
    from assistant_os.policy.policy_models import PolicyContext
    return PolicyContext(
        subject_state=subject_state,
        guard_decision=guard_decision,
        action_type=action_type,
        principal_id=principal_id,
    )


def _eval(subject_state="active", guard_decision="allow", action_type="read", principal_id=""):
    """Shorthand: build context and call evaluate_policy."""
    from assistant_os.policy.policy_engine import evaluate_policy
    return evaluate_policy(_ctx(subject_state, guard_decision, action_type, principal_id))


# ===========================================================================
# Unit tests — policy_models
# ===========================================================================

class TestPolicyOutcome:
    """PolicyOutcome enum values are stable string tokens."""

    def test_approved_value(self):
        from assistant_os.policy.policy_models import PolicyOutcome
        assert PolicyOutcome.APPROVED.value == "approved"

    def test_denied_value(self):
        from assistant_os.policy.policy_models import PolicyOutcome
        assert PolicyOutcome.DENIED.value == "denied"

    def test_needs_consent_value(self):
        from assistant_os.policy.policy_models import PolicyOutcome
        assert PolicyOutcome.NEEDS_CONSENT.value == "needs_consent"

    def test_quarantined_value(self):
        from assistant_os.policy.policy_models import PolicyOutcome
        assert PolicyOutcome.QUARANTINED.value == "quarantined"

    def test_outcomes_are_str_enum(self):
        from assistant_os.policy.policy_models import PolicyOutcome
        assert isinstance(PolicyOutcome.APPROVED, str)
        assert "approved" in {PolicyOutcome.APPROVED}


class TestPolicyReason:
    """PolicyReason enum values are stable string tokens."""

    def test_approved_value(self):
        from assistant_os.policy.policy_models import PolicyReason
        assert PolicyReason.APPROVED.value == "approved"

    def test_subject_state_blocked_value(self):
        from assistant_os.policy.policy_models import PolicyReason
        assert PolicyReason.SUBJECT_STATE_BLOCKED.value == "subject_state_blocked"

    def test_guard_denied_value(self):
        from assistant_os.policy.policy_models import PolicyReason
        assert PolicyReason.GUARD_DENIED.value == "guard_denied"

    def test_capability_denied_value(self):
        from assistant_os.policy.policy_models import PolicyReason
        assert PolicyReason.CAPABILITY_DENIED.value == "capability_denied"

    def test_write_in_quarantine_value(self):
        from assistant_os.policy.policy_models import PolicyReason
        assert PolicyReason.WRITE_IN_QUARANTINE.value == "write_in_quarantine"


class TestPolicyContext:
    """PolicyContext is an immutable snapshot."""

    def test_construction(self):
        from assistant_os.policy.policy_models import PolicyContext
        ctx = PolicyContext(
            subject_state="active",
            guard_decision="allow",
            action_type="read",
            principal_id="user-1",
        )
        assert ctx.subject_state == "active"
        assert ctx.guard_decision == "allow"
        assert ctx.action_type == "read"
        assert ctx.principal_id == "user-1"

    def test_principal_id_defaults_to_empty_string(self):
        from assistant_os.policy.policy_models import PolicyContext
        ctx = PolicyContext(subject_state="active", guard_decision="allow", action_type="read")
        assert ctx.principal_id == ""

    def test_is_frozen(self):
        """PolicyContext is immutable — attribute assignment raises."""
        from assistant_os.policy.policy_models import PolicyContext
        ctx = PolicyContext(subject_state="active", guard_decision="allow", action_type="read")
        with pytest.raises((AttributeError, TypeError)):
            ctx.subject_state = "suspended"  # type: ignore[misc]


class TestPolicyDecisionErrorType:
    """PolicyDecision.error_type maps reason → backward-compatible error string."""

    def test_approved_reason_gives_empty_error_type(self):
        from assistant_os.policy.policy_models import PolicyDecision, PolicyOutcome, PolicyReason
        d = PolicyDecision(outcome=PolicyOutcome.APPROVED, reason=PolicyReason.APPROVED,
                           detail="ok", permitted=True)
        assert d.error_type == ""

    def test_quarantined_outcome_approved_reason_gives_empty_error_type(self):
        """QUARANTINED outcome uses APPROVED reason → error_type is empty (permitted=True)."""
        from assistant_os.policy.policy_models import PolicyDecision, PolicyOutcome, PolicyReason
        d = PolicyDecision(outcome=PolicyOutcome.QUARANTINED, reason=PolicyReason.APPROVED,
                           detail="restricted", permitted=True)
        assert d.error_type == ""

    def test_capability_denied_reason_gives_capability_denied(self):
        from assistant_os.policy.policy_models import PolicyDecision, PolicyOutcome, PolicyReason
        d = PolicyDecision(outcome=PolicyOutcome.DENIED, reason=PolicyReason.CAPABILITY_DENIED,
                           detail="cap", permitted=False)
        assert d.error_type == "capability_denied"

    def test_write_in_quarantine_reason_gives_write_blocked(self):
        from assistant_os.policy.policy_models import PolicyDecision, PolicyOutcome, PolicyReason
        d = PolicyDecision(outcome=PolicyOutcome.NEEDS_CONSENT, reason=PolicyReason.WRITE_IN_QUARANTINE,
                           detail="write", permitted=False)
        assert d.error_type == "write_blocked"

    def test_subject_state_blocked_gives_access_denied(self):
        from assistant_os.policy.policy_models import PolicyDecision, PolicyOutcome, PolicyReason
        d = PolicyDecision(outcome=PolicyOutcome.DENIED, reason=PolicyReason.SUBJECT_STATE_BLOCKED,
                           detail="suspended", permitted=False)
        assert d.error_type == "access_denied"

    def test_guard_denied_gives_access_denied(self):
        from assistant_os.policy.policy_models import PolicyDecision, PolicyOutcome, PolicyReason
        d = PolicyDecision(outcome=PolicyOutcome.DENIED, reason=PolicyReason.GUARD_DENIED,
                           detail="guard", permitted=False)
        assert d.error_type == "access_denied"

    def test_decision_is_frozen(self):
        from assistant_os.policy.policy_models import PolicyDecision, PolicyOutcome, PolicyReason
        d = PolicyDecision(outcome=PolicyOutcome.APPROVED, reason=PolicyReason.APPROVED,
                           detail="ok", permitted=True)
        with pytest.raises((AttributeError, TypeError)):
            d.permitted = False  # type: ignore[misc]


# ===========================================================================
# Unit tests — evaluate_policy: step 1 (subject_state hard stop)
# ===========================================================================

class TestStep1SubjectStateHardStop:
    """Suspended and terminated subjects are denied before all other checks."""

    def test_suspended_is_denied(self):
        from assistant_os.policy.policy_models import PolicyOutcome, PolicyReason
        d = _eval(subject_state="suspended", guard_decision="allow", action_type="read")
        assert d.outcome == PolicyOutcome.DENIED
        assert d.reason == PolicyReason.SUBJECT_STATE_BLOCKED
        assert d.permitted is False

    def test_terminated_is_denied(self):
        from assistant_os.policy.policy_models import PolicyOutcome, PolicyReason
        d = _eval(subject_state="terminated", guard_decision="allow", action_type="read")
        assert d.outcome == PolicyOutcome.DENIED
        assert d.reason == PolicyReason.SUBJECT_STATE_BLOCKED
        assert d.permitted is False

    def test_suspended_denied_even_with_deny_guard(self):
        """Step 1 fires before step 2; both would deny but reason is SUBJECT_STATE_BLOCKED."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="suspended", guard_decision="deny", action_type="execute")
        assert d.reason == PolicyReason.SUBJECT_STATE_BLOCKED

    def test_suspended_error_type_is_access_denied(self):
        d = _eval(subject_state="suspended")
        assert d.error_type == "access_denied"

    def test_terminated_error_type_is_access_denied(self):
        d = _eval(subject_state="terminated")
        assert d.error_type == "access_denied"

    def test_active_not_blocked(self):
        """Active state is not a terminal state."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="active", guard_decision="allow", action_type="read")
        assert d.reason != PolicyReason.SUBJECT_STATE_BLOCKED

    def test_quarantined_not_blocked_by_step1(self):
        """Quarantined is not in _TERMINAL_STATES — passes step 1."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="allow", action_type="read")
        assert d.reason != PolicyReason.SUBJECT_STATE_BLOCKED


# ===========================================================================
# Unit tests — evaluate_policy: step 2 (guard_decision hard stop)
# ===========================================================================

class TestStep2GuardDecisionHardStop:
    """guard_decision == 'deny' → DENIED(GUARD_DENIED), regardless of capability."""

    def test_deny_guard_returns_denied(self):
        from assistant_os.policy.policy_models import PolicyOutcome, PolicyReason
        d = _eval(subject_state="active", guard_decision="deny", action_type="read")
        assert d.outcome == PolicyOutcome.DENIED
        assert d.reason == PolicyReason.GUARD_DENIED
        assert d.permitted is False

    def test_deny_guard_error_type_is_access_denied(self):
        d = _eval(subject_state="active", guard_decision="deny")
        assert d.error_type == "access_denied"

    def test_deny_guard_fires_before_capability_gate(self):
        """
        quarantined + deny guard + execute action:
        Step 2 fires (GUARD_DENIED) before step 4 (CAPABILITY_DENIED).
        """
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="deny", action_type="execute")
        assert d.reason == PolicyReason.GUARD_DENIED

    def test_allow_guard_does_not_trigger_step2(self):
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="active", guard_decision="allow", action_type="read")
        assert d.reason != PolicyReason.GUARD_DENIED

    def test_empty_guard_decision_does_not_trigger_step2(self):
        """Legacy callers (no guard_decision) → step 2 passes."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="active", guard_decision="", action_type="read")
        assert d.reason != PolicyReason.GUARD_DENIED


# ===========================================================================
# Unit tests — evaluate_policy: step 4 (capability evaluation)
# ===========================================================================

class TestStep4CapabilityEvaluation:
    """Capability check fires when required_capability(action_type) is not None."""

    def test_quarantined_execute_is_denied(self):
        from assistant_os.policy.policy_models import PolicyOutcome, PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="allow", action_type="execute")
        assert d.outcome == PolicyOutcome.DENIED
        assert d.reason == PolicyReason.CAPABILITY_DENIED
        assert d.permitted is False

    def test_quarantined_execute_error_type_is_capability_denied(self):
        d = _eval(subject_state="quarantined", guard_decision="allow", action_type="execute")
        assert d.error_type == "capability_denied"

    def test_suspended_execute_with_allow_guard_denied_by_capability(self):
        """
        suspended + guard=allow + action=execute:
        Step 1 actually fires first (SUBJECT_STATE_BLOCKED), not step 4.
        """
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="suspended", guard_decision="allow", action_type="execute")
        assert d.reason == PolicyReason.SUBJECT_STATE_BLOCKED

    def test_active_execute_with_allow_passes_capability(self):
        """active state permits EXECUTE_CODE capability."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="active", guard_decision="allow", action_type="execute")
        assert d.reason != PolicyReason.CAPABILITY_DENIED

    def test_active_write_with_allow_passes_capability(self):
        """active state permits WRITE_FILES capability."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="active", guard_decision="allow", action_type="write")
        assert d.reason != PolicyReason.CAPABILITY_DENIED

    def test_read_requires_no_capability_passes(self):
        """Read action_type → required_capability returns None → step 4 skipped."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="allow", action_type="read")
        assert d.reason != PolicyReason.CAPABILITY_DENIED

    def test_unknown_action_type_passes_capability(self):
        """Unknown action_type → required_capability returns None → gate passes."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="allow", action_type="unknown_xyz")
        assert d.reason != PolicyReason.CAPABILITY_DENIED


# ===========================================================================
# Unit tests — evaluate_policy: step 5 (DEGRADED path)
# ===========================================================================

class TestStep5DegradedPath:
    """guard_decision == 'degraded' → NEEDS_CONSENT (write) or QUARANTINED (read)."""

    @pytest.mark.parametrize("action_type", ["write", "network", "policy"])
    def test_degraded_write_like_returns_needs_consent(self, action_type):
        # Note: "execute" is excluded here because quarantined subjects lack EXECUTE_CODE
        # capability → step 4 fires first (CAPABILITY_DENIED) before step 5.
        # That case is covered by test_degraded_execute_fires_capability_check_first.
        from assistant_os.policy.policy_models import PolicyOutcome, PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="degraded", action_type=action_type)
        assert d.outcome == PolicyOutcome.NEEDS_CONSENT
        assert d.reason == PolicyReason.WRITE_IN_QUARANTINE
        assert d.permitted is False

    @pytest.mark.parametrize("action_type", ["write", "network", "policy"])
    def test_degraded_write_like_error_type_is_write_blocked(self, action_type):
        # "execute" excluded for same reason as above.
        d = _eval(subject_state="quarantined", guard_decision="degraded", action_type=action_type)
        assert d.error_type == "write_blocked"

    def test_degraded_read_returns_quarantined(self):
        from assistant_os.policy.policy_models import PolicyOutcome, PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="degraded", action_type="read")
        assert d.outcome == PolicyOutcome.QUARANTINED
        assert d.reason == PolicyReason.APPROVED
        assert d.permitted is True

    def test_degraded_read_error_type_is_empty(self):
        """Permitted outcome → error_type is empty string."""
        d = _eval(subject_state="quarantined", guard_decision="degraded", action_type="read")
        assert d.error_type == ""

    def test_degraded_empty_action_type_returns_quarantined(self):
        """Empty action_type (legacy/NL) in DEGRADED → read-like → QUARANTINED (permitted)."""
        from assistant_os.policy.policy_models import PolicyOutcome
        d = _eval(subject_state="quarantined", guard_decision="degraded", action_type="")
        assert d.outcome == PolicyOutcome.QUARANTINED
        assert d.permitted is True

    def test_degraded_execute_fires_capability_check_first(self):
        """
        quarantined + degraded + execute:
        Step 4 fires first (execute requires EXECUTE_CODE, quarantined denies it)
        → CAPABILITY_DENIED before reaching step 5.
        """
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="degraded", action_type="execute")
        assert d.reason == PolicyReason.CAPABILITY_DENIED

    def test_degraded_write_does_not_fail_capability_check(self):
        """
        quarantined + degraded + write:
        Step 4: WRITE_FILES is permitted for quarantined → capability passes.
        Step 5: degraded + write-like → NEEDS_CONSENT.
        """
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="degraded", action_type="write")
        assert d.reason == PolicyReason.WRITE_IN_QUARANTINE


# ===========================================================================
# Unit tests — evaluate_policy: step 6 (APPROVED)
# ===========================================================================

class TestStep6Approved:
    """All checks pass → PolicyOutcome.APPROVED, permitted=True."""

    def test_active_allow_read_approved(self):
        from assistant_os.policy.policy_models import PolicyOutcome, PolicyReason
        d = _eval(subject_state="active", guard_decision="allow", action_type="read")
        assert d.outcome == PolicyOutcome.APPROVED
        assert d.reason == PolicyReason.APPROVED
        assert d.permitted is True

    def test_active_allow_write_approved(self):
        from assistant_os.policy.policy_models import PolicyOutcome
        d = _eval(subject_state="active", guard_decision="allow", action_type="write")
        assert d.outcome == PolicyOutcome.APPROVED
        assert d.permitted is True

    def test_active_allow_execute_approved(self):
        from assistant_os.policy.policy_models import PolicyOutcome
        d = _eval(subject_state="active", guard_decision="allow", action_type="execute")
        assert d.outcome == PolicyOutcome.APPROVED
        assert d.permitted is True

    def test_legacy_caller_empty_fields_approved(self):
        """Legacy callers omitting guard fields receive APPROVED (backward-compatible)."""
        from assistant_os.policy.policy_models import PolicyOutcome
        d = _eval(subject_state="", guard_decision="", action_type="")
        assert d.outcome == PolicyOutcome.APPROVED
        assert d.permitted is True

    def test_approved_error_type_is_empty(self):
        d = _eval(subject_state="active", guard_decision="allow", action_type="read")
        assert d.error_type == ""


# ===========================================================================
# Unit tests — evaluation order guarantees
# ===========================================================================

class TestEvaluationOrder:
    """
    The evaluation order is fixed and documented.  These tests prove the
    ordering invariant by presenting inputs where multiple steps would fire
    and asserting the earlier step wins.
    """

    def test_step1_before_step2(self):
        """suspended + deny guard: step 1 (SUBJECT_STATE_BLOCKED) wins."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="suspended", guard_decision="deny", action_type="execute")
        assert d.reason == PolicyReason.SUBJECT_STATE_BLOCKED

    def test_step1_before_step4(self):
        """suspended + allow guard + execute: step 1 wins over cap gate."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="suspended", guard_decision="allow", action_type="execute")
        assert d.reason == PolicyReason.SUBJECT_STATE_BLOCKED

    def test_step2_before_step4(self):
        """quarantined + deny guard + execute: step 2 wins over cap gate."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="deny", action_type="execute")
        assert d.reason == PolicyReason.GUARD_DENIED

    def test_step2_before_step5(self):
        """quarantined + deny guard + write: step 2 wins over DEGRADED path."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="deny", action_type="write")
        assert d.reason == PolicyReason.GUARD_DENIED

    def test_step4_before_step5_execute(self):
        """quarantined + degraded + execute: step 4 (cap denied) fires before step 5."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="degraded", action_type="execute")
        assert d.reason == PolicyReason.CAPABILITY_DENIED

    def test_step4_does_not_fire_for_read(self):
        """quarantined + degraded + read: step 4 skipped (no capability required) → step 5."""
        from assistant_os.policy.policy_models import PolicyReason
        d = _eval(subject_state="quarantined", guard_decision="degraded", action_type="read")
        assert d.reason == PolicyReason.APPROVED  # step 5 QUARANTINED uses APPROVED reason

    def test_pure_function_same_inputs_same_output(self):
        """evaluate_policy is pure: same inputs always produce the same output."""
        from assistant_os.policy.policy_engine import evaluate_policy
        ctx = _ctx(subject_state="quarantined", guard_decision="allow", action_type="execute")
        d1 = evaluate_policy(ctx)
        d2 = evaluate_policy(ctx)
        d3 = evaluate_policy(ctx)
        assert d1 == d2 == d3


# ===========================================================================
# Integration tests — orchestrator.handle_request() with policy engine
# ===========================================================================

def _req(subject_state, guard_decision, action_type="read", **extra):
    """Minimal CanonicalRequest with policy fields set."""
    return {
        "text": "test",
        "context_id": f"ctx-s10-{subject_state}-{guard_decision}-{action_type}",
        "filters": {},
        "metadata": {},
        "principal_id": "user-s10-test",
        "subject_state": subject_state,
        "guard_decision": guard_decision,
        "action_type": action_type,
        **extra,
    }


class TestPolicyEngineInOrchestrator:
    """Policy engine gate position and backward compatibility in handle_request()."""

    # --- Guard DENY → access_denied (replaces old F3 block) ---

    def test_guard_deny_returns_denied(self):
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("active", "deny"))
        assert result["ok"] is False
        assert result["result_type"] == "denied"

    def test_guard_deny_error_type_is_access_denied(self):
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("active", "deny"))
        assert result["error"]["type"] == "access_denied"

    # --- Suspended/Terminated → access_denied ---

    def test_suspended_denied(self):
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("suspended", "allow"))
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "access_denied"

    def test_terminated_denied(self):
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("terminated", "allow"))
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "access_denied"

    # --- DEGRADED + write → write_blocked (replaces old F3 DEGRADED block) ---

    def test_degraded_write_returns_denied(self):
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("quarantined", "degraded", "write"))
        assert result["ok"] is False
        assert result["result_type"] == "denied"

    def test_degraded_write_error_type_is_write_blocked(self):
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("quarantined", "degraded", "write"))
        assert result["error"]["type"] == "write_blocked"

    def test_degraded_read_is_permitted(self):
        """quarantined + degraded + read → QUARANTINED (permitted) — does NOT return denied."""
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("quarantined", "degraded", "read"))
        assert result.get("result_type") != "denied"

    # --- Capability gate → capability_denied (replaces old S9 block) ---

    def test_capability_denied_for_quarantined_execute(self):
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("quarantined", "allow", "execute"))
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "capability_denied"

    def test_capability_denied_for_suspended_execute_via_allow_guard(self):
        """
        suspended + allow guard + execute:
        Step 1 fires (SUBJECT_STATE_BLOCKED → access_denied), not step 4.
        """
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("suspended", "allow", "execute"))
        assert result["error"]["type"] == "access_denied"

    # --- Ordering: guard DENY before capability gate ---

    def test_guard_deny_wins_over_capability_gate(self):
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("quarantined", "deny", "execute"))
        assert result["error"]["type"] == "access_denied"
        assert result["error"]["type"] != "capability_denied"

    # --- Backward compatibility: legacy callers ---

    def test_legacy_caller_no_guard_fields_reaches_execution(self):
        """
        Legacy callers that do not include guard_decision/subject_state/action_type
        must NOT be denied by the policy engine.
        """
        from assistant_os.core.orchestrator import handle_request
        req = {
            "text": "What is the status?",
            "context_id": "ctx-legacy-s10",
            "filters": {},
            "metadata": {},
        }
        result = handle_request(req)
        assert result.get("result_type") != "denied"

    def test_no_guard_decision_backward_compat(self):
        """Request without guard_decision should not be blocked by policy engine."""
        from assistant_os.core.orchestrator import handle_request
        req = {
            "text": "hello",
            "context_id": "ctx-legacy-noguard",
            "filters": {},
            "metadata": {},
            "subject_state": "active",
        }
        result = handle_request(req)
        assert result.get("result_type") != "denied"

    # --- data is empty on denied results ---

    def test_denied_result_has_empty_data(self):
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("quarantined", "allow", "execute"))
        assert result["data"] == {}

    # --- error types are mutually distinct ---

    def test_access_denied_and_capability_denied_are_distinct(self):
        from assistant_os.core.orchestrator import handle_request
        # access_denied path
        r1 = handle_request(_req("active", "deny"))
        # capability_denied path
        r2 = handle_request(_req("quarantined", "allow", "execute"))
        assert r1["error"]["type"] != r2["error"]["type"]

    def test_write_blocked_and_access_denied_are_distinct(self):
        from assistant_os.core.orchestrator import handle_request
        # write_blocked path
        r1 = handle_request(_req("quarantined", "degraded", "write"))
        # access_denied path
        r2 = handle_request(_req("active", "deny"))
        assert r1["error"]["type"] != r2["error"]["type"]


# ===========================================================================
# Integration tests — policy engine subsumes all three prior manual blocks
# ===========================================================================

class TestPolicyEngineSubsumption:
    """
    Confirm that the three prior ad-hoc auth blocks (F3 guard DENY,
    F3 DEGRADED write, S9 capability gate) are correctly reproduced
    by the unified policy engine, with identical observable behavior.
    """

    def test_f3_guard_deny_reproduced(self):
        """F3 guard DENY → result_type='denied', error.type='access_denied'."""
        from assistant_os.core.orchestrator import handle_request
        result = handle_request({
            "text": "blocked",
            "context_id": "ctx-sub-guard-deny",
            "filters": {},
            "metadata": {},
            "principal_id": "user-1",
            "subject_state": "quarantined",
            "guard_decision": "deny",
            "action_type": "execute",
        })
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "access_denied"

    def test_f3_degraded_write_reproduced(self):
        """F3 DEGRADED write block → result_type='denied', error.type='write_blocked'."""
        from assistant_os.core.orchestrator import handle_request
        result = handle_request({
            "text": "write something",
            "context_id": "ctx-sub-deg-write",
            "filters": {},
            "metadata": {"action": "FIN_EXPENSE"},
            "principal_id": "user-1",
            "subject_state": "quarantined",
            "guard_decision": "degraded",
            "action_type": "write",
        })
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "write_blocked"

    def test_s9_capability_gate_reproduced(self):
        """S9 capability gate → result_type='denied', error.type='capability_denied'."""
        from assistant_os.core.orchestrator import handle_request
        result = handle_request({
            "text": "execute something",
            "context_id": "ctx-sub-cap",
            "filters": {},
            "metadata": {},
            "principal_id": "user-1",
            "subject_state": "quarantined",
            "guard_decision": "allow",
            "action_type": "execute",
        })
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "capability_denied"
