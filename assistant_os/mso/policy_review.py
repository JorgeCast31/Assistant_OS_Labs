"""MSO PolicyDecisionDraft — first authority chain artifact after human confirmation.

This module produces a deterministic, frozen ``MSOPolicyDecisionDraft`` by
evaluating the confirmed prepared action's domain/action/capability against the
MSO capability registry (``capability_registry.check_capability``).

Authority chain position
------------------------
MSOExecutionProposal
→ AuthorityPreparationRequest
→ ConfirmablePreparedAction / ConfirmablePreparedActionQueueEntry  (review-only)
→ HumanConfirmationRecord                                           (signal only, not authority)
→ MSOPolicyDecisionDraft                                           ← this module
→ [CapabilityToken]   (future)
→ [OperationBinding]  (future)
→ [AuthorizedPlan]    (future)
→ [PoliceGate]        (future)
→ [execution]         (future, only after full authority chain)

Design
------
This module is intentionally NOT:
  - issuing a CapabilityToken
  - creating an OperationBinding
  - creating an AuthorizedPlan
  - calling PoliceGate
  - calling the runner, Machine Operator, or any pipeline
  - changing Police, authority-signing, or runner semantics
  - treating human confirmation as authority

This IS:
  - a policy review artifact for the MSO authority chain
  - derived from a confirmed HumanConfirmationRecord + ConfirmablePreparedActionQueueEntry
  - evaluated deterministically against the MSO capability registry
  - always execution_allowed=False, can_execute_now=False, used_execution=False
  - stored in a process-local in-memory store keyed by queue_entry_id
  - merged into GET /mso/prepared-actions/pending read model at read time

Invariants (enforced by __post_init__, not negotiable)
------------------------------------------------------
  execution_allowed = False  (always)
  can_execute_now   = False  (always)
  used_execution    = False  (always)
  policy_review_id  != ""    (always non-empty)

Fail-closed rules
-----------------
- No HumanConfirmationRecord → reject (confirmation_required)
- confirmed=False → reject (action_rejected — cannot review rejected actions)
- action_id mismatch → reject (action_id_mismatch)
- entry not in queue → reject (entry not found)
- Unknown action in capability registry → denied outcome (not an error)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Optional
from uuid import uuid4

from .capability_registry import check_capability
from .human_confirmation import HumanConfirmationRecord
from .prepared_action_queue import ConfirmablePreparedActionQueueEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return f"prd-{uuid4()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# MSOPolicyDecisionDraft
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class MSOPolicyDecisionDraft:
    """Frozen MSO-scope policy decision draft.

    First authority chain artifact after HumanConfirmationRecord.
    Produced by evaluate_mso_policy_for_prepared_action().

    Never issues tokens, creates AuthorizedPlan, calls PoliceGate, or executes.
    execution_allowed, can_execute_now, and used_execution are invariantly False.
    """

    # Identity
    policy_review_id: str = field(default_factory=_new_id)
    entry_id: str = ""
    action_id: str = ""

    # Source context (copied from queue entry)
    domain: str = "UNKNOWN"
    requested_action: str = ""
    capability_name: str = ""

    # Capability registry result
    capability_mode: str = ""              # "allow" | "confirm_only" | "deny" | "revoked"

    # Policy outcome
    policy_outcome: str = ""              # "approved" | "approved_confirm_only" | "denied"

    # Confirmation traceability
    requires_human_confirmation: bool = True
    human_confirmation_satisfied: bool = False

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    can_execute_now: bool = False
    used_execution: bool = False

    # Timestamps and notes
    created_at: datetime = field(default_factory=_now)
    notes: str = ""

    # Artifact type tag
    artifact_type: str = "mso_policy_decision_draft"

    def __post_init__(self) -> None:
        """Enforce non-negotiable safety invariants."""
        if self.execution_allowed is not False:
            raise ValueError(
                "MSOPolicyDecisionDraft.execution_allowed must always be False. "
                "A policy decision draft is a review artifact; it does not authorize execution."
            )
        if self.can_execute_now is not False:
            raise ValueError(
                "MSOPolicyDecisionDraft.can_execute_now must always be False. "
                "A policy decision draft does not open any execution path."
            )
        if self.used_execution is not False:
            raise ValueError(
                "MSOPolicyDecisionDraft.used_execution must always be False. "
                "No execution was performed to produce a policy decision draft."
            )
        if not self.policy_review_id:
            raise ValueError(
                "MSOPolicyDecisionDraft.policy_review_id must be non-empty."
            )

    def to_dict(self) -> dict:
        """Serialize for audit/transport. Never includes secrets."""
        return {
            "artifact_type": self.artifact_type,
            "policy_review_id": self.policy_review_id,
            "entry_id": self.entry_id,
            "action_id": self.action_id,
            "domain": self.domain,
            "requested_action": self.requested_action,
            "capability_name": self.capability_name,
            "capability_mode": self.capability_mode,
            "policy_outcome": self.policy_outcome,
            "requires_human_confirmation": self.requires_human_confirmation,
            "human_confirmation_satisfied": self.human_confirmation_satisfied,
            "execution_allowed": self.execution_allowed,
            "can_execute_now": self.can_execute_now,
            "used_execution": self.used_execution,
            "created_at": self.created_at.isoformat(),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_store: dict[str, MSOPolicyDecisionDraft] = {}   # keyed by entry_id (queue_entry_id)
_lock = Lock()


def _store_policy_review(draft: MSOPolicyDecisionDraft) -> None:
    with _lock:
        _store[draft.entry_id] = draft


def get_mso_policy_review(entry_id: str) -> Optional[MSOPolicyDecisionDraft]:
    """Return the stored MSOPolicyDecisionDraft for entry_id, or None."""
    with _lock:
        return _store.get(entry_id)


def clear_mso_policy_review_store_for_tests() -> None:
    """Empty the store. FOR TESTS ONLY."""
    with _lock:
        _store.clear()


# ---------------------------------------------------------------------------
# Merge into GET read model
# ---------------------------------------------------------------------------

def merge_policy_review_into_dict(item_dict: dict) -> dict:
    """Overlay policy review fields onto a prepared action dict (by queue_entry_id).

    Pure read — never mutates the store or the source dict.
    Returns a new dict with policy_review_id, policy_outcome, capability_mode,
    and policy_review_created_at overlaid if a review record exists.
    """
    entry_id = item_dict.get("queue_entry_id", "")
    if not entry_id:
        return item_dict
    draft = get_mso_policy_review(entry_id)
    if draft is None:
        return item_dict
    result = dict(item_dict)
    result["policy_review_id"] = draft.policy_review_id
    result["policy_outcome"] = draft.policy_outcome
    result["capability_mode"] = draft.capability_mode
    result["policy_review_created_at"] = draft.created_at.isoformat()
    return result


# ---------------------------------------------------------------------------
# Core evaluation function — pure, deterministic, no side effects except store
# ---------------------------------------------------------------------------

def evaluate_mso_policy_for_prepared_action(
    entry: ConfirmablePreparedActionQueueEntry,
    confirmation: HumanConfirmationRecord,
) -> MSOPolicyDecisionDraft:
    """Evaluate MSO capability policy for a confirmed prepared action.

    Deterministic: same entry + confirmation → same policy_outcome.
    Calls check_capability(action, domain) from the MSO capability registry.
    Stores the result in the process-local policy review store.

    Does NOT:
    - Issue CapabilityToken
    - Create OperationBinding or AuthorizedPlan
    - Call PoliceGate
    - Call runner or Machine Operator
    - Change execution_allowed, can_execute_now, or used_execution

    Parameters
    ----------
    entry : ConfirmablePreparedActionQueueEntry
        The queue entry for the action being reviewed.
    confirmation : HumanConfirmationRecord
        The human confirmation record. Must have confirmed=True.

    Returns
    -------
    MSOPolicyDecisionDraft
        Frozen artifact stored in the policy review store.

    Raises
    ------
    ValueError
        If confirmation.confirmed is False (action was rejected).
        If confirmation.action_id does not match entry.prepared_action_id.
    """
    if not confirmation.confirmed:
        raise ValueError(
            "Cannot evaluate policy for a rejected action. "
            "confirmation.confirmed must be True. "
            "Rejected actions do not advance the authority chain."
        )

    if confirmation.action_id != entry.prepared_action_id:
        raise ValueError(
            f"action_id mismatch: confirmation.action_id={confirmation.action_id!r} "
            f"does not match entry.prepared_action_id={entry.prepared_action_id!r}. "
            "Policy review rejected to prevent cross-entry authority confusion."
        )

    capability = check_capability(entry.requested_action, entry.domain)

    if capability.mode == "allow" and capability.allowed:
        outcome = "approved"
        notes = (
            f"Capability '{capability.action}' in domain '{entry.domain}' "
            f"is approved (mode=allow). "
            "Human confirmation satisfied. "
            "Execution remains closed pending full authority chain."
        )
    elif capability.mode == "confirm_only" and capability.allowed:
        outcome = "approved_confirm_only"
        notes = (
            f"Capability '{capability.action}' in domain '{entry.domain}' "
            f"requires confirmation (mode=confirm_only). "
            "Human confirmation satisfied. "
            "Execution remains closed pending full authority chain."
        )
    else:
        # deny, blocked, revoked, or any unknown mode
        outcome = "denied"
        notes = (
            f"Capability '{capability.action}' in domain '{entry.domain}' "
            f"is denied (mode={capability.mode!r}). "
            f"Deny reason: {capability.deny_reason or 'blocked by capability registry'}. "
            "Human confirmation does not override capability denial."
        )

    draft = MSOPolicyDecisionDraft(
        entry_id=entry.queue_entry_id,
        action_id=entry.prepared_action_id,
        domain=entry.domain,
        requested_action=entry.requested_action,
        capability_name=entry.capability_name or capability.action,
        capability_mode=capability.mode,
        policy_outcome=outcome,
        requires_human_confirmation=True,
        human_confirmation_satisfied=True,
        execution_allowed=False,
        can_execute_now=False,
        used_execution=False,
        notes=notes,
    )
    _store_policy_review(draft)
    return draft
