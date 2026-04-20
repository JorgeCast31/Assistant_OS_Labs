"""
Sprint 13 — Grant Skeleton Tests.

Validates the explicit grant layer and its integration with the policy engine
and the orchestrator token pipeline.

Architecture under test
-----------------------
  Request
    → evaluate_policy(context, grant_store)
        1. subject_state hard stop
        2. guard_decision hard stop
        3. required_capability(action_type)
        4. capability evaluation
        5. grant lookup          ← Sprint 13
        6. DEGRADED path
        7. APPROVED
    → [if APPROVED] issue_token
    → [before execute] verify_token → consume_token
    → pipeline dispatch

Coverage
--------
Unit — grant_models:
  Grant and GrantQuery construction, immutability, field semantics.

Unit — grant_store (InMemoryGrantStore):
  add_grant, find_applicable_grant matching rules, has_grants,
  inactive grant, expired grant, scope_prefix filter, clear.

Unit — evaluate_policy with grants (steps 4→5 ordering):
  - No grant store (None) → APPROVED (backward compat, step 5 skipped)
  - Empty store → APPROVED (permissive fallback, step 5 skipped)
  - Non-empty store, matching grant → APPROVED
  - Non-empty store, no match → DENIED(NO_APPLICABLE_GRANT)
  - Grant check fires AFTER capability check (steps 4 < 5)
  - Grant check fires BEFORE DEGRADED path (step 5 < step 6)
  - error_type == "grant_denied" for NO_APPLICABLE_GRANT
  - PolicyContext.operation_key passed through to GrantQuery
  - scope_prefix respected inside evaluate_policy
  - Expired grant → no match → denied

Integration — orchestrator.handle_request():
  - Empty default store → APPROVED path (legacy behavior preserved)
  - Matching grant in default store → APPROVED → token issued
  - Non-matching grant in default store → DENIED(grant_denied) → no token
  - Denied principal gets grant_denied, not access_denied or capability_denied
  - All execution paths still route through policy engine (no bypass)
"""

from __future__ import annotations

import time
import uuid

import pytest


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def clean_stores():
    """
    Ensure clean grant store and token registry before each test.

    autouse=True: applied to every test in this module automatically.
    """
    from assistant_os.grants.grant_store import get_default_store
    from assistant_os.capabilities.token_issuer import _reset_registry
    get_default_store().clear()
    _reset_registry()
    yield
    get_default_store().clear()
    _reset_registry()


# ===========================================================================
# Helpers
# ===========================================================================

def _grant(
    principal_id="user-1",
    action_type="read",
    capability=None,
    scope_prefix="",
    is_active=True,
    expires_at=None,
    grant_id=None,
):
    from assistant_os.grants.grant_models import Grant
    return Grant(
        grant_id=grant_id or str(uuid.uuid4()),
        principal_id=principal_id,
        action_type=action_type,
        capability=capability,
        scope_prefix=scope_prefix,
        is_active=is_active,
        issued_at=time.time(),
        expires_at=expires_at,
    )


def _query(
    principal_id="user-1",
    action_type="read",
    capability=None,
    operation_key="ctx-test",
):
    from assistant_os.grants.grant_models import GrantQuery
    return GrantQuery(
        principal_id=principal_id,
        action_type=action_type,
        capability=capability,
        operation_key=operation_key,
    )


def _ctx(
    subject_state="active",
    guard_decision="allow",
    action_type="read",
    principal_id="user-1",
    operation_key="ctx-test",
):
    from assistant_os.policy.policy_models import PolicyContext
    return PolicyContext(
        subject_state=subject_state,
        guard_decision=guard_decision,
        action_type=action_type,
        principal_id=principal_id,
        operation_key=operation_key,
    )


def _eval(ctx, store=None):
    from assistant_os.policy.policy_engine import evaluate_policy
    return evaluate_policy(ctx, grant_store=store)


def _new_store(*grants):
    from assistant_os.grants.grant_store import InMemoryGrantStore
    s = InMemoryGrantStore()
    for g in grants:
        s.add_grant(g)
    return s


