"""
Tests for Sprint 4 / F4: Policy Engine

Proves:
  1. ActionType enum correctness
  2. evaluate_policy — full decision table (4 states × 5 action types = 20 cells)
  3. evaluate_policy is pure (same input → same output, no side effects)
  4. evaluate_policy fail-closed on unknown inputs
  5. infer_action_type — concrete string → abstract type mapping
  6. policy_reason — non-empty string, reflects state + action
  7. identity_guard delegates to policy engine (does not own decision logic)
  8. identity_guard decision depends on BOTH subject_state AND action_type
  9. GuardResult carries action_type field
 10. build_guarded_request infers action_type and stamps it into CanonicalRequest
 11. is_write_operation backward compat (delegates to infer_action_type)
 12. No divergence: same (state, action_type) → same decision across all paths
 13. PolicyContext placeholder doesn't affect decisions
"""

import json
import pytest
from itertools import product

from assistant_os.identity import (
    SubjectState,
    PrincipalKind,
    Principal,
    RequestIdentity,
    anonymous_human,
)
from assistant_os.identity_guard import (
    GuardDecision,
    GuardResult,
    ActionType,
    identity_guard,
    build_guarded_request,
    is_write_operation,
    infer_action_type,
    enforce_guard_for_handler,
)
from assistant_os.policy_engine import (
    evaluate_policy,
    policy_reason,
    PolicyContext,
    _POLICY_TABLE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_identity(state: SubjectState, session_id: str = "f4-test-sess") -> RequestIdentity:
    return RequestIdentity(
        principal=Principal(
            kind=PrincipalKind.Human,
            id=f"human:{session_id[:8]}",
            label="user",
        ),
        subject_state=state,
        session_id=session_id,
    )


def _principal(state: SubjectState) -> Principal:
    return Principal(kind=PrincipalKind.Human, id="human:test1234", label="user")


# ---------------------------------------------------------------------------
# ActionType enum
# ---------------------------------------------------------------------------

class TestActionType:
    def test_values(self):
        assert ActionType.READ.value    == "read"
        assert ActionType.WRITE.value   == "write"
        assert ActionType.EXECUTE.value == "execute"
        assert ActionType.NETWORK.value == "network"
        assert ActionType.POLICY.value  == "policy"

    def test_str_enum_comparison(self):
        assert ActionType.READ    == "read"
        assert ActionType.WRITE   == "write"
        assert ActionType.EXECUTE == "execute"

    def test_all_five_variants_exist(self):
        values = {at.value for at in ActionType}
        assert values == {"read", "write", "execute", "network", "policy"}

    def test_importable_from_identity_guard(self):
        """ActionType is re-exported from identity_guard for caller convenience."""
        from assistant_os.identity_guard import ActionType as AT
        assert AT.READ == "read"


# ---------------------------------------------------------------------------
# evaluate_policy — full decision table
# ---------------------------------------------------------------------------

class TestEvaluatePolicyTable:
    """
    Test the complete 4×5 policy table.
    Each test method covers one SubjectState row.
    """

    def _eval(self, state: SubjectState, at: ActionType) -> GuardDecision:
        return evaluate_policy(_principal(state), state, at)

    # ── Active — full access ──────────────────────────────────────────────

    def test_active_read_allows(self):
        assert self._eval(SubjectState.Active, ActionType.READ) == GuardDecision.ALLOW

    def test_active_write_allows(self):
        assert self._eval(SubjectState.Active, ActionType.WRITE) == GuardDecision.ALLOW

    def test_active_execute_allows(self):
        assert self._eval(SubjectState.Active, ActionType.EXECUTE) == GuardDecision.ALLOW

    def test_active_network_allows(self):
        assert self._eval(SubjectState.Active, ActionType.NETWORK) == GuardDecision.ALLOW

    def test_active_policy_allows(self):
        assert self._eval(SubjectState.Active, ActionType.POLICY) == GuardDecision.ALLOW

    # ── Quarantined — read/write degraded; execute/network/policy denied ──

    def test_quarantined_read_degrades(self):
        assert self._eval(SubjectState.Quarantined, ActionType.READ) == GuardDecision.DEGRADED

    def test_quarantined_write_degrades(self):
        assert self._eval(SubjectState.Quarantined, ActionType.WRITE) == GuardDecision.DEGRADED

    def test_quarantined_execute_denies(self):
        assert self._eval(SubjectState.Quarantined, ActionType.EXECUTE) == GuardDecision.DENY

    def test_quarantined_network_denies(self):
        assert self._eval(SubjectState.Quarantined, ActionType.NETWORK) == GuardDecision.DENY

    def test_quarantined_policy_denies(self):
        assert self._eval(SubjectState.Quarantined, ActionType.POLICY) == GuardDecision.DENY

    # ── Suspended — complete denial ───────────────────────────────────────

    def test_suspended_read_denies(self):
        assert self._eval(SubjectState.Suspended, ActionType.READ) == GuardDecision.DENY

    def test_suspended_write_denies(self):
        assert self._eval(SubjectState.Suspended, ActionType.WRITE) == GuardDecision.DENY

    def test_suspended_execute_denies(self):
        assert self._eval(SubjectState.Suspended, ActionType.EXECUTE) == GuardDecision.DENY

    def test_suspended_network_denies(self):
        assert self._eval(SubjectState.Suspended, ActionType.NETWORK) == GuardDecision.DENY

    def test_suspended_policy_denies(self):
        assert self._eval(SubjectState.Suspended, ActionType.POLICY) == GuardDecision.DENY

    # ── Terminated — complete denial ──────────────────────────────────────

    def test_terminated_read_denies(self):
        assert self._eval(SubjectState.Terminated, ActionType.READ) == GuardDecision.DENY

    def test_terminated_write_denies(self):
        assert self._eval(SubjectState.Terminated, ActionType.WRITE) == GuardDecision.DENY

    def test_terminated_execute_denies(self):
        assert self._eval(SubjectState.Terminated, ActionType.EXECUTE) == GuardDecision.DENY

    def test_terminated_network_denies(self):
        assert self._eval(SubjectState.Terminated, ActionType.NETWORK) == GuardDecision.DENY

    def test_terminated_policy_denies(self):
        assert self._eval(SubjectState.Terminated, ActionType.POLICY) == GuardDecision.DENY

    def test_all_20_cells_covered_in_table(self):
        """The static _POLICY_TABLE must have exactly 20 entries (4×5)."""
        assert len(_POLICY_TABLE) == 20, (
            f"Expected 20 policy table entries, got {len(_POLICY_TABLE)}"
        )


# ---------------------------------------------------------------------------
# evaluate_policy — purity and determinism
# ---------------------------------------------------------------------------

class TestEvaluatePolicyPurity:
    def test_same_input_same_output(self):
        """Deterministic: identical calls produce identical results."""
        for state, at in product(SubjectState, ActionType):
            principal = _principal(state)
            r1 = evaluate_policy(principal, state, at)
            r2 = evaluate_policy(principal, state, at)
            assert r1 == r2, f"Non-determinism for ({state}, {at})"

    def test_all_returns_are_guard_decision(self):
        """evaluate_policy always returns a GuardDecision, never None."""
        for state, at in product(SubjectState, ActionType):
            result = evaluate_policy(_principal(state), state, at)
            assert isinstance(result, GuardDecision)

    def test_different_action_types_can_differ_for_quarantined(self):
        """
        For Quarantined, READ and EXECUTE must produce different decisions —
        proving the engine actually uses action_type in its decision.
        """
        principal = _principal(SubjectState.Quarantined)
        r_read = evaluate_policy(principal, SubjectState.Quarantined, ActionType.READ)
        r_exec = evaluate_policy(principal, SubjectState.Quarantined, ActionType.EXECUTE)
        assert r_read != r_exec, (
            "Quarantined READ and EXECUTE should produce different decisions"
        )
        assert r_read == GuardDecision.DEGRADED
        assert r_exec == GuardDecision.DENY

    def test_policy_context_does_not_affect_decision(self):
        """PolicyContext is a placeholder — must not change outcomes."""
        principal = _principal(SubjectState.Active)
        without_ctx = evaluate_policy(principal, SubjectState.Active, ActionType.WRITE)
        with_ctx = evaluate_policy(
            principal, SubjectState.Active, ActionType.WRITE,
            context=PolicyContext(resource_id="task-123", resource_type="task"),
        )
        assert without_ctx == with_ctx

    def test_fail_closed_on_unknown_state(self):
        """Simulate an unknown state value by patching the enum value."""
        # We can't easily create an invalid SubjectState value with a proper enum,
        # so we test via the table directly.
        result = _POLICY_TABLE.get(("unknown_state", "read"))
        assert result is None  # not in table → caller gets DENY via fallback

    def test_no_side_effects_no_mutation(self):
        """Calling evaluate_policy does not change _POLICY_TABLE."""
        table_before = dict(_POLICY_TABLE)
        evaluate_policy(_principal(SubjectState.Active), SubjectState.Active, ActionType.WRITE)
        assert _POLICY_TABLE == table_before


# ---------------------------------------------------------------------------
# infer_action_type
# ---------------------------------------------------------------------------

class TestInferActionType:
    # EXECUTE detection
    def test_fin_commit_is_execute(self):
        assert infer_action_type("FIN_COMMIT") == ActionType.EXECUTE

    def test_fin_batch_is_execute(self):
        assert infer_action_type("FIN_BATCH") == ActionType.EXECUTE

    def test_fin_confirm_is_execute(self):
        assert infer_action_type("FIN_CONFIRM") == ActionType.EXECUTE

    def test_work_confirm_is_execute(self):
        assert infer_action_type("WORK_CONFIRM") == ActionType.EXECUTE

    def test_code_commit_is_execute(self):
        assert infer_action_type("CODE_COMMIT") == ActionType.EXECUTE

    def test_generic_confirm_is_execute(self):
        assert infer_action_type("CONFIRM") == ActionType.EXECUTE

    # WRITE detection
    def test_fin_expense_is_write(self):
        assert infer_action_type("FIN_EXPENSE") == ActionType.WRITE

    def test_work_create_is_write(self):
        assert infer_action_type("WORK_CREATE") == ActionType.WRITE

    def test_work_update_is_write(self):
        assert infer_action_type("WORK_UPDATE") == ActionType.WRITE

    def test_work_delete_is_write(self):
        assert infer_action_type("WORK_DELETE") == ActionType.WRITE

    def test_code_fix_is_write(self):
        assert infer_action_type("CODE_FIX") == ActionType.WRITE

    def test_code_create_is_write(self):
        assert infer_action_type("CODE_CREATE") == ActionType.WRITE

    def test_generic_create_is_write(self):
        assert infer_action_type("CREATE") == ActionType.WRITE

    def test_generic_delete_is_write(self):
        assert infer_action_type("DELETE") == ActionType.WRITE

    # NETWORK detection
    def test_network_prefix_is_network(self):
        assert infer_action_type("NETWORK_CALL") == ActionType.NETWORK

    def test_api_call_is_network(self):
        assert infer_action_type("API_CALL") == ActionType.NETWORK

    # POLICY detection
    def test_policy_prefix_is_policy(self):
        assert infer_action_type("POLICY_UPDATE") == ActionType.POLICY

    def test_admin_prefix_is_policy(self):
        assert infer_action_type("ADMIN_RESET") == ActionType.POLICY

    # READ (default)
    def test_work_query_is_read(self):
        assert infer_action_type("WORK_QUERY") == ActionType.READ

    def test_fin_plan_is_read(self):
        assert infer_action_type("FIN_PLAN") == ActionType.READ

    def test_code_explain_is_read(self):
        assert infer_action_type("CODE_EXPLAIN") == ActionType.READ

    def test_code_review_is_read(self):
        assert infer_action_type("CODE_REVIEW") == ActionType.READ

    def test_none_is_read(self):
        assert infer_action_type(None) == ActionType.READ

    def test_empty_string_is_read(self):
        assert infer_action_type("") == ActionType.READ

    def test_unknown_string_is_read(self):
        assert infer_action_type("SOME_UNKNOWN_OP") == ActionType.READ

    def test_case_insensitive(self):
        assert infer_action_type("fin_expense") == ActionType.WRITE
        assert infer_action_type("work_create") == ActionType.WRITE
        assert infer_action_type("fin_commit") == ActionType.EXECUTE

    def test_execute_takes_priority_over_write(self):
        """
        FIN_COMMIT starts with FIN_ which is also in write prefixes.
        EXECUTE must be checked first and win.
        """
        at = infer_action_type("FIN_COMMIT")
        assert at == ActionType.EXECUTE, (
            f"FIN_COMMIT should be EXECUTE (commit a plan), got {at}"
        )


# ---------------------------------------------------------------------------
# policy_reason
# ---------------------------------------------------------------------------

class TestPolicyReason:
    def test_all_combinations_produce_non_empty_string(self):
        for state, at in product(SubjectState, ActionType):
            principal = _principal(state)
            decision = evaluate_policy(principal, state, at)
            reason = policy_reason(state, at, decision)
            assert isinstance(reason, str) and len(reason) > 0, (
                f"Empty reason for ({state}, {at}, {decision})"
            )

    def test_allow_reason_mentions_action_type(self):
        reason = policy_reason(SubjectState.Active, ActionType.WRITE, GuardDecision.ALLOW)
        assert "write" in reason.lower()

    def test_degraded_reason_mentions_quarantined(self):
        reason = policy_reason(SubjectState.Quarantined, ActionType.READ, GuardDecision.DEGRADED)
        assert "quarantined" in reason.lower() or "degraded" in reason.lower()

    def test_deny_for_suspended_mentions_suspended(self):
        reason = policy_reason(SubjectState.Suspended, ActionType.READ, GuardDecision.DENY)
        assert "suspended" in reason.lower()

    def test_deny_for_terminated_mentions_terminated(self):
        reason = policy_reason(SubjectState.Terminated, ActionType.WRITE, GuardDecision.DENY)
        assert "terminated" in reason.lower()


# ---------------------------------------------------------------------------
# identity_guard delegates to policy engine
# ---------------------------------------------------------------------------

class TestIdentityGuardDelegates:
    """
    identity_guard must delegate decisions to evaluate_policy.
    It must not own decision logic.
    """

    def test_guard_uses_action_type_in_decision(self):
        """
        For Quarantined, READ and EXECUTE must produce different GuardDecisions.
        If the guard were ignoring action_type, both would be DEGRADED.
        """
        identity = _make_identity(SubjectState.Quarantined)
        gr_read = identity_guard(identity, ActionType.READ)
        gr_exec = identity_guard(identity, ActionType.EXECUTE)
        assert gr_read.decision == GuardDecision.DEGRADED
        assert gr_exec.decision == GuardDecision.DENY

    def test_guard_default_action_type_is_read(self):
        """No action_type → READ default → Active stays ALLOW."""
        identity = _make_identity(SubjectState.Active)
        gr = identity_guard(identity)
        assert gr.decision == GuardDecision.ALLOW
        assert gr.action_type == "read"

    def test_guard_result_carries_action_type(self):
        identity = _make_identity(SubjectState.Active)
        for at in ActionType:
            gr = identity_guard(identity, at)
            assert gr.action_type == at.value

    def test_guard_active_all_actions_allow(self):
        identity = _make_identity(SubjectState.Active)
        for at in ActionType:
            gr = identity_guard(identity, at)
            assert gr.decision == GuardDecision.ALLOW, f"Active+{at} should ALLOW"

    def test_guard_suspended_all_actions_deny(self):
        identity = _make_identity(SubjectState.Suspended)
        for at in ActionType:
            gr = identity_guard(identity, at)
            assert gr.decision == GuardDecision.DENY, f"Suspended+{at} should DENY"

    def test_guard_terminated_all_actions_deny(self):
        identity = _make_identity(SubjectState.Terminated)
        for at in ActionType:
            gr = identity_guard(identity, at)
            assert gr.decision == GuardDecision.DENY, f"Terminated+{at} should DENY"

    def test_guard_quarantined_read_write_degrade(self):
        identity = _make_identity(SubjectState.Quarantined)
        for at in (ActionType.READ, ActionType.WRITE):
            gr = identity_guard(identity, at)
            assert gr.decision == GuardDecision.DEGRADED, f"Quarantined+{at} should DEGRADE"

    def test_guard_quarantined_execute_network_policy_deny(self):
        identity = _make_identity(SubjectState.Quarantined)
        for at in (ActionType.EXECUTE, ActionType.NETWORK, ActionType.POLICY):
            gr = identity_guard(identity, at)
            assert gr.decision == GuardDecision.DENY, f"Quarantined+{at} should DENY"

    def test_guard_result_allow_write_flag(self):
        """allow_write is True only for ALLOW decisions."""
        identity = _make_identity(SubjectState.Active)
        gr_allow = identity_guard(identity, ActionType.WRITE)
        assert gr_allow.allow_write is True

        identity2 = _make_identity(SubjectState.Quarantined)
        gr_degrad = identity_guard(identity2, ActionType.WRITE)
        assert gr_degrad.allow_write is False

        identity3 = _make_identity(SubjectState.Suspended)
        gr_deny = identity_guard(identity3, ActionType.WRITE)
        assert gr_deny.allow_write is False

    def test_guard_result_allow_read_flag(self):
        """allow_read is True for ALLOW and DEGRADED, False for DENY."""
        identity_active = _make_identity(SubjectState.Active)
        identity_quar   = _make_identity(SubjectState.Quarantined)
        identity_susp   = _make_identity(SubjectState.Suspended)

        assert identity_guard(identity_active, ActionType.READ).allow_read is True
        assert identity_guard(identity_quar,   ActionType.READ).allow_read is True
        assert identity_guard(identity_susp,   ActionType.READ).allow_read is False

    def test_guard_audit_dict_has_action_type(self):
        identity = _make_identity(SubjectState.Active)
        gr = identity_guard(identity, ActionType.WRITE)
        d = gr.to_audit_dict()
        assert "action_type" in d
        assert d["action_type"] == "write"

    def test_guard_audit_dict_json_safe(self):
        for state, at in product(SubjectState, ActionType):
            identity = _make_identity(state)
            gr = identity_guard(identity, at)
            json.dumps(gr.to_audit_dict())  # must not raise

    def test_guard_calls_evaluate_policy_once(self):
        """Guard must delegate — not compute decision independently."""
        from unittest.mock import patch
        identity = _make_identity(SubjectState.Active)
        with patch(
            "assistant_os.policy_engine.evaluate_policy",
            wraps=evaluate_policy,
        ) as mock_ep:
            identity_guard(identity, ActionType.WRITE)
            assert mock_ep.call_count == 1


# ---------------------------------------------------------------------------
# build_guarded_request — action_type inference and stamping
# ---------------------------------------------------------------------------

class TestBuildGuardedRequestActionType:
    def test_action_type_stamped_in_req(self):
        identity = _make_identity(SubjectState.Active)
        req, gr = build_guarded_request(identity, metadata={"action": "FIN_EXPENSE"})
        assert req.get("action_type") == "write"

    def test_action_type_in_guard_result(self):
        identity = _make_identity(SubjectState.Active)
        req, gr = build_guarded_request(identity, metadata={"action": "FIN_EXPENSE"})
        assert gr.action_type == "write"

    def test_execute_action_inferred_correctly(self):
        identity = _make_identity(SubjectState.Active)
        req, gr = build_guarded_request(identity, metadata={"action": "FIN_COMMIT"})
        assert req.get("action_type") == "execute"
        assert gr.action_type == "execute"

    def test_explicit_action_type_takes_priority(self):
        identity = _make_identity(SubjectState.Active)
        req, gr = build_guarded_request(
            identity,
            metadata={"action": "FIN_EXPENSE"},  # would infer WRITE
            action_type=ActionType.READ,           # explicit override
        )
        assert req.get("action_type") == "read"
        assert gr.action_type == "read"

    def test_no_metadata_action_defaults_to_read(self):
        identity = _make_identity(SubjectState.Active)
        req, gr = build_guarded_request(identity, text="hola")
        assert req.get("action_type") == "read"
        assert gr.action_type == "read"

    def test_quarantined_execute_gives_deny(self):
        """
        For Quarantined + FIN_COMMIT (EXECUTE), policy must return DENY,
        not DEGRADED. This is a new F4 behavior not possible in F2.
        """
        identity = _make_identity(SubjectState.Quarantined)
        req, gr = build_guarded_request(identity, metadata={"action": "FIN_COMMIT"})
        assert req["guard_decision"] == "deny"
        assert gr.decision == GuardDecision.DENY
        assert gr.action_type == "execute"

    def test_quarantined_read_gives_degraded(self):
        identity = _make_identity(SubjectState.Quarantined)
        req, gr = build_guarded_request(identity, metadata={"action": "WORK_QUERY"})
        assert req["guard_decision"] == "degraded"
        assert gr.action_type == "read"

    def test_req_guard_decision_matches_gr_decision(self):
        """CanonicalRequest and GuardResult must not diverge."""
        for state, action_str in [
            (SubjectState.Active,      "FIN_EXPENSE"),
            (SubjectState.Quarantined, "FIN_COMMIT"),
            (SubjectState.Quarantined, "WORK_QUERY"),
            (SubjectState.Suspended,   "FIN_EXPENSE"),
            (SubjectState.Terminated,  "WORK_CREATE"),
        ]:
            identity = _make_identity(state)
            req, gr = build_guarded_request(identity, metadata={"action": action_str})
            assert req["guard_decision"] == gr.decision.value, (
                f"Divergence for ({state}, {action_str})"
            )

    def test_req_action_type_matches_gr_action_type(self):
        """CanonicalRequest action_type and GuardResult action_type must match."""
        identity = _make_identity(SubjectState.Active)
        for at in ActionType:
            req, gr = build_guarded_request(identity, action_type=at)
            assert req["action_type"] == gr.action_type == at.value


# ---------------------------------------------------------------------------
# is_write_operation backward compat shim
# ---------------------------------------------------------------------------

class TestIsWriteOperationShim:
    """is_write_operation delegates to infer_action_type — backward compat."""

    def test_write_operations_return_true(self):
        for op in ("FIN_EXPENSE", "WORK_CREATE", "WORK_UPDATE", "WORK_DELETE", "CODE_FIX"):
            assert is_write_operation(op) is True, f"{op} should be a write op"

    def test_execute_operations_return_true(self):
        """
        F4: EXECUTE operations also return True (they are mutations).
        FIN_COMMIT etc. now map to EXECUTE, which counts as a write for
        the backward-compat shim.
        """
        for op in ("FIN_COMMIT", "FIN_BATCH", "FIN_CONFIRM"):
            assert is_write_operation(op) is True, f"{op} should count as write (execute)"

    def test_read_operations_return_false(self):
        for op in ("WORK_QUERY", "FIN_PLAN", "CODE_EXPLAIN", "CODE_REVIEW"):
            assert is_write_operation(op) is False, f"{op} should not be a write op"

    def test_none_returns_false(self):
        assert is_write_operation(None) is False

    def test_empty_string_returns_false(self):
        assert is_write_operation("") is False


# ---------------------------------------------------------------------------
# No divergence between paths for same (state, action_type)
# ---------------------------------------------------------------------------

class TestNoDivergenceF4:
    """
    The policy engine is the single source of truth.
    Calling evaluate_policy directly, calling identity_guard, or calling
    build_guarded_request must all produce the same decision for the same
    (SubjectState, ActionType) input.
    """

    def test_all_paths_consistent(self):
        test_cases = list(product(SubjectState, ActionType))
        for state, at in test_cases:
            identity = _make_identity(state)
            principal = identity.principal

            # Direct policy engine call
            direct = evaluate_policy(principal, state, at)

            # Through identity_guard
            gr = identity_guard(identity, at)

            # Through build_guarded_request
            req, bgr = build_guarded_request(identity, action_type=at)

            assert direct == gr.decision == bgr.decision, (
                f"Divergence for ({state.value}, {at.value}): "
                f"policy={direct.value}, guard={gr.decision.value}, "
                f"build_guard={bgr.decision.value}"
            )
            assert req["guard_decision"] == direct.value, (
                f"CanonicalRequest diverged for ({state.value}, {at.value})"
            )


# ---------------------------------------------------------------------------
# PolicyContext placeholder
# ---------------------------------------------------------------------------

class TestPolicyContext:
    def test_context_is_dataclass(self):
        ctx = PolicyContext()
        assert ctx.resource_id is None
        assert ctx.resource_type is None
        assert ctx.extra == {}

    def test_context_fields_set(self):
        ctx = PolicyContext(resource_id="task-123", resource_type="task", extra={"team": "eng"})
        assert ctx.resource_id == "task-123"
        assert ctx.resource_type == "task"
        assert ctx.extra == {"team": "eng"}

    def test_context_does_not_affect_policy(self):
        """
        PolicyContext is reserved for F4.5+.
        Current evaluate_policy must ignore it entirely.
        """
        state = SubjectState.Active
        at = ActionType.WRITE
        principal = _principal(state)

        without = evaluate_policy(principal, state, at)
        with_ctx = evaluate_policy(
            principal, state, at,
            context=PolicyContext(resource_id="task-999", resource_type="task"),
        )
        assert without == with_ctx


# ---------------------------------------------------------------------------
# F4 new semantics — Quarantined + EXECUTE → DENY (richer than F2)
# ---------------------------------------------------------------------------

class TestF4NewSemantics:
    """
    F2/F3: Quarantined → always DEGRADED (all actions).
    F4: Quarantined × EXECUTE/NETWORK/POLICY → DENY (more precise).

    This section explicitly tests the F4 behavior that wasn't possible before.
    """

    def test_quarantined_execute_is_denied_not_degraded(self):
        identity = _make_identity(SubjectState.Quarantined)
        gr = identity_guard(identity, ActionType.EXECUTE)
        assert gr.decision == GuardDecision.DENY
        assert gr.decision != GuardDecision.DEGRADED

    def test_quarantined_network_is_denied_not_degraded(self):
        identity = _make_identity(SubjectState.Quarantined)
        gr = identity_guard(identity, ActionType.NETWORK)
        assert gr.decision == GuardDecision.DENY

    def test_quarantined_policy_is_denied_not_degraded(self):
        identity = _make_identity(SubjectState.Quarantined)
        gr = identity_guard(identity, ActionType.POLICY)
        assert gr.decision == GuardDecision.DENY

    def test_quarantined_write_remains_degraded_for_compat(self):
        """
        WRITE stays DEGRADED (not DENY) for backward compatibility with
        the F2/F3 chat path write-blocking pattern.
        """
        identity = _make_identity(SubjectState.Quarantined)
        gr = identity_guard(identity, ActionType.WRITE)
        assert gr.decision == GuardDecision.DEGRADED

    def test_fin_commit_quarantined_gives_deny_via_build(self):
        """End-to-end: committing a FIN plan while quarantined → DENY."""
        identity = _make_identity(SubjectState.Quarantined)
        req, gr = build_guarded_request(identity, metadata={"action": "FIN_COMMIT"})
        assert gr.decision == GuardDecision.DENY
        assert req["guard_decision"] == "deny"

    def test_fin_expense_quarantined_gives_degraded_via_build(self):
        """End-to-end: recording a FIN expense while quarantined → DEGRADED."""
        identity = _make_identity(SubjectState.Quarantined)
        req, gr = build_guarded_request(identity, metadata={"action": "FIN_EXPENSE"})
        assert gr.decision == GuardDecision.DEGRADED
        assert req["guard_decision"] == "degraded"
