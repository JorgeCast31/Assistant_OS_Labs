"""
AssistantOS — Identity Guard (F2/F3/F4)

The guard evaluates a RequestIdentity against the Policy Engine and returns
a GuardResult (ALLOW / DENY / DEGRADED) before any domain routing executes.

F4 change: identity_guard now delegates decision-making to the Policy Engine
(policy_engine.evaluate_policy).  The guard itself is responsible only for:
  - extracting the subject's state and the operation's ActionType
  - calling evaluate_policy (once, deterministically)
  - building the GuardResult envelope
  - surfacing the result for callers

The guard is still the single enforcement entry point.  The Policy Engine is
the single source of access decisions.

Design notes
------------
- identity_guard() is pure: no side effects, no I/O.  Logging happens outside.
- DEGRADED means partial access: reads allowed, writes blocked downstream.
- DENY means total block: the caller must reject before processing anything.
- The guard never raises: errors are returned as DENY.
- build_guarded_request() is the F3 canonical construction point; it now
  includes ActionType so the policy engine sees the full picture.
- is_write_operation() is kept as a backward-compat shim; it delegates to
  infer_action_type() from the policy engine.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .identity import RequestIdentity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GuardDecision
# ---------------------------------------------------------------------------

class GuardDecision(str, Enum):
    """
    Outcome of the policy evaluation for a single request.

    Variants:
        ALLOW    — Full access granted.
        DENY     — Request rejected entirely.  Caller must return HTTP 403
                   or equivalent without processing any domain logic.
        DEGRADED — Partial access.  Read operations are permitted; write /
                   execute operations are blocked at enforcement sites.
    """
    ALLOW    = "allow"
    DENY     = "deny"
    DEGRADED = "degraded"

    def is_allowed(self) -> bool:
        """True when the request may proceed (ALLOW or DEGRADED)."""
        return self in (GuardDecision.ALLOW, GuardDecision.DEGRADED)

    def is_full_access(self) -> bool:
        """True only when full write access is granted."""
        return self == GuardDecision.ALLOW

    def blocks_all(self) -> bool:
        """True when the request must be rejected entirely."""
        return self == GuardDecision.DENY


# ---------------------------------------------------------------------------
# GuardResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GuardResult:
    """
    Immutable result from the identity guard / policy engine evaluation.

    F4 addition: action_type field records which ActionType was evaluated,
    providing a richer audit trail (the decision now depends on both
    subject_state AND action_type).

    Fields:
        decision        — GuardDecision (ALLOW / DENY / DEGRADED)
        reason          — Human-readable justification for the decision.
        subject_state   — SubjectState.value that drove the decision.
        principal_id    — principal.id from the evaluated identity.
        action_type     — ActionType.value that was evaluated (F4).
        evaluated_at    — UTC ISO-8601 timestamp of evaluation.
        allow_read      — True when read operations are permitted.
        allow_write     — True when write/mutating operations are permitted.
    """
    decision:      GuardDecision
    reason:        str
    subject_state: str                        # SubjectState.value (str for JSON safety)
    principal_id:  str
    action_type:   str = "read"               # ActionType.value (F4; default "read")
    evaluated_at:  str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    allow_read:    bool = True
    allow_write:   bool = True

    # ── Convenience pass-throughs ──────────────────────────────────────────

    def is_allowed(self) -> bool:
        return self.decision.is_allowed()

    def is_full_access(self) -> bool:
        return self.decision.is_full_access()

    def blocks_all(self) -> bool:
        return self.decision.blocks_all()

    # ── Serialization ──────────────────────────────────────────────────────

    def to_audit_dict(self) -> dict:
        """Serialize for audit log / response metadata inclusion."""
        return {
            "decision":      self.decision.value,
            "reason":        self.reason,
            "subject_state": self.subject_state,
            "principal_id":  self.principal_id,
            "action_type":   self.action_type,
            "evaluated_at":  self.evaluated_at,
            "allow_read":    self.allow_read,
            "allow_write":   self.allow_write,
        }


# ---------------------------------------------------------------------------
# GuardResult construction helper
# ---------------------------------------------------------------------------

def _build_result(
    identity: "RequestIdentity",
    decision: GuardDecision,
    action_type_val: str,
    reason: str,
) -> GuardResult:
    """Build a GuardResult from a decision + identity, without external deps."""
    allow_read  = decision in (GuardDecision.ALLOW, GuardDecision.DEGRADED)
    allow_write = decision == GuardDecision.ALLOW
    return GuardResult(
        decision=decision,
        reason=reason,
        subject_state=identity.subject_state.value,
        principal_id=identity.principal.id,
        action_type=action_type_val,
        allow_read=allow_read,
        allow_write=allow_write,
    )


# ---------------------------------------------------------------------------
# identity_guard — delegates to Policy Engine
# ---------------------------------------------------------------------------

def identity_guard(
    identity: "RequestIdentity",
    action_type: "Optional[ActionType]" = None,
) -> GuardResult:
    """
    Evaluate the identity guard for a single request.

    F4: delegates the access decision to policy_engine.evaluate_policy.
    The guard itself is responsible for context extraction and result wrapping;
    it does not contain decision logic.

    Args:
        identity:    RequestIdentity built at the request boundary.
        action_type: ActionType for the operation being requested.
                     Defaults to ActionType.READ when absent (safe default —
                     read is the least-privileged non-write classification).

    Returns:
        GuardResult — immutable, JSON-serializable, suitable for audit logging.
    """
    from .policy_engine import ActionType as AT, evaluate_policy, policy_reason

    if action_type is None:
        action_type = AT.READ

    try:
        decision = evaluate_policy(
            principal=identity.principal,
            subject_state=identity.subject_state,
            action_type=action_type,
        )
        reason = policy_reason(identity.subject_state, action_type, decision)
        result = _build_result(identity, decision, action_type.value, reason)

    except Exception as exc:  # pragma: no cover
        # Guard must never raise — convert errors to DENY (fail closed).
        logger.error("identity_guard: unexpected error: %s", exc)
        action_val = action_type.value if action_type is not None else "unknown"
        result = GuardResult(
            decision=GuardDecision.DENY,
            reason=f"Guard evaluation failed unexpectedly: {exc!s}",
            subject_state="unknown",
            principal_id="unknown",
            action_type=action_val,
            allow_read=False,
            allow_write=False,
        )

    logger.debug(
        "identity_guard: principal=%s state=%s action=%s decision=%s",
        result.principal_id,
        result.subject_state,
        result.action_type,
        result.decision.value,
    )
    return result


# ---------------------------------------------------------------------------
# Backward-compat shim — is_write_operation
# ---------------------------------------------------------------------------

def is_write_operation(action: Optional[str]) -> bool:
    """
    Return True when the action string represents a mutating operation.

    F4: delegates to infer_action_type() from the policy engine.
    Retained for backward compatibility — callers in chat_core and
    orchestrator use this function and are not yet updated.

    Prefer infer_action_type() for new code; it returns the full ActionType.
    """
    from .policy_engine import infer_action_type, ActionType as AT
    if not action:
        return False
    at = infer_action_type(action)
    return at in (AT.WRITE, AT.EXECUTE)


# ---------------------------------------------------------------------------
# F3: Centralized guard construction — single canonical entry point (updated F4)
# ---------------------------------------------------------------------------

def build_guarded_request(
    identity: "RequestIdentity",
    *,
    text: str = "",
    context_id: Optional[str] = None,
    filters: Optional[dict] = None,
    metadata: Optional[dict] = None,
    action_type: "Optional[ActionType]" = None,
) -> "tuple[dict, GuardResult]":
    """
    F3/F4: Single canonical path for identity-aware request construction.

    This is the ONE function where:
      1. RequestIdentity is normalized into a CanonicalRequest
      2. ActionType is resolved (explicit > inferred from metadata > READ)
      3. identity_guard (→ policy_engine.evaluate_policy) is called once
      4. guard_decision and action_type are stamped into CanonicalRequest

    Downstream callers MUST NOT call identity_guard() independently.

    ActionType resolution order:
      1. Explicit action_type argument (highest priority)
      2. Inferred from metadata["action"] string via infer_action_type()
      3. ActionType.READ as fallback (safe default)

    Returns:
        (req, guard_result)
          req          — CanonicalRequest with principal_id, subject_state,
                         guard_decision, and action_type stamped.
          guard_result — Full GuardResult for callers that need audit fields
                         (reason, allow_write, evaluated_at).  Same evaluation
                         as req["guard_decision"] — NOT a second call.
    """
    from .contracts import normalize_request
    from .policy_engine import infer_action_type, ActionType as AT

    # Resolve ActionType: explicit arg > infer from metadata["action"] > READ
    if action_type is None:
        meta = metadata or {}
        action_str = meta.get("action") or ""
        action_type = infer_action_type(action_str) if action_str else AT.READ

    # Build normalized request with identity fields
    req = normalize_request(
        text=text,
        context_id=context_id,
        filters=filters,
        metadata=metadata,
        identity=identity,
    )

    # Evaluate guard once — stamps result into req
    guard_result = identity_guard(identity, action_type=action_type)
    req["guard_decision"] = guard_result.decision.value
    req["action_type"] = guard_result.action_type

    return req, guard_result


# ---------------------------------------------------------------------------
# F3: Shared enforcement helper for webhook handler methods
# ---------------------------------------------------------------------------

def enforce_guard_for_handler(
    req: "dict",
    action: Optional[str] = None,
    *,
    principal_id: Optional[str] = None,
) -> "Optional[tuple[str, str]]":
    """
    F3/F4: Shared enforcement helper for webhook handler methods.

    Reads guard_decision from a CanonicalRequest (stamped by
    build_guarded_request) and returns an (error_type, reason) pair when
    the request should be rejected, or None when it may proceed.

    Does NOT call identity_guard() or policy_engine — only reads the
    decision that was already computed by build_guarded_request.

    Decision rules:
        "deny"     → always block (Suspended / Terminated / Quarantined+Execute)
        "degraded" → block only write operations (Quarantined + WRITE/READ)
        "allow"    → unconditionally allow
        absent     → allow (backward-compatible; no identity context)

    For "degraded" decisions, the action arg (if provided) is used to check
    whether this specific operation is a write.  If no action is provided,
    the guard_decision in req is used as-is.

    Args:
        req:          CanonicalRequest dict built via build_guarded_request.
        action:       ACTION_* constant for the operation being attempted.
        principal_id: Optional, for log context only.

    Returns:
        None — request may proceed.
        ("access_denied", reason) — request must be rejected.
        ("write_blocked", reason) — write op rejected under DEGRADED.
    """
    from .policy_engine import infer_action_type, ActionType as AT

    gd = req.get("guard_decision")

    if gd == "deny":
        logger.warning(
            "enforce_guard: DENY — principal=%s action=%s",
            principal_id or req.get("principal_id", "unknown"),
            action or "unknown",
        )
        return (
            "access_denied",
            f"Request denied by identity guard "
            f"(subject_state={req.get('subject_state', 'unknown')}).",
        )

    if gd == "degraded" and action:
        at = infer_action_type(action)
        if at in (AT.WRITE, AT.EXECUTE):
            logger.info(
                "enforce_guard: DEGRADED write blocked — principal=%s action=%s",
                principal_id or req.get("principal_id", "unknown"),
                action,
            )
            return (
                "write_blocked",
                "Write operations are blocked in read-only (quarantined) mode.",
            )

    return None


# ---------------------------------------------------------------------------
# ActionType re-export — convenience so callers import from one place
# ---------------------------------------------------------------------------

# Import at module level for re-export; kept at bottom to avoid circular deps
# at class-definition time (GuardDecision must exist first).
from .policy_engine import ActionType, infer_action_type  # noqa: E402


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Core types
    "GuardDecision",
    "GuardResult",
    # Guard evaluation
    "identity_guard",
    # ActionType (re-exported from policy_engine for convenience)
    "ActionType",
    "infer_action_type",
    # Write-op classification (backward-compat shim)
    "is_write_operation",
    # F3: Centralized construction
    "build_guarded_request",
    "enforce_guard_for_handler",
]
