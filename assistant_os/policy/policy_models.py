"""
Policy models — Sprint 10.

Data types for the unified Policy Engine.  No logic here — only types.

Relationship to existing types
-------------------------------
- ActionType lives in policy_engine.py (legacy module) and is NOT duplicated here.
  evaluate_policy() receives action_type as a plain string matching ActionType.value.
- GuardDecision lives in identity_guard.py and is NOT duplicated here.
  guard_decision arrives on PolicyContext as a plain string matching GuardDecision.value.
- Capability lives in capabilities/capability_gate.py and is NOT duplicated here.
  The policy engine imports it at call time to avoid circular imports.

PolicyOutcome
-------------
  APPROVED      — all checks passed; execution may proceed.
  DENIED        — hard stop; do not execute.
  NEEDS_CONSENT — subject is quarantined and action is write-type; blocked
                  but not a permanent hard stop (could be unblocked by consent).
  QUARANTINED   — subject is quarantined and action is read-type; execution
                  proceeds with restrictions.

PolicyReason
------------
  Typed enumeration of why a particular outcome was reached.  One value per
  evaluation-order step so the reason is unambiguous:

    APPROVED              — all checks passed (used for any permitted outcome)
    SUBJECT_STATE_BLOCKED — step 1: state is suspended or terminated
    GUARD_DENIED          — step 2: guard_decision == "deny"
    CAPABILITY_DENIED     — step 4: required capability not in subject's matrix
    WRITE_IN_QUARANTINE   — step 5: degraded session attempting a write-type action

PolicyContext
-------------
  Immutable snapshot of the authorization inputs available at orchestrator
  time.  Built from the CanonicalRequest fields stamped by build_guarded_request().

PolicyDecision
--------------
  Immutable result of evaluate_policy().  `permitted` is the gate field:
  True → proceed, False → return a denied DomainResult.

  `error_type` is a derived property that maps reason → the string to put in
  DomainResult error.type.  Backward-compatible with the error types the
  existing orchestrator/tests expect.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# PolicyOutcome
# ---------------------------------------------------------------------------

class PolicyOutcome(str, Enum):
    """Terminal outcome of a policy evaluation."""

    APPROVED      = "approved"
    DENIED        = "denied"
    NEEDS_CONSENT = "needs_consent"
    QUARANTINED   = "quarantined"


# ---------------------------------------------------------------------------
# PolicyReason
# ---------------------------------------------------------------------------

class PolicyReason(str, Enum):
    """
    Typed reason for the PolicyDecision.

    One value per evaluation-order step so that:
    - The reason is machine-readable (enum, not a free string).
    - Callers can branch on reason without parsing text.
    - Audit logs carry a stable, versioned token.
    """

    APPROVED              = "approved"
    SUBJECT_STATE_BLOCKED = "subject_state_blocked"
    GUARD_DENIED          = "guard_denied"
    CAPABILITY_DENIED     = "capability_denied"
    NO_APPLICABLE_GRANT   = "no_applicable_grant"   # S13: grant check
    WRITE_IN_QUARANTINE   = "write_in_quarantine"


# ---------------------------------------------------------------------------
# PolicyContext
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PolicyContext:
    """
    Immutable snapshot of authorization inputs for a single request.

    All fields are plain strings so the engine has zero coupling to the
    enum types in the layers above it.  Callers pass `.value` of enums.

    Fields
    ------
    subject_state  : SubjectState.value — lifecycle state of the subject.
                     e.g. "active", "quarantined", "suspended", "terminated".
    guard_decision : GuardDecision.value — result already stamped on the request
                     by build_guarded_request().  e.g. "allow", "deny", "degraded".
                     Empty string ("") for legacy callers without guard context.
    action_type    : ActionType.value — abstract operation class stamped on the
                     request by build_guarded_request().
                     e.g. "read", "write", "execute", "network", "policy".
                     Empty string ("") when action type is unknown (NL or legacy).
    principal_id   : Identifier of the acting principal.  Used by the grant
                     check (S13) to find an applicable grant.
                     Empty string ("") for legacy callers without principal context.
    operation_key  : Unique per-request identifier used for grant scope matching.
                     Set to context_id by the orchestrator.
                     Empty string ("") for direct callers / legacy callers;
                     grants with scope_prefix="" match empty operation_key.
    """

    subject_state:  str
    guard_decision: str
    action_type:    str
    principal_id:   str = ""
    operation_key:  str = ""


# ---------------------------------------------------------------------------
# PolicyDecision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PolicyDecision:
    """
    Immutable result of evaluate_policy().

    Fields
    ------
    outcome   : PolicyOutcome — semantic category of the decision.
    reason    : PolicyReason  — which evaluation step drove the outcome.
    detail    : str           — human-readable explanation (non-empty, for logs/UI).
    permitted : bool          — gate field: True → proceed, False → deny.

    Properties
    ----------
    error_type : str — maps reason to the error.type string expected by the
                       orchestrator and callers.  Empty string when permitted=True.
    """

    outcome:   PolicyOutcome
    reason:    PolicyReason
    detail:    str
    permitted: bool

    @property
    def error_type(self) -> str:
        """
        Canonical error.type string for DomainResult.error when permitted=False.

        Backward-compatible with the error types produced by the three separate
        checks this engine replaces in the orchestrator:
          - guard DENY / subject state block  → "access_denied"
          - capability check failure          → "capability_denied"
          - DEGRADED write block              → "write_blocked"
          - permitted outcome                 → ""
        """
        if self.reason == PolicyReason.CAPABILITY_DENIED:
            return "capability_denied"
        if self.reason == PolicyReason.NO_APPLICABLE_GRANT:
            return "grant_denied"
        if self.reason == PolicyReason.WRITE_IN_QUARANTINE:
            return "write_blocked"
        if self.reason == PolicyReason.APPROVED:
            return ""
        # SUBJECT_STATE_BLOCKED, GUARD_DENIED, or any future reason
        return "access_denied"