def _req(
    subject_state="active",
    guard_decision="allow",
    action_type="read",
    principal_id="user-s13",
    context_id=None,
    **extra,
):
    return {
        "text": "test",
        "context_id": context_id or f"ctx-s13-{principal_id}-{action_type}",
        "filters": {},
        "metadata": {},
        "principal_id": principal_id,
        "subject_state": subject_state,
        "guard_decision": guard_decision,
        "action_type": action_type,
        **extra,
    }


# ===========================================================================
# Unit — grant_models
# ===========================================================================

class TestGrantConstruction:
    def test_grant_fields(self):
        g = _grant(
            principal_id="alice",
            action_type="write",
            capability="write_files",
            scope_prefix="ctx-proj",
            is_active=True,
        )
        assert g.principal_id == "alice"
        assert g.action_type == "write"
        assert g.capability == "write_files"
        assert g.scope_prefix == "ctx-proj"
        assert g.is_active is True
        assert g.expires_at is None

    def test_grant_with_expiry(self):
        exp = time.time() + 3600
        g = _grant(expires_at=exp)
        assert g.expires_at == exp

    def test_grant_capability_none(self):
        g = _grant(capability=None)
        assert g.capability is None

    def test_grant_is_frozen(self):
        g = _grant()
        with pytest.raises((AttributeError, TypeError)):
            g.is_active = False  # type: ignore[misc]

    def test_grant_query_fields(self):
        q = _query(
            principal_id="bob",
            action_type="execute",
            capability="execute_code",
            operation_key="ctx-run",
        )
        assert q.principal_id == "bob"
        assert q.action_type == "execute"
        assert q.capability == "execute_code"
        assert q.operation_key == "ctx-run"

    def test_grant_query_is_frozen(self):
        q = _query()
        with pytest.raises((AttributeError, TypeError)):
            q.principal_id = "hacked"  # type: ignore[misc]


# ===========================================================================
# Unit — InMemoryGrantStore
# ===========================================================================

