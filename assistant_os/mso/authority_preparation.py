"""
AuthorityPreparationRequest — non-executing authority review preparation artifact.

This module bridges an MSOExecutionProposal (cognitive planning artifact) to
a structured preparation record that declares what authority is still pending
before any execution can occur.

Design
------
This is intentionally NOT:
  - an AuthorizedPlan          (execution binding — requires all authority satisfied)
  - a PolicyDecision           (policy verdict)
  - a PoliceDecision           (police gate verdict)
  - a CapabilityToken          (execution capability)
  - an OperationBinding        (action fingerprint)
  - an execution result        (something that ran)

This IS:
  - a preparation artifact for governed authority review
  - derived from MSOExecutionProposal without executing anything
  - declaring which authority steps are still pending (all of them at draft time)
  - always cognitive_only=True, used_execution=False, execution_allowed=False

Invariants (enforced by __post_init__, not negotiable)
------------------------------------------------------
  cognitive_only     = True   (always)
  used_execution     = False  (always)
  execution_allowed  = False  (always)

Status lifecycle
----------------
  draft                  — just created from a proposal; no authority steps satisfied
  pending_policy         — awaiting PolicyDecision
  pending_confirmation   — awaiting human confirmation
  ready_for_authority    — all pre-execution checks described; awaiting authority chain
  blocked                — preparation blocked due to missing/invalid proposal data

Authority refs
--------------
All authority refs start as None (pending). They are never set by this module.
Setting them is the responsibility of the governed authority chain, not the seat.

  policy_decision_ref    — pending PolicyDecision
  capability_token_ref   — pending CapabilityToken
  operation_binding_ref  — pending OperationBinding
  authorized_plan_ref    — pending AuthorizedPlan
  police_decision_ref    — pending PoliceGate decision

The purpose of including these fields is traceability and explicit declaration
that ALL five steps are required before any execution can proceed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional
from uuid import uuid4

from .execution_proposal import MSOExecutionProposal, REQUIRED_AUTHORITY_CHAIN


# ---------------------------------------------------------------------------
# Status type
# ---------------------------------------------------------------------------

PreparationStatus = Literal[
    "draft",
    "pending_policy",
    "pending_confirmation",
    "ready_for_authority",
    "blocked",
]


# ---------------------------------------------------------------------------
# AuthorityPreparationRequest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthorityPreparationRequest:
    """
    Non-executing authority review preparation artifact.

    Derived from MSOExecutionProposal via prepare_authority_from_proposal().
    All authority refs start None (pending). This artifact never issues tokens,
    never creates AuthorizedPlan, never calls Police, never executes.

    Fields
    ------
    preparation_id : str
        Unique identifier for this preparation record.

    proposal_id : str
        ID of the source MSOExecutionProposal.

    user_intent : str
        The original user intent copied from the proposal.

    domain : str
        Classified domain copied from the proposal.

    requested_action : str
        Requested action copied from the proposal.

    capability_name : str
        Required capability name copied from the proposal.

    capability_scope : tuple[str, ...]
        Capability scope values copied from the proposal.

    delegated_seat_ref : Optional[str]
        Seat reference for traceability, copied from proposal.

    provider_name : Optional[str]
        Provider name for traceability, copied from proposal.

    model_name : Optional[str]
        Model name for traceability, copied from proposal.

    requires_human_confirmation : bool
        Whether human approval is required before execution.
        Copied from proposal and always True for execution proposals.

    required_authority_chain : tuple[str, ...]
        The full authority chain that must be satisfied before any execution.
        Copied from proposal: PolicyDecision, CapabilityToken, OperationBinding,
        AuthorizedPlan, PoliceGate.

    policy_decision_ref : Optional[str]
        Reference to a PolicyDecision. None = pending.
        Never set by this module — set by the governed authority chain.

    capability_token_ref : Optional[str]
        Reference to a CapabilityToken. None = pending.

    operation_binding_ref : Optional[str]
        Reference to an OperationBinding. None = pending.

    authorized_plan_ref : Optional[str]
        Reference to an AuthorizedPlan. None = pending.

    police_decision_ref : Optional[str]
        Reference to a PoliceGate decision. None = pending.

    status : PreparationStatus
        Lifecycle state of this preparation record.
        "draft" at creation; only the authority chain can advance it.

    execution_allowed : bool
        INVARIANT: always False. This record does not authorize execution.

    used_execution : bool
        INVARIANT: always False. No execution performed to produce this record.

    cognitive_only : bool
        INVARIANT: always True. This is a cognitive/preparation artifact.

    notes : str
        Human-readable explanation of pending authority steps.

    artifact_type : str
        Constant: "authority_preparation_request".
    """

    # Identity
    preparation_id: str = field(default_factory=lambda: f"prep-{uuid4()}")
    proposal_id: str = ""

    # Intent / classification (copied from proposal)
    user_intent: str = ""
    domain: str = "UNKNOWN"
    requested_action: str = ""

    # Resource (optional governed target, e.g. repo URL). Backward compatible.
    resource: Optional[str] = None

    # Capability (copied from proposal)
    capability_name: str = ""
    capability_scope: tuple[str, ...] = field(default_factory=tuple)

    # Traceability (copied from proposal)
    delegated_seat_ref: Optional[str] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None

    # Confirmation requirement
    requires_human_confirmation: bool = True

    # Authority chain declaration
    required_authority_chain: tuple[str, ...] = field(
        default_factory=lambda: REQUIRED_AUTHORITY_CHAIN
    )

    # Authority refs — all None (pending) at creation
    policy_decision_ref: Optional[str] = None
    capability_token_ref: Optional[str] = None
    operation_binding_ref: Optional[str] = None
    authorized_plan_ref: Optional[str] = None
    police_decision_ref: Optional[str] = None

    # Lifecycle status
    status: PreparationStatus = "draft"

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    used_execution: bool = False
    cognitive_only: bool = True

    # Notes
    notes: str = ""

    # Artifact type tag
    artifact_type: str = "authority_preparation_request"

    def __post_init__(self) -> None:
        """Enforce non-negotiable safety invariants."""
        if self.execution_allowed is not False:
            raise ValueError(
                "AuthorityPreparationRequest.execution_allowed must always be False. "
                "This artifact prepares for authority review; it does not authorize execution."
            )
        if self.used_execution is not False:
            raise ValueError(
                "AuthorityPreparationRequest.used_execution must always be False. "
                "No execution is performed to produce an authority preparation record."
            )
        if self.cognitive_only is not True:
            raise ValueError(
                "AuthorityPreparationRequest.cognitive_only must always be True. "
                "This artifact is a cognitive/preparation record, not an execution result."
            )

    @property
    def pending_authority_steps(self) -> list[str]:
        """Return list of authority steps that are still pending (ref is None)."""
        steps = []
        mapping = {
            "PolicyDecision": self.policy_decision_ref,
            "CapabilityToken": self.capability_token_ref,
            "OperationBinding": self.operation_binding_ref,
            "AuthorizedPlan": self.authorized_plan_ref,
            "PoliceGate": self.police_decision_ref,
        }
        for step in self.required_authority_chain:
            if mapping.get(step) is None:
                steps.append(step)
        return steps

    @property
    def all_authority_pending(self) -> bool:
        """True when no authority steps have been satisfied yet."""
        return len(self.pending_authority_steps) == len(self.required_authority_chain)

    def to_dict(self) -> dict:
        """Serialize for audit/transport. Never includes secrets."""
        return {
            "artifact_type": self.artifact_type,
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
            "requires_human_confirmation": self.requires_human_confirmation,
            "required_authority_chain": list(self.required_authority_chain),
            "policy_decision_ref": self.policy_decision_ref,
            "capability_token_ref": self.capability_token_ref,
            "operation_binding_ref": self.operation_binding_ref,
            "authorized_plan_ref": self.authorized_plan_ref,
            "police_decision_ref": self.police_decision_ref,
            "status": self.status,
            "execution_allowed": self.execution_allowed,
            "used_execution": self.used_execution,
            "cognitive_only": self.cognitive_only,
            "notes": self.notes,
            "pending_authority_steps": self.pending_authority_steps,
            "all_authority_pending": self.all_authority_pending,
        }


# ---------------------------------------------------------------------------
# Mapping function: MSOExecutionProposal → AuthorityPreparationRequest
# ---------------------------------------------------------------------------


def prepare_authority_from_proposal(
    proposal: MSOExecutionProposal,
) -> AuthorityPreparationRequest:
    """
    Map an MSOExecutionProposal to an AuthorityPreparationRequest.

    Pure function — no side effects, no I/O, no network, no token issuance,
    no AuthorizedPlan creation, no Police calls, no runner/pipeline invocation.

    The returned record:
    - copies intent/domain/capability/scope/traceability from the proposal
    - preserves cognitive_only=True, used_execution=False, execution_allowed=False
    - sets all authority refs to None (pending — not satisfied by this function)
    - sets status to "draft" (or "blocked" if proposal domain is UNKNOWN)
    - includes full authority chain from proposal

    Parameters
    ----------
    proposal : MSOExecutionProposal
        The source cognitive orchestration proposal from the seat.

    Returns
    -------
    AuthorityPreparationRequest
        Immutable preparation record with all authority refs pending.

    Raises
    ------
    TypeError
        If proposal is not an MSOExecutionProposal instance.
    """
    if not isinstance(proposal, MSOExecutionProposal):
        raise TypeError(
            f"prepare_authority_from_proposal requires MSOExecutionProposal, "
            f"got {type(proposal).__name__!r}."
        )

    # Determine initial status.
    # UNKNOWN domain or empty user_intent → "blocked" (cannot proceed without classification).
    # All other proposals start as "draft".
    if proposal.domain == "UNKNOWN" or not proposal.user_intent.strip():
        status: PreparationStatus = "blocked"
        notes = (
            "Authority preparation blocked: proposal domain is UNKNOWN or intent is missing. "
            "Reclassify the domain before requesting authority review. "
            "Required authority steps: "
            + " → ".join(proposal.next_required_authority)
        )
    else:
        status = "draft"
        notes = (
            f"Authority preparation for domain={proposal.domain!r}, "
            f"action={proposal.requested_action!r}. "
            "All authority steps are pending: "
            + " → ".join(proposal.next_required_authority)
            + ". Human confirmation required before any execution can proceed."
        )

    return AuthorityPreparationRequest(
        proposal_id=proposal.proposal_id,
        user_intent=proposal.user_intent,
        domain=proposal.domain,
        requested_action=proposal.requested_action,
        resource=proposal.resource,
        capability_name=proposal.capability_name,
        capability_scope=proposal.capability_scope,
        delegated_seat_ref=proposal.delegated_seat_ref,
        provider_name=proposal.provider_name,
        model_name=proposal.model_name,
        requires_human_confirmation=proposal.requires_human_confirmation,
        required_authority_chain=proposal.next_required_authority,
        # All authority refs pending — not issued by this function
        policy_decision_ref=None,
        capability_token_ref=None,
        operation_binding_ref=None,
        authorized_plan_ref=None,
        police_decision_ref=None,
        status=status,
        # Safety invariants — always False/True
        execution_allowed=False,
        used_execution=False,
        cognitive_only=True,
        notes=notes,
    )
