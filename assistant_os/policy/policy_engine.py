"""
Policy Engine — Sprint 10.

Single deterministic entry point for all authorization decisions in the
orchestrator pipeline.

Design
------
evaluate_policy(context: PolicyContext) → PolicyDecision

This function subsumes the three separate authorization checks that
previously lived inline in the orchestrator:
  1. F3: identity guard DENY check
  2. F3: DEGRADED + write-operation block
  3. S9: Capability Gate

Evaluation order (fixed, documented, tested)
--------------------------------------------
  1. subject_state hard stop
     Suspended and Terminated subjects are denied immediately.
     Reason: these states carry a permanent block that precedes all other checks.

  2. guard_decision hard stop
     guard_decision == "deny" blocks immediately.
     This covers: Quarantined × EXECUTE/NETWORK/POLICY (which the policy
     table maps to DENY, not DEGRADED).
     Reason: the guard has already computed the decision; we read, not re-decide.

  3. Required capability from action_type
     required_capability(action_type) → Optional[Capability]
     Determines which MO capability (if any) the action_type requires.
     READ and unknown action types return None → no capability check needed.

  4. Capability evaluation
     evaluate_capability(subject_state, capability) → bool
     If the required capability is not permitted for the subject state → DENIED.
     This fires even when guard_decision == "allow" (e.g., when tests inject
     allow directly to isolate the capability layer).

  5. Grant lookup  [Sprint 13]
     find_applicable_grant(GrantQuery) → Grant | None
     Enforced only when a non-empty grant store is provided.
     No applicable grant → DENIED(NO_APPLICABLE_GRANT).
     Grant found → proceed.
     Empty/absent store → skip (permissive fallback for pre-S13 callers).

  6. DEGRADED path — quarantined subject, guard passed, capability passed,
     grant found (or check not active):
     guard_decision == "degraded" AND action_type is write-like:
       → NEEDS_CONSENT  (blocked; could be unblocked by consent flow)
     guard_decision == "degraded" AND action_type is NOT write-like:
       → QUARANTINED    (permitted; proceeds with restrictions)

  7. Approved
     All checks passed → APPROVED, permitted=True.

Non-negotiable properties
--------------------------
- Pure function: same inputs → same output, always.
- No side effects: no logging, no I/O, no mutation.
- No LLM involvement.
- Fail-closed: unknown subject_state → no capabilities → may still pass
  capability check (capability=None for unknown action) but suspended/terminated
  are caught at step 1.
- Does not duplicate ActionType, GuardDecision, or Capability definitions.

Relationship to existing modules
---------------------------------
- policy_engine.py (legacy): holds ActionType, infer_action_type, GuardDecision-based
  evaluate_policy — that function is called from identity_guard.identity_guard().
  THIS engine is separate: it receives already-resolved strings on PolicyContext
  and returns PolicyDecision, not GuardDecision.
- identity_guard.py: build_guarded_request() stamps guard_decision, action_type,
  subject_state onto the CanonicalRequest before the orchestrator reads them.
- capabilities/capability_gate.py: required_capability() and evaluate_capability()
  are imported lazily here (at call time) to avoid circular imports at load time.
"""

from __future__ import annotations

from .policy_models import PolicyContext, PolicyDecision, PolicyOutcome, PolicyReason


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Subject states that block all operations unconditionally (step 1 hard stop).
_TERMINAL_STATES: frozenset[str] = frozenset({"suspended", "terminated"})

# action_type values that count as "write-like" for the DEGRADED path (step 5).
# These are the ActionType.value strings that mutate state or call external systems.
_WRITE_LIKE_ACTIONS: frozenset[str] = frozenset({"write", "execute", "network", "policy"})


# ---------------------------------------------------------------------------
# evaluate_policy
# ---------------------------------------------------------------------------