class TestInMemoryGrantStore:

    # --- has_grants ---

    def test_empty_store_has_no_grants(self):
        from assistant_os.grants.grant_store import InMemoryGrantStore
        s = InMemoryGrantStore()
        assert s.has_grants() is False

    def test_store_with_grant_has_grants(self):
        s = _new_store(_grant())
        assert s.has_grants() is True

    def test_clear_empties_store(self):
        from assistant_os.grants.grant_store import InMemoryGrantStore
        s = InMemoryGrantStore()
        s.add_grant(_grant())
        s.clear()
        assert s.has_grants() is False

    # --- find_applicable_grant: happy path ---

    def test_matching_grant_found(self):
        g = _grant(principal_id="u1", action_type="read", capability=None)
        s = _new_store(g)
        q = _query(principal_id="u1", action_type="read", capability=None)
        assert s.find_applicable_grant(q) is g

    def test_no_match_returns_none(self):
        g = _grant(principal_id="u1", action_type="read")
        s = _new_store(g)
        q = _query(principal_id="u2", action_type="read")  # different principal
        assert s.find_applicable_grant(q) is None

    # --- Rule 1: is_active ---

    def test_inactive_grant_not_matched(self):
        g = _grant(is_active=False)
        s = _new_store(g)
        q = _query()
        assert s.find_applicable_grant(q) is None

    def test_active_grant_matched(self):
        g = _grant(is_active=True)
        s = _new_store(g)
        q = _query()
        assert s.find_applicable_grant(q) is g

    # --- Rule 2: principal_id ---

    def test_different_principal_not_matched(self):
        g = _grant(principal_id="alice")
        s = _new_store(g)
        q = _query(principal_id="bob")
        assert s.find_applicable_grant(q) is None

    def test_same_principal_matched(self):
        g = _grant(principal_id="alice")
        s = _new_store(g)
        q = _query(principal_id="alice")
        assert s.find_applicable_grant(q) is g

    # --- Rule 3: action_type ---

    def test_different_action_type_not_matched(self):
        g = _grant(action_type="read")
        s = _new_store(g)
        q = _query(action_type="write")
        assert s.find_applicable_grant(q) is None

    def test_same_action_type_matched(self):
        g = _grant(action_type="write")
        s = _new_store(g)
        q = _query(action_type="write")
        assert s.find_applicable_grant(q) is g

    # --- Rule 4: capability ---

    def test_different_capability_not_matched(self):
        g = _grant(capability="execute_code")
        s = _new_store(g)
        q = _query(capability="write_files")
        assert s.find_applicable_grant(q) is None

    def test_capability_none_matches_none(self):
        g = _grant(capability=None)
        s = _new_store(g)
        q = _query(capability=None)
        assert s.find_applicable_grant(q) is g

    def test_capability_none_does_not_match_value(self):
        g = _grant(capability=None)
        s = _new_store(g)
        q = _query(capability="write_files")
        assert s.find_applicable_grant(q) is None

    def test_capability_value_does_not_match_none(self):
        g = _grant(capability="write_files")
        s = _new_store(g)
        q = _query(capability=None)
        assert s.find_applicable_grant(q) is None

    # --- Rule 5: scope_prefix ---

    def test_empty_scope_prefix_matches_any_operation_key(self):
        g = _grant(scope_prefix="")
        s = _new_store(g)
        q = _query(operation_key="ctx-anything-at-all")
        assert s.find_applicable_grant(q) is g

    def test_scope_prefix_matches_when_key_starts_with(self):
        g = _grant(scope_prefix="ctx-proj-")
        s = _new_store(g)
        q = _query(operation_key="ctx-proj-abc")
        assert s.find_applicable_grant(q) is g

    def test_scope_prefix_does_not_match_when_key_doesnt_start_with(self):
        g = _grant(scope_prefix="ctx-proj-")
        s = _new_store(g)
        q = _query(operation_key="ctx-other-abc")
        assert s.find_applicable_grant(q) is None

    def test_scope_prefix_exact_match(self):
        g = _grant(scope_prefix="ctx-exact")
        s = _new_store(g)
        q = _query(operation_key="ctx-exact")
        assert s.find_applicable_grant(q) is g

    # --- Rule 6: expiry ---

    def test_not_yet_expired_grant_matched(self):
        g = _grant(expires_at=time.time() + 3600)
        s = _new_store(g)
        q = _query()
        assert s.find_applicable_grant(q) is g

    def test_expired_grant_not_matched(self):
        g = _grant(expires_at=time.time() - 1)  # 1 second ago
        s = _new_store(g)
        q = _query()
        assert s.find_applicable_grant(q) is None

    def test_no_expiry_never_expires(self):
        g = _grant(expires_at=None)
        s = _new_store(g)
        q = _query()
        assert s.find_applicable_grant(q) is g

    # --- Multiple grants: first match wins ---

    def test_first_matching_grant_returned(self):
        g1 = _grant(principal_id="u1", action_type="read", grant_id="g1")
        g2 = _grant(principal_id="u1", action_type="read", grant_id="g2")
        s = _new_store(g1, g2)
        q = _query(principal_id="u1", action_type="read")
        result = s.find_applicable_grant(q)
        assert result is g1

    def test_second_grant_matches_when_first_inactive(self):
        g1 = _grant(is_active=False, grant_id="g1")
        g2 = _grant(is_active=True, grant_id="g2")
        s = _new_store(g1, g2)
        q = _query()
        result = s.find_applicable_grant(q)
        assert result is g2


# ===========================================================================
# Unit — evaluate_policy with grants (step 5)
# ===========================================================================

