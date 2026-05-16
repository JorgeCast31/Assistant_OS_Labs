"""MSO AuthorityBindingDraft — second authority chain artifact after MSOPolicyDecisionDraft.

This module produces a deterministic, frozen ``MSOAuthorityBindingDraft`` from an
approved ``MSOPolicyDecisionDraft``. It advances the chain label only.

Authority chain position
------------------------
MSOExecutionProposal
→ AuthorityPreparationRequest
→ ConfirmablePreparedAction / queue
→ HumanConfirmationRecord
→ MSOPolicyDecisionDraft
→ MSOAuthorityBindingDraft                                            ← this module
→ [CapabilityToken]   (future — production token_issuer.issue_token)
→ [OperationBinding]  (future — production token_models.OperationBinding)
→ [AuthorizedPlan]    (future)
→ [PoliceGate]        (future)
→ [execution]         (future)

Design
------
This module is intentionally NOT:
  - calling token_issuer.issue_token() (non-idempotent, registers in _token_registry)
  - creating OperationBinding or AuthorizedPlan (production artifacts)
  - calling PoliceGate enforcement.check() (marks tokens SPENT)
  - calling RunnerAPI.execute() (actual execution)
  - signing with AuthorityArtifact (HMAC-SHA256, production)

This IS:
  - a draft artifact for the MSO authority chain (chain position 6)
  - derived from an approved MSOPolicyDecisionDraft
  - idempotent by entry_id (duplicate calls return the same artifact)
  - always execution_allowed=False, can_execute_now=False, used_execution=False
  - stored in process-local in-memory store keyed by entry_id
  - merged into GET /mso/prepared-actions/pending read model at read time

Invariants (enforced by __post_init__)
--------------------------------------
  execution_allowed     = False  (always)
  can_execute_now       = False  (always)
  used_execution        = False  (always)
  authority_binding_id != ""     (always non-empty)

Fail-closed rules
-----------------
- policy_outcome not in ("approved", "approved_confirm_only") → raises ValueError
- entry_id mismatch between entry and policy_review → raises ValueError
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Optional
from uuid import uuid4

from .policy_review import MSOPolicyDecisionDraft
from .prepared_action_queue import ConfirmablePreparedActionQueueEntry


def _new_id() -> str:
    return f"ab-{uuid4()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class MSOAuthorityBindingDraft:
    """Frozen MSO-scope authority binding draft.

    Second authority chain artifact after MSOPolicyDecisionDraft.
    Produced by create_mso_authority_binding().

    Never calls token_issuer, creates OperationBinding/AuthorizedPlan,
    calls PoliceGate, or executes.
    execution_allowed, can_execute_now, and used_execution are invariantly False.
    """

    # Identity
    authority_binding_id: str = field(default_factory=_new_id)
    entry_id: str = ""
    action_id: str = ""
    policy_review_id: str = ""

    # Source context
    domain: str = "UNKNOWN"
    requested_action: str = ""
    capability_name: str = ""
    capability_mode: str = ""
    policy_outcome: str = ""

    # Binding state
    binding_status: str = "drafted"

    # Chain requirements — always True at this stage
    requires_authorized_plan: bool = True
    requires_police_gate: bool = True

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    can_execute_now: bool = False
    used_execution: bool = False

    # Timestamps and notes
    created_at: datetime = field(default_factory=_now)
    notes: str = ""

    # Artifact type tag
    artifact_type: str = "mso_authority_binding_draft"

    def __post_init__(self) -> None:
        if self.execution_allowed is not False:
            raise ValueError(
                "MSOAuthorityBindingDraft.execution_allowed must always be False. "
                "An authority binding draft does not authorize execution."
            )
        if self.can_execute_now is not False:
            raise ValueError(
                "MSOAuthorityBindingDraft.can_execute_now must always be False. "
                "An authority binding draft does not open any execution path."
            )
        if self.used_execution is not False:
            raise ValueError(
                "MSOAuthorityBindingDraft.used_execution must always be False. "
                "No execution was performed to produce an authority binding draft."
            )
        if not self.authority_binding_id:
            raise ValueError(
                "MSOAuthorityBindingDraft.authority_binding_id must be non-empty."
            )

    def to_dict(self) -> dict:
        """Serialize for audit/transport. Never includes secrets."""
        return {
            "artifact_type": self.artifact_type,
            "authority_binding_id": self.authority_binding_id,
            "entry_id": self.entry_id,
            "action_id": self.action_id,
            "policy_review_id": self.policy_review_id,
            "domain": self.domain,
            "requested_action": self.requested_action,
            "capability_name": self.capability_name,
            "capability_mode": self.capability_mode,
            "policy_outcome": self.policy_outcome,
            "binding_status": self.binding_status,
            "requires_authorized_plan": self.requires_authorized_plan,
            "requires_police_gate": self.requires_police_gate,
            "execution_allowed": self.execution_allowed,
            "can_execute_now": self.can_execute_now,
            "used_execution": self.used_execution,
            "created_at": self.created_at.isoformat(),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_store: dict[str, MSOAuthorityBindingDraft] = {}
_lock = Lock()


def _store_authority_binding(binding: MSOAuthorityBindingDraft) -> None:
    with _lock:
        _store[binding.entry_id] = binding


def get_mso_authority_binding(entry_id: str) -> Optional[MSOAuthorityBindingDraft]:
    """Return the stored MSOAuthorityBindingDraft for entry_id, or None."""
    with _lock:
        return _store.get(entry_id)


def clear_mso_authority_binding_store_for_tests() -> None:
    """Empty the store. FOR TESTS ONLY."""
    with _lock:
        _store.clear()


# ---------------------------------------------------------------------------
# Merge into GET read model
# ---------------------------------------------------------------------------

def merge_authority_binding_into_dict(item_dict: dict) -> dict:
    """Overlay authority binding fields onto a prepared action dict (by queue_entry_id).

    Pure read — never mutates the store or the source dict.
    Returns a new dict with authority_binding_id, authority_binding_status,
    authority_binding_created_at, requires_authorized_plan, requires_police_gate
    overlaid if a binding record exists.
    """
    entry_id = item_dict.get("queue_entry_id", "")
    if not entry_id:
        return item_dict
    binding = get_mso_authority_binding(entry_id)
    if binding is None:
        return item_dict
    result = dict(item_dict)
    result["authority_binding_id"] = binding.authority_binding_id
    result["authority_binding_status"] = binding.binding_status
    result["authority_binding_created_at"] = binding.created_at.isoformat()
    result["requires_authorized_plan"] = binding.requires_authorized_plan
    result["requires_police_gate"] = binding.requires_police_gate
    return result


# ---------------------------------------------------------------------------
# Core creation function
# ---------------------------------------------------------------------------

def create_mso_authority_binding(
    entry: ConfirmablePreparedActionQueueEntry,
    policy_review: MSOPolicyDecisionDraft,
) -> MSOAuthorityBindingDraft:
    """Create an MSOAuthorityBindingDraft from an approved MSOPolicyDecisionDraft.

    Idempotent: same entry_id → same authority_binding_id (returns existing if stored).
    Does NOT call token_issuer, create OperationBinding/AuthorizedPlan,
    call PoliceGate, or invoke runner.

    Parameters
    ----------
    entry : ConfirmablePreparedActionQueueEntry
    policy_review : MSOPolicyDecisionDraft
        Must have policy_outcome in ("approved", "approved_confirm_only").

    Returns
    -------
    MSOAuthorityBindingDraft
        Frozen artifact stored in the authority binding store.

    Raises
    ------
    ValueError
        If policy_outcome is not "approved" or "approved_confirm_only".
        If policy_review.entry_id does not match entry.queue_entry_id.
    """
    existing = get_mso_authority_binding(entry.queue_entry_id)
    if existing is not None:
        return existing

    if policy_review.policy_outcome not in ("approved", "approved_confirm_only"):
        raise ValueError(
            f"Cannot create authority binding for policy_outcome={policy_review.policy_outcome!r}. "
            "Only 'approved' or 'approved_confirm_only' outcomes may advance the authority chain. "
            "Denied outcomes do not advance."
        )

    if policy_review.entry_id != entry.queue_entry_id:
        raise ValueError(
            f"entry_id mismatch: policy_review.entry_id={policy_review.entry_id!r} "
            f"does not match entry.queue_entry_id={entry.queue_entry_id!r}. "
            "Authority binding rejected to prevent cross-entry authority confusion."
        )

    binding = MSOAuthorityBindingDraft(
        entry_id=entry.queue_entry_id,
        action_id=entry.prepared_action_id,
        policy_review_id=policy_review.policy_review_id,
        domain=entry.domain,
        requested_action=entry.requested_action,
        capability_name=entry.capability_name or policy_review.capability_name,
        capability_mode=policy_review.capability_mode,
        policy_outcome=policy_review.policy_outcome,
        binding_status="drafted",
        requires_authorized_plan=True,
        requires_police_gate=True,
        execution_allowed=False,
        can_execute_now=False,
        used_execution=False,
        notes=(
            f"Authority binding draft for entry '{entry.queue_entry_id}'. "
            f"Policy review '{policy_review.policy_review_id}' "
            f"outcome={policy_review.policy_outcome!r}. "
            "AuthorizedPlan, PoliceGate, and execution still required."
        ),
    )
    _store_authority_binding(binding)
    return binding