def evaluate_policy(
    context: PolicyContext,
    grant_store: "InMemoryGrantStore | None" = None,  # type: ignore[name-defined]
) -> PolicyDecision:
    """
    Evaluate the unified policy and return a deterministic PolicyDecision.

    Evaluation order is fixed (see module docstring, updated for S13):
      1. subject_state hard stop
      2. guard_decision hard stop
      3. required_capability(action_type)
      4. capability evaluation
      5. grant lookup            ← new in Sprint 13
      6. DEGRADED path
      7. APPROVED

    The function is pure given its inputs (same context + same grant_store
    state → same output).  No side effects, no I/O, no randomness, no LLM.

    Parameters
    ----------
    context     : PolicyContext — snapshot of subject_state, guard_decision,
                  action_type, principal_id, and operation_key for this request.
    grant_store : Optional InMemoryGrantStore — when provided and non-empty,
                  step 5 (grant lookup) is enforced: no grant → DENIED.
                  When None or empty, the grant check is skipped (permissive
                  fallback for Sprint 9–12 callers and legacy code).

    Returns
    -------
    PolicyDecision — always returned, never raises.
    """

    # ── Step 1: subject_state hard stop ───────────────────────────────────
    # Suspended and Terminated subjects are denied before any other check.
    # These states represent permanent lifecycle blocks.
    if context.subject_state in _TERMINAL_STATES:
        return PolicyDecision(
            outcome=PolicyOutcome.DENIED,
            reason=PolicyReason.SUBJECT_STATE_BLOCKED,
            detail=(
                f"Subject state '{context.subject_state}' blocks all operations. "
                "No actions are permitted until the session is released."
            ),
            permitted=False,
        )

    # ── Step 2: guard_decision hard stop ──────────────────────────────────
    # guard_decision == "deny" was computed upstream by build_guarded_request()
    # (→ identity_guard → policy_engine.evaluate_policy → GuardDecision.DENY).
    # We read the already-computed decision; we do not re-evaluate.
    if context.guard_decision == "deny":
        return PolicyDecision(
            outcome=PolicyOutcome.DENIED,
            reason=PolicyReason.GUARD_DENIED,
            detail=(
                "Identity guard denied this request. "
                f"Subject state: '{context.subject_state}'."
            ),
            permitted=False,
        )

    # ── Step 3: required capability from action_type ───────────────────────
    # Import lazily to avoid circular import at module load time.
    from ..capabilities.capability_gate import (
        evaluate_capability,
        required_capability,
    )
    cap = required_capability(context.action_type)

    # ── Step 4: capability evaluation ─────────────────────────────────────
    # If action_type maps to a specific MO capability, the subject's state
    # must permit that capability.  Fail-closed: unknown state → False.
    if cap is not None and not evaluate_capability(context.subject_state, cap):
        return PolicyDecision(
            outcome=PolicyOutcome.DENIED,
            reason=PolicyReason.CAPABILITY_DENIED,
            detail=(
                f"Capability '{cap.value}' is not permitted "
                f"for subject state '{context.subject_state}'."
            ),
            permitted=False,
        )

    # ── Step 5: Grant lookup ──────────────────────────────────────────────
    # Enforced only when a non-empty grant store is provided.
    # An empty or absent store is treated as permissive (backward-compat).
    #
    # Rule: capability valid + no applicable grant → DENIED(NO_APPLICABLE_GRANT)
    #        capability valid + grant found        → proceed to step 6/7
    #
    # The grant query uses the same cap resolved in step 3 so that grant
    # records must agree with the capability required for the action_type.
    if grant_store is not None and grant_store.has_grants():
        from ..grants.grant_models import GrantQuery
        _grant_query = GrantQuery(
            principal_id=context.principal_id,
            action_type=context.action_type,
            capability=cap.value if cap is not None else None,
            operation_key=context.operation_key,
        )
        if grant_store.find_applicable_grant(_grant_query) is None:
            return PolicyDecision(
                outcome=PolicyOutcome.DENIED,
                reason=PolicyReason.NO_APPLICABLE_GRANT,
                detail=(
                    f"No applicable grant for principal '{context.principal_id}' "
                    f"with action_type='{context.action_type}' "
                    f"capability='{cap.value if cap is not None else None}'."
                ),
                permitted=False,
            )

    # ── Step 6: DEGRADED path ─────────────────────────────────────────────
    # guard_decision == "degraded" means the subject is Quarantined and the
    # abstract guard did NOT hard-deny (i.e., action_type is READ or WRITE at
    # the GuardDecision level — EXECUTE/NETWORK/POLICY are DENY, caught above).
    #
    # Within DEGRADED, further distinguish by action_type:
    #   Write-like → NEEDS_CONSENT (blocked; explicit consent required)
    #   Read-like  → QUARANTINED   (permitted; restricted mode)
    if context.guard_decision == "degraded":
        if context.action_type in _WRITE_LIKE_ACTIONS:
            return PolicyDecision(
                outcome=PolicyOutcome.NEEDS_CONSENT,
                reason=PolicyReason.WRITE_IN_QUARANTINE,
                detail=(
                    f"Action '{context.action_type}' requires consent "
                    "while subject is in quarantine (read-only mode)."
                ),
                permitted=False,
            )
        # Read-type (or unknown action_type) in DEGRADED → proceed with restriction
        return PolicyDecision(
            outcome=PolicyOutcome.QUARANTINED,
            reason=PolicyReason.APPROVED,
            detail=(
                "Subject is quarantined; read access is permitted "
                "in restricted mode."
            ),
            permitted=True,
        )

    # ── Step 6: Approved ──────────────────────────────────────────────────
    # All checks passed.
    return PolicyDecision(
        outcome=PolicyOutcome.APPROVED,
        reason=PolicyReason.APPROVED,
        detail="All policy checks passed.",
        permitted=True,
    )