class TestEvaluatePolicyGrantCheck:
    """grant_store parameter wiring and step 5 behavior."""

    # --- Backward compatibility ---

    def test_no_store_gives_approved(self):
        """grant_store=None → step 5 skipped → APPROVED."""
        from assistant_os.policy.policy_models import PolicyOutcome
        d = _eval(_ctx(), store=None)
        assert d.outcome == PolicyOutcome.APPROVED
        assert d.permitted is True

    def test_empty_store_gives_approved(self):
        """Empty store → step 5 skipped → APPROVED."""
        from assistant_os.policy.policy_models import PolicyOutcome
        from assistant_os.grants.grant_store import InMemoryGrantStore
        d = _eval(_ctx(), store=InMemoryGrantStore())
        assert d.outcome == PolicyOutcome.APPROVED
        assert d.permitted is True

    # --- Grant found → proceed ---

    def test_matching_grant_gives_approved(self):
        from assistant_os.policy.policy_models import PolicyOutcome
        s = _new_store(_grant(principal_id="user-1", action_type="read", capability=None))
        d = _eval(_ctx(), store=s)
        assert d.outcome == PolicyOutcome.APPROVED
        assert d.permitted is True

    def test_matching_grant_for_write(self):
        """write + active + allow + grant(write, write_files) → APPROVED."""
        from assistant_os.policy.policy_models import PolicyOutcome
        s = _new_store(_grant(principal_id="user-1", action_type="write", capability="write_files"))
        d = _eval(_ctx(action_type="write"), store=s)
        assert d.outcome == PolicyOutcome.APPROVED
        assert d.permitted is True

    # --- No grant → denied ---

    def test_no_matching_grant_gives_denied(self):
        from assistant_os.policy.policy_models import PolicyOutcome, PolicyReason
        s = _new_store(_grant(principal_id="other-user"))  # non-empty but no match
        d = _eval(_ctx(principal_id="user-1"), store=s)
        assert d.outcome == PolicyOutcome.DENIED
        assert d.reason == PolicyReason.NO_APPLICABLE_GRANT
        assert d.permitted is False

    def test_no_matching_grant_error_type_is_grant_denied(self):
        s = _new_store(_grant(principal_id="other-user"))
        d = _eval(_ctx(principal_id="user-1"), store=s)
        assert d.error_type == "grant_denied"

    def test_expired_grant_gives_denied(self):
        from assistant_os.policy.policy_models import PolicyReason
        s = _new_store(_grant(expires_at=time.time() - 1))
        d = _eval(_ctx(), store=s)
        assert d.reason == PolicyReason.NO_APPLICABLE_GRANT

    def test_inactive_grant_gives_denied(self):
        from assistant_os.policy.policy_models import PolicyReason
        s = _new_store(_grant(is_active=False))
        d = _eval(_ctx(), store=s)
        assert d.reason == PolicyReason.NO_APPLICABLE_GRANT

    # --- Evaluation order ---

    def test_step4_fires_before_step5_capability_denied_wins(self):
        """
        quarantined + allow + execute: step 4 (capability denied) fires before
        step 5 (grant check).  Even with a matching grant, capability takes precedence.
        """
        from assistant_os.policy.policy_models import PolicyReason
        s = _new_store(_grant(
            principal_id="user-1",
            action_type="execute",
            capability="execute_code",
        ))
        d = _eval(
            _ctx(subject_state="quarantined", action_type="execute"),
            store=s,
        )
        # Step 4: quarantined cannot execute_code → CAPABILITY_DENIED
        assert d.reason == PolicyReason.CAPABILITY_DENIED

    def test_step2_fires_before_step5_guard_denied_wins(self):
        """
        guard_decision=deny: step 2 fires before step 5.
        Even with a matching grant, guard DENY takes precedence.
        """
        from assistant_os.policy.policy_models import PolicyReason
        s = _new_store(_grant(principal_id="user-1", action_type="read"))
        d = _eval(_ctx(guard_decision="deny"), store=s)
        assert d.reason == PolicyReason.GUARD_DENIED

    def test_step1_fires_before_step5_subject_state_blocked_wins(self):
        """
        suspended: step 1 fires before step 5.
        """
        from assistant_os.policy.policy_models import PolicyReason
        s = _new_store(_grant(principal_id="user-1", action_type="read"))
        d = _eval(_ctx(subject_state="suspended"), store=s)
        assert d.reason == PolicyReason.SUBJECT_STATE_BLOCKED

    def test_step5_fires_before_step6_degraded_path(self):
        """
        quarantined + degraded + write + NO grant:
        Step 5 (grant denied) fires before step 6 (DEGRADED → NEEDS_CONSENT).
        """
        from assistant_os.policy.policy_models import PolicyReason
        # Store has a grant for a different user to activate step 5
        s = _new_store(_grant(principal_id="other-user", action_type="write"))
        d = _eval(
            _ctx(subject_state="quarantined", guard_decision="degraded",
                 action_type="write", principal_id="user-1"),
            store=s,
        )
        assert d.reason == PolicyReason.NO_APPLICABLE_GRANT

    def test_step5_pass_then_step6_degraded_write_gives_needs_consent(self):
        """
        quarantined + degraded + write + matching grant:
        Step 5 passes → step 6 (DEGRADED + write) → NEEDS_CONSENT.
        """
        from assistant_os.policy.policy_models import PolicyOutcome, PolicyReason
        s = _new_store(_grant(
            principal_id="user-1",
            action_type="write",
            capability="write_files",
        ))
        d = _eval(
            _ctx(subject_state="quarantined", guard_decision="degraded",
                 action_type="write", principal_id="user-1"),
            store=s,
        )
        assert d.outcome == PolicyOutcome.NEEDS_CONSENT
        assert d.reason == PolicyReason.WRITE_IN_QUARANTINE

    def test_step5_pass_then_step6_degraded_read_gives_quarantined(self):
        """
        quarantined + degraded + read + matching grant:
        Step 5 passes → step 6 (DEGRADED + read) → QUARANTINED (permitted).
        """
        from assistant_os.policy.policy_models import PolicyOutcome
        s = _new_store(_grant(
            principal_id="user-1",
            action_type="read",
            capability=None,
        ))
        d = _eval(
            _ctx(subject_state="quarantined", guard_decision="degraded",
                 action_type="read", principal_id="user-1"),
            store=s,
        )
        assert d.outcome == PolicyOutcome.QUARANTINED
        assert d.permitted is True

    # --- operation_key threading ---

    def test_operation_key_passed_to_grant_query(self):
        """scope_prefix filters are respected when operation_key is threaded through."""
        # Grant only covers "ctx-prod-" prefix
        s = _new_store(_grant(scope_prefix="ctx-prod-"))
        # Matching key
        d_match = _eval(_ctx(operation_key="ctx-prod-abc"), store=s)
        assert d_match.permitted is True
        # Non-matching key
        d_no = _eval(_ctx(operation_key="ctx-dev-abc"), store=s)
        assert d_no.permitted is False
        assert d_no.error_type == "grant_denied"

    def test_empty_operation_key_matches_empty_scope_prefix(self):
        """operation_key='' with scope_prefix='' → match (any operation)."""
        s = _new_store(_grant(scope_prefix=""))
        d = _eval(_ctx(operation_key=""), store=s)
        assert d.permitted is True

    def test_empty_operation_key_does_not_match_nonempty_scope_prefix(self):
        """operation_key='' with scope_prefix='ctx-prod-' → no match."""
        s = _new_store(_grant(scope_prefix="ctx-prod-"))
        d = _eval(_ctx(operation_key=""), store=s)
        assert d.permitted is False

    # --- error_type mapping ---

    def test_no_applicable_grant_reason_value(self):
        from assistant_os.policy.policy_models import PolicyReason
        assert PolicyReason.NO_APPLICABLE_GRANT.value == "no_applicable_grant"

    def test_grant_denied_error_type_distinct_from_access_denied(self):
        s = _new_store(_grant(principal_id="other"))
        d = _eval(_ctx(principal_id="user-1"), store=s)
        assert d.error_type == "grant_denied"
        assert d.error_type != "access_denied"
        assert d.error_type != "capability_denied"


