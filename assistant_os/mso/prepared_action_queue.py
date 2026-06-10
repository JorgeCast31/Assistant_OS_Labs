"""
ConfirmablePreparedActionQueue — process-local in-memory manual review queue.

This module holds ConfirmablePreparedAction artifacts that are waiting for
explicit human review. It is the next surface step in the authority chain:

    ConfirmablePreparedAction (waiting_for_human_confirmation)
    → ConfirmablePreparedActionQueueEntry (pending_review)
    → [human reviews]
    → [human confirms through separate governed path — NOT implemented here]
    → [authority chain: PolicyDecision → CapabilityToken → ...→ PoliceGate]
    → [execution, only after full authority]

Design
------
This module is intentionally NOT:
  - executing any prepared action
  - approving any prepared action
  - calling the runner or any pipeline
  - issuing CapabilityToken
  - creating AuthorizedPlan
  - calling PoliceGate
  - bypassing PolicyDecision, CapabilityToken, OperationBinding, AuthorizedPlan, or PoliceGate
  - enabling HOST, MACHINE_OPERATOR, or OpenClaw
  - adding UI approve/execute controls

This IS:
  - a safe, read-only in-memory queue for manual review of prepared actions
  - derived from ConfirmablePreparedAction via enqueue_confirmable_prepared_action()
  - always review_only=True, execution_allowed=False, can_execute_now=False
  - always human_confirmation_status="pending" (no confirmation issued here)

Invariants (enforced by __post_init__, not negotiable)
------------------------------------------------------
  review_only       = True   (always)
  execution_allowed = False  (always)
  can_execute_now   = False  (always)

Thread safety
-------------
The in-memory queue (_queue dict) is protected by a threading.Lock.
All reads and writes go through the lock.

Process-local scope
-------------------
This queue is process-local (in-memory). It does not persist across restarts.
No database, no external service, no network calls. This is intentional for
the current sprint scope.

Test isolation
--------------
Use clear_confirmable_action_queue_for_tests() to reset the queue between tests.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from .confirmable_prepared_action import ConfirmablePreparedAction


# ---------------------------------------------------------------------------
# Module-level in-memory queue + lock
# ---------------------------------------------------------------------------

_queue: dict[str, "ConfirmablePreparedActionQueueEntry"] = {}
_lock: threading.Lock = threading.Lock()


# ---------------------------------------------------------------------------
# ConfirmablePreparedActionQueueEntry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfirmablePreparedActionQueueEntry:
    """
    Manual review queue entry for a ConfirmablePreparedAction.

    Derived from ConfirmablePreparedAction via enqueue_confirmable_prepared_action().
    This entry is review-only: it never issues tokens, never creates AuthorizedPlan,
    never calls Police, never executes, and never approves anything.

    Fields
    ------
    queue_entry_id : str
        Unique identifier for this queue entry. Auto-generated UUID.

    prepared_action_id : str
        ID of the source ConfirmablePreparedAction (action_id).

    preparation_id : str
        ID of the source AuthorityPreparationRequest.

    proposal_id : str
        ID of the source MSOExecutionProposal.

    user_intent : str
        Original user intent, copied from the prepared action.

    domain : str
        Classified domain, copied from the prepared action.

    requested_action : str
        Requested action, copied from the prepared action.

    capability_name : str
        Required capability name, copied from the prepared action.

    capability_scope : tuple[str, ...]
        Capability scope values, copied from the prepared action.

    delegated_seat_ref : Optional[str]
        Seat reference for traceability.

    provider_name : Optional[str]
        Provider name for traceability.

    model_name : Optional[str]
        Model name for traceability.

    human_confirmation_status : str
        Always "pending" at queue entry creation. Confirmation is a separate
        governed step outside this module.

    status : str
        Always "pending_review" — this entry is waiting for human review.

    created_at : str
        ISO 8601 UTC timestamp of when this entry was enqueued.

    review_only : bool
        INVARIANT: always True. This entry is for manual review only.

    execution_allowed : bool
        INVARIANT: always False. This entry does not authorize execution.

    can_execute_now : bool
        INVARIANT: always False. No execution path is available from this entry.

    notes : str
        Human-readable explanation of the review requirement.

    artifact_type : str
        Constant: "confirmable_prepared_action_queue_entry".
    """

    # Identity
    queue_entry_id: str = field(default_factory=lambda: f"qe-{uuid4()}")
    prepared_action_id: str = ""
    preparation_id: str = ""
    proposal_id: str = ""

    # Intent / classification (copied from prepared action)
    user_intent: str = ""
    domain: str = "UNKNOWN"
    requested_action: str = ""

    # Resource (optional governed target, e.g. repo URL). Backward compatible.
    resource: Optional[str] = None

    # Capability (copied from prepared action)
    capability_name: str = ""
    capability_scope: tuple[str, ...] = field(default_factory=tuple)

    # Traceability (copied from prepared action)
    delegated_seat_ref: Optional[str] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None

    # Confirmation state
    human_confirmation_status: str = "pending"

    # Queue lifecycle status
    status: str = "pending_review"

    # Timestamp
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Safety invariants — NEVER change these defaults
    review_only: bool = True
    execution_allowed: bool = False
    can_execute_now: bool = False

    # Notes
    notes: str = ""

    # Artifact type tag
    artifact_type: str = "confirmable_prepared_action_queue_entry"

    def __post_init__(self) -> None:
        """Enforce non-negotiable safety invariants."""
        if self.review_only is not True:
            raise ValueError(
                "ConfirmablePreparedActionQueueEntry.review_only must always be True. "
                "This entry is a manual review record, not an execution authority."
            )
        if self.execution_allowed is not False:
            raise ValueError(
                "ConfirmablePreparedActionQueueEntry.execution_allowed must always be False. "
                "Queue entries do not authorize execution."
            )
        if self.can_execute_now is not False:
            raise ValueError(
                "ConfirmablePreparedActionQueueEntry.can_execute_now must always be False. "
                "No execution path is available from a manual review queue entry."
            )

    def to_dict(self) -> dict:
        """Serialize for audit/transport/surface response. Never includes secrets."""
        return {
            "artifact_type": self.artifact_type,
            "queue_entry_id": self.queue_entry_id,
            "prepared_action_id": self.prepared_action_id,
            "preparation_id": self.preparation_id,
            "proposal_id": self.proposal_id,
            "user_intent": self.user_intent,
            "domain": self.domain,
            "requested_action": self.requested_action,
            "resource": self.resource,
            "capability_name": self.capability_name,
            "capability_scope": list(self.capability_scope),
            "delegated_seat_ref": self.delegated_seat_ref,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "human_confirmation_status": self.human_confirmation_status,
            "status": self.status,
            "created_at": self.created_at,
            "review_only": self.review_only,
            "execution_allowed": self.execution_allowed,
            "can_execute_now": self.can_execute_now,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Queue operations
# ---------------------------------------------------------------------------


def enqueue_confirmable_prepared_action(
    action: ConfirmablePreparedAction,
) -> ConfirmablePreparedActionQueueEntry:
    """
    Enqueue a ConfirmablePreparedAction for manual review.

    Pure metadata copy — does not mutate the original action.
    Does not execute, approve, issue tokens, call Police, or create AuthorizedPlan.

    The resulting entry is stored in the process-local in-memory queue with
    status="pending_review" and human_confirmation_status="pending".

    Parameters
    ----------
    action : ConfirmablePreparedAction
        The prepared action to enqueue.

    Returns
    -------
    ConfirmablePreparedActionQueueEntry
        Immutable queue entry with review_only=True, execution_allowed=False,
        can_execute_now=False.

    Raises
    ------
    TypeError
        If action is not a ConfirmablePreparedAction instance.
    """
    if not isinstance(action, ConfirmablePreparedAction):
        raise TypeError(
            f"enqueue_confirmable_prepared_action requires ConfirmablePreparedAction, "
            f"got {type(action).__name__!r}."
        )

    if action.status == "waiting_for_human_confirmation" and action.domain == "UNKNOWN":
        notes = (
            f"Queue entry for UNKNOWN domain action (action_id={action.action_id!r}). "
            "Pending human review. Domain may be unclassified. "
            "Human confirmation required before any authority chain can proceed. "
            "No execution path available from this entry."
        )
    else:
        notes = (
            f"Manual review queue entry for domain={action.domain!r}, "
            f"action={action.requested_action!r} "
            f"(action_id={action.action_id!r}). "
            "Waiting for explicit human review. "
            "Human confirmation required before any authority chain can proceed. "
            "No execution path available from this entry."
        )

    entry = ConfirmablePreparedActionQueueEntry(
        prepared_action_id=action.action_id,
        preparation_id=action.preparation_id,
        proposal_id=action.proposal_id,
        user_intent=action.user_intent,
        domain=action.domain,
        requested_action=action.requested_action,
        resource=action.resource,
        capability_name=action.capability_name,
        capability_scope=action.capability_scope,
        delegated_seat_ref=action.delegated_seat_ref,
        provider_name=action.provider_name,
        model_name=action.model_name,
        human_confirmation_status="pending",
        status="pending_review",
        review_only=True,
        execution_allowed=False,
        can_execute_now=False,
        notes=notes,
    )

    with _lock:
        _queue[entry.queue_entry_id] = entry

    return entry


def list_pending_confirmable_actions() -> list[ConfirmablePreparedActionQueueEntry]:
    """
    Return all pending manual review queue entries, newest-first.

    Read-only — does not modify the queue, does not approve, does not execute.
    Returns an immutable snapshot of current queue contents.

    Returns
    -------
    list[ConfirmablePreparedActionQueueEntry]
        All entries currently in the queue, newest-first (by created_at).
        Empty list if queue is empty.
    """
    with _lock:
        entries = list(_queue.values())
    entries.sort(key=lambda e: e.created_at, reverse=True)
    return entries


def get_confirmable_action_queue_entry(
    entry_id: str,
) -> Optional[ConfirmablePreparedActionQueueEntry]:
    """
    Return a single queue entry by its queue_entry_id, or None if not found.

    Read-only — does not modify the queue.
    """
    with _lock:
        return _queue.get(entry_id)


def list_pending_confirmable_action_dicts() -> list[dict]:
    """
    Return serialized dicts of all pending manual review queue entries, newest-first.

    Read-only. Safe for surface/API transport. No execution affordance.
    Delegates to list_pending_confirmable_actions() and calls to_dict() on each entry.

    Returns
    -------
    list[dict]
        Serialized queue entries. Empty list if queue is empty.
        Each dict contains only review-safe fields (see to_dict()).
        No tokens, no AuthorizedPlan refs, no Police decision refs.
    """
    return [e.to_dict() for e in list_pending_confirmable_actions()]


def clear_confirmable_action_queue_for_tests() -> None:
    """
    Empty the in-memory queue. FOR TESTS ONLY.

    Must be called in test setup/teardown to prevent state bleed between tests.
    Never call this in production code paths.
    """
    with _lock:
        _queue.clear()