# ===========================================================================
# Integration — orchestrator.handle_request() with grant layer
# ===========================================================================

class TestGrantsInOrchestrator:
    """
    Default store is passed to evaluate_policy by the orchestrator.
    Tests use the autouse fixture to clean the store before each test.
    """

    def test_empty_store_approved_legacy_behavior(self):
        """
        Default store empty → grant check skipped → APPROVED path.
        All existing Sprint 9–12 integration tests depend on this.
        """
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("active", "allow", "read"))
        assert result.get("result_type") != "denied"

    def test_matching_grant_in_store_gives_approved(self):
        """
        Default store has a matching grant → policy APPROVED → token issued.
        """
        from assistant_os.grants.grant_store import get_default_store
        from assistant_os.grants.grant_models import Grant
        get_default_store().add_grant(Grant(
            grant_id="g-orch-1",
            principal_id="user-s13",
            action_type="read",
            capability=None,
            scope_prefix="",
            is_active=True,
            issued_at=time.time(),
        ))
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("active", "allow", "read", principal_id="user-s13"))
        assert result.get("result_type") != "denied"

    def test_no_matching_grant_gives_denied(self):
        """
        Default store non-empty but no match for this principal →
        DENIED(grant_denied) → no token.
        """
        from assistant_os.grants.grant_store import get_default_store
        from assistant_os.grants.grant_models import Grant
        # Grant for a different user — activates the grant check
        get_default_store().add_grant(Grant(
            grant_id="g-other",
            principal_id="other-user",
            action_type="read",
            capability=None,
            scope_prefix="",
            is_active=True,
            issued_at=time.time(),
        ))
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("active", "allow", "read", principal_id="user-s13"))
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "grant_denied"

    def test_grant_denied_no_token_issued(self):
        """
        When policy returns DENIED(NO_APPLICABLE_GRANT), no token should
        be registered as ACTIVE (token issuance is post-APPROVED only).
        """
        from assistant_os.grants.grant_store import get_default_store
        from assistant_os.grants.grant_models import Grant
        from assistant_os.capabilities.token_issuer import _token_registry
        from assistant_os.capabilities.token_models import TokenStatus

        get_default_store().add_grant(Grant(
            grant_id="g-other-2",
            principal_id="other-user",
            action_type="read",
            capability=None,
            scope_prefix="",
            is_active=True,
            issued_at=time.time(),
        ))
        from assistant_os.core.orchestrator import handle_request
        handle_request(_req("active", "allow", "read", principal_id="user-s13"))

        active = [v for v in _token_registry.values() if v == TokenStatus.ACTIVE.value]
        assert len(active) == 0, "No ACTIVE token should exist when grant is denied"

    def test_matching_grant_token_issued(self):
        """
        Matching grant → APPROVED → token registered in registry.
        """
        from assistant_os.grants.grant_store import get_default_store
        from assistant_os.grants.grant_models import Grant
        from assistant_os.capabilities.token_issuer import _token_registry

        get_default_store().add_grant(Grant(
            grant_id="g-match-tok",
            principal_id="user-s13",
            action_type="read",
            capability=None,
            scope_prefix="",
            is_active=True,
            issued_at=time.time(),
        ))
        count_before = len(_token_registry)
        from assistant_os.core.orchestrator import handle_request
        handle_request(_req("active", "allow", "read", principal_id="user-s13"))
        assert len(_token_registry) > count_before

    def test_grant_denied_is_distinct_from_policy_access_denied(self):
        """
        grant_denied (step 5) vs access_denied (step 1/2) must be distinct.
        """
        from assistant_os.grants.grant_store import get_default_store
        from assistant_os.grants.grant_models import Grant
        from assistant_os.core.orchestrator import handle_request

        get_default_store().add_grant(Grant(
            grant_id="g-dist",
            principal_id="other",
            action_type="read",
            capability=None,
            scope_prefix="",
            is_active=True,
            issued_at=time.time(),
        ))
        # Grant denied (step 5)
        r_grant = handle_request(_req("active", "allow", "read", principal_id="user-s13"))
        assert r_grant["error"]["type"] == "grant_denied"

        # Guard denied (step 2) — does NOT touch grant check
        r_guard = handle_request(_req("active", "deny", "read", principal_id="user-s13"))
        assert r_guard["error"]["type"] == "access_denied"

        assert r_grant["error"]["type"] != r_guard["error"]["type"]

    def test_grant_denied_is_distinct_from_capability_denied(self):
        """
        grant_denied (step 5) vs capability_denied (step 4) must be distinct.
        """
        from assistant_os.grants.grant_store import get_default_store
        from assistant_os.grants.grant_models import Grant
        from assistant_os.core.orchestrator import handle_request

        get_default_store().add_grant(Grant(
            grant_id="g-cap-dist",
            principal_id="other",
            action_type="execute",
            capability="execute_code",
            scope_prefix="",
            is_active=True,
            issued_at=time.time(),
        ))
        # Capability denied (step 4) — quarantined cannot execute
        r_cap = handle_request(_req("quarantined", "allow", "execute", principal_id="user-s13"))
        assert r_cap["error"]["type"] == "capability_denied"

        # Grant denied (step 5) — active can execute but no grant
        r_grant = handle_request(_req("active", "allow", "read", principal_id="user-s13"))
        assert r_grant["error"]["type"] == "grant_denied"

        assert r_cap["error"]["type"] != r_grant["error"]["type"]

    def test_all_execution_paths_go_through_policy_engine(self):
        """
        A matching grant is required even for the confirm path (Phase 3C).
        The confirm request goes through policy engine → grant check → APPROVED
        → token issued → execute confirmed plan.
        """
        from assistant_os.grants.grant_store import get_default_store
        from assistant_os.grants.grant_models import Grant
        from assistant_os.core.orchestrator import handle_request

        # Activate grant check with a non-matching grant
        get_default_store().add_grant(Grant(
            grant_id="g-confirm",
            principal_id="other-user",
            action_type="read",
            capability=None,
            scope_prefix="",
            is_active=True,
            issued_at=time.time(),
        ))
        # Confirm path request with no matching grant
        req = _req("active", "allow", "read", principal_id="user-s13")
        req["metadata"] = {"confirm_plan_id": "some-plan-id"}
        result = handle_request(req)
        # Should be denied by grant check before even trying to find the plan
        assert result["ok"] is False
        assert result["error"]["type"] == "grant_denied"

    def test_grant_scope_prefix_filters_by_context_id(self):
        """
        scope_prefix filters are respected end-to-end: grant only covers
        requests whose context_id starts with the prefix.
        """
        from assistant_os.grants.grant_store import get_default_store
        from assistant_os.grants.grant_models import Grant
        from assistant_os.core.orchestrator import handle_request

        get_default_store().add_grant(Grant(
            grant_id="g-scope",
            principal_id="user-s13",
            action_type="read",
            capability=None,
            scope_prefix="ctx-allowed-",
            is_active=True,
            issued_at=time.time(),
        ))
        # Matching context_id
        r_ok = handle_request(_req(
            principal_id="user-s13",
            context_id="ctx-allowed-abc",
        ))
        assert r_ok.get("result_type") != "denied"

        # Non-matching context_id
        r_denied = handle_request(_req(
            principal_id="user-s13",
            context_id="ctx-blocked-abc",
        ))
        assert r_denied["error"]["type"] == "grant_denied"


# ===========================================================================
# Regression guard — Sprint 9–12 tests are not broken
# ===========================================================================

class TestBackwardCompatibilityRegression:
    """
    Minimal regression suite ensuring Sprint 9–12 behaviors survive S13.
    These run with an empty default grant store (autouse fixture).
    """

    def test_active_allow_read_still_approved(self):
        """Sprint 10 core: active + allow + read → APPROVED (no grant store)."""
        from assistant_os.policy.policy_models import PolicyOutcome
        from assistant_os.policy.policy_engine import evaluate_policy
        from assistant_os.policy.policy_models import PolicyContext
        d = evaluate_policy(PolicyContext(
            subject_state="active", guard_decision="allow", action_type="read",
        ))
        assert d.outcome == PolicyOutcome.APPROVED

    def test_suspended_still_denied_subject_state(self):
        """Sprint 10: suspended → SUBJECT_STATE_BLOCKED regardless of grants."""
        from assistant_os.policy.policy_models import PolicyReason
        from assistant_os.policy.policy_engine import evaluate_policy
        from assistant_os.policy.policy_models import PolicyContext
        d = evaluate_policy(PolicyContext(
            subject_state="suspended", guard_decision="allow", action_type="read",
        ))
        assert d.reason == PolicyReason.SUBJECT_STATE_BLOCKED

    def test_quarantined_execute_still_capability_denied(self):
        """Sprint 9/10: quarantined + execute → CAPABILITY_DENIED."""
        from assistant_os.policy.policy_models import PolicyReason
        from assistant_os.policy.policy_engine import evaluate_policy
        from assistant_os.policy.policy_models import PolicyContext
        d = evaluate_policy(PolicyContext(
            subject_state="quarantined", guard_decision="allow", action_type="execute",
        ))
        assert d.reason == PolicyReason.CAPABILITY_DENIED

    def test_token_still_issued_after_approved_no_grants(self):
        """Sprint 12: APPROVED → token registered in registry."""
        from assistant_os.capabilities.token_issuer import _token_registry
        from assistant_os.core.orchestrator import handle_request
        before = len(_token_registry)
        handle_request(_req("active", "allow", "read"))
        assert len(_token_registry) > before

    def test_orchestrator_still_denies_guard_deny(self):
        """Sprint 10: guard_decision=deny → access_denied, no grant check."""
        from assistant_os.core.orchestrator import handle_request
        result = handle_request(_req("active", "deny", "read"))
        assert result["error"]["type"] == "access_denied"
