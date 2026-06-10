"""
ConfirmablePreparedAction — non-executing CODE/docs prepared action waiting for human confirmation.

This is the next artifact in the authority chain after AuthorityPreparationRequest:

    MSOExecutionProposal
    → AuthorityPreparationRequest       (authority review preparation; all authority pending)
    → ConfirmablePreparedAction         (waiting_for_human_confirmation; no execution)
    → [human reviews and explicitly confirms — separate governed step, not implemented here]
    → [authority chain: PolicyDecision → CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate]
    → [execution, only after full authority]

Sprint scope: CODE/docs prepared action review only.

Design
------
This artifact is intentionally NOT:
  - executing anything
  - calling the runner or any pipeline
  - issuing CapabilityToken
  - creating AuthorizedPlan
  - calling PoliceGate
  - bypassing PolicyDecision, CapabilityToken, OperationBinding, AuthorizedPlan, PoliceGate
  - enabling HOST, MACHINE_OPERATOR, or OpenClaw

This IS:
  - a structured representation of a CODE/docs prepared action for human review
  - derived from AuthorityPreparationRequest via build_confirmable_from_preparation()
  - always status="waiting_for_human_confirmation" at creation
  - always cognitive_only=True, used_execution=False, execution_allowed=False
  - always confirmed=False (confirmation is a separate governed step outside this module)

Invariants (enforced by __post_init__, not negotiable)
------------------------------------------------------
  cognitive_only    = True   (always)
  used_execution    = False  (always)
  execution_allowed = False  (always)
  confirmed         = False  (always — confirmation is not issued here)
  status            = "waiting_for_human_confirmation" (always at creation)

Non-goals for this sprint
--------------------------
  - Do not execute the prepared action.
  - Do not call runner.
  - Do not call pipelines.
  - Do not issue CapabilityToken.
  - Do not create real AuthorizedPlan.
  - Do not call PoliceGate.
  - Do not enable HOST, MACHINE_OPERATOR, or OpenClaw.
  - Do not add UI approve/execute controls.
  - Do not implement temporal restrictions.
  - Do not make live API calls.
  - Do not store secrets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional
from uuid import uuid4

from .authority_preparation import AuthorityPreparationRequest


# ---------------------------------------------------------------------------
# ConfirmablePreparedAction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfirmablePreparedAction:
    """
    Non-executing CODE/docs prepared action waiting for explicit human confirmation.

    Derived from AuthorityPreparationRequest via build_confirmable_from_preparation().
    This artifact represents a prepared plan that a human must review before any
    execution authority can proceed. It never issues tokens, never creates
    AuthorizedPlan, never calls Police, never executes.

    Fields
    ------
    action_id : str
        Unique identifier for this confirmable action. Auto-generated UUID.

    preparation_id : str
        ID of the source AuthorityPreparationRequest.

    proposal_id : str
        ID of the source MSOExecutionProposal (traced through preparation).

    user_intent : str
        The original user intent copied from the preparation.

    domain : str
        Classified domain copied from the preparation.

    requested_action : str
        Requested action copied from the preparation.

    capability_name : str
        Required capability name copied from the preparation.

    capability_scope : tuple[str, ...]
        Capability scope values copied from the preparation.

    plan_steps : tuple[str, ...]
        Informational description of what the proposed execution would involve.
        These are for human review only — NOT instructions to execute.

    risk_level : str
        Assessed risk level: "low" | "medium" | "high" | "unknown".

    pending_authority_steps : tuple[str, ...]
        Authority steps still pending (copied from preparation).
        All steps are pending at this stage.

    delegated_seat_ref : Optional[str]
        Seat reference for traceability.

    provider_name : Optional[str]
        Provider name for traceability.

    model_name : Optional[str]
        Model name for traceability.

    action_type : str
        Scope tag for this sprint: always "code_docs".

    status : str
        INVARIANT: always "waiting_for_human_confirmation".
        This artifact is the waiting state — human confirmation is not provided here.

    execution_allowed : bool
        INVARIANT: always False. This artifact does not authorize execution.

    used_execution : bool
        INVARIANT: always False. No execution was performed to produce this artifact.

    cognitive_only : bool
        INVARIANT: always True. This is a cognitive/preparation artifact.

    confirmed : bool
        INVARIANT: always False. Confirmation is a separate governed step outside
        this module. This artifact only represents the waiting state.

    notes : str
        Human-readable explanation of the pending confirmation requirement.

    artifact_type : str
        Constant: "confirmable_prepared_action".
    """

    # Identity
    action_id: str = field(default_factory=lambda: f"cpa-{uuid4()}")
    preparation_id: str = ""
    proposal_id: str = ""

    # Intent / classification (copied from preparation)
    user_intent: str = ""
    domain: str = "UNKNOWN"
    requested_action: str = ""

    # Resource (optional governed target, e.g. repo URL). Backward compatible.
    resource: Optional[str] = None

    # Capability (copied from preparation)
    capability_name: str = ""
    capability_scope: tuple[str, ...] = field(default_factory=tuple)

    # Plan content (informational only — NOT instructions to execute)
    plan_steps: tuple[str, ...] = field(default_factory=tuple)

    # Risk
    risk_level: str = "unknown"

    # Pending authority (copied from preparation)
    pending_authority_steps: tuple[str, ...] = field(default_factory=tuple)

    # Traceability (copied from preparation)
    delegated_seat_ref: Optional[str] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None

    # Sprint scope tag
    action_type: str = "code_docs"

    # Status — INVARIANT: always "waiting_for_human_confirmation"
    status: str = "waiting_for_human_confirmation"

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    used_execution: bool = False
    cognitive_only: bool = True
    confirmed: bool = False

    # Notes
    notes: str = ""

    # Artifact type tag
    artifact_type: str = "confirmable_prepared_action"

    def __post_init__(self) -> None:
        """Enforce non-negotiable safety invariants."""
        if self.execution_allowed is not False:
            raise ValueError(
                "ConfirmablePreparedAction.execution_allowed must always be False. "
                "This artifact is a waiting-for-confirmation record; it does not authorize execution."
            )
        if self.used_execution is not False:
            raise ValueError(
                "ConfirmablePreparedAction.used_execution must always be False. "
                "No execution is performed to produce a confirmable prepared action."
            )
        if self.cognitive_only is not True:
            raise ValueError(
                "ConfirmablePreparedAction.cognitive_only must always be True. "
                "This artifact is a cognitive/preparation record, not an execution result."
            )
        if self.confirmed is not False:
            raise ValueError(
                "ConfirmablePreparedAction.confirmed must always be False. "
                "Confirmation is a separate governed step. This artifact only represents "
                "the waiting_for_human_confirmation state."
            )
        if self.status != "waiting_for_human_confirmation":
            raise ValueError(
                "ConfirmablePreparedAction.status must always be "
                "'waiting_for_human_confirmation'. "
                "This artifact is created in the waiting state only."
            )

    def to_dict(self) -> dict:
        """Serialize for audit/transport. Never includes secrets."""
        return {
            "artifact_type": self.artifact_type,
            "action_id": self.action_id,
            "preparation_id": self.preparation_id,
            "proposal_id": self.proposal_id,
            "user_intent": self.user_intent,
            "domain": self.domain,
            "requested_action": self.requested_action,
            "resource": self.resource,
            "capability_name": self.capability_name,
            "capability_scope": list(self.capability_scope),
            "plan_steps": list(self.plan_steps),
            "risk_level": self.risk_level,
            "pending_authority_steps": list(self.pending_authority_steps),
            "delegated_seat_ref": self.delegated_seat_ref,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "action_type": self.action_type,
            "status": self.status,
            "execution_allowed": self.execution_allowed,
            "used_execution": self.used_execution,
            "cognitive_only": self.cognitive_only,
            "confirmed": self.confirmed,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Builder: AuthorityPreparationRequest → ConfirmablePreparedAction
# ---------------------------------------------------------------------------


def build_confirmable_from_preparation(
    preparation: AuthorityPreparationRequest,
    *,
    plan_steps: tuple[str, ...] = (),
    risk_level: str = "unknown",
) -> ConfirmablePreparedAction:
    """
    Map an AuthorityPreparationRequest to a ConfirmablePreparedAction.

    Pure function — no side effects, no I/O, no network, no token issuance,
    no AuthorizedPlan creation, no Police calls, no runner/pipeline invocation.

    The returned artifact:
    - copies identity/intent/domain/capability/scope/traceability from preparation
    - preserves cognitive_only=True, used_execution=False, execution_allowed=False
    - sets confirmed=False (confirmation is not issued here)
    - sets status="waiting_for_human_confirmation" (invariant)
    - includes pending_authority_steps from the preparation
    - accepts optional plan_steps (informational, not executable)
    - accepts optional risk_level for human review

    Blocked preparations are accepted — the artifact still enters
    waiting_for_human_confirmation with a note describing the block.
    Human review of a blocked preparation is valid; it prevents accidental
    execution of unclassified intents.

    Parameters
    ----------
    preparation : AuthorityPreparationRequest
        The source authority preparation record.
    plan_steps : tuple[str, ...]
        Informational plan steps for human review. NOT instructions to execute.
        Typically copied from the source MSOExecutionProposal.
    risk_level : str
        Risk assessment: "low" | "medium" | "high" | "unknown".

    Returns
    -------
    ConfirmablePreparedAction
        Immutable confirmable action with status=waiting_for_human_confirmation.

    Raises
    ------
    TypeError
        If preparation is not an AuthorityPreparationRequest instance.
    """
    if not isinstance(preparation, AuthorityPreparationRequest):
        raise TypeError(
            f"build_confirmable_from_preparation requires AuthorityPreparationRequest, "
            f"got {type(preparation).__name__!r}."
        )

    pending_steps = tuple(preparation.pending_authority_steps)

    if preparation.status == "blocked":
        notes = (
            f"Confirmable action derived from BLOCKED preparation (preparation_id={preparation.preparation_id!r}). "
            "The source preparation was blocked due to missing or invalid proposal data. "
            "Human review required before any authority chain can proceed. "
            "Resolve the block before confirming. "
            f"Pending authority: {' → '.join(pending_steps) if pending_steps else 'none declared'}."
        )
    else:
        notes = (
            f"CODE/docs prepared action for domain={preparation.domain!r}, "
            f"action={preparation.requested_action!r}. "
            "Waiting for explicit human confirmation before any execution authority can proceed. "
            f"Pending authority steps: {' → '.join(pending_steps) if pending_steps else 'none declared'}. "
            "This artifact does not execute, does not issue tokens, "
            "and does not authorize any action."
        )

    return ConfirmablePreparedAction(
        preparation_id=preparation.preparation_id,
        proposal_id=preparation.proposal_id,
        user_intent=preparation.user_intent,
        domain=preparation.domain,
        requested_action=preparation.requested_action,
        resource=preparation.resource,
        capability_name=preparation.capability_name,
        capability_scope=preparation.capability_scope,
        plan_steps=plan_steps,
        risk_level=risk_level,
        pending_authority_steps=pending_steps,
        delegated_seat_ref=preparation.delegated_seat_ref,
        provider_name=preparation.provider_name,
        model_name=preparation.model_name,
        action_type="code_docs",
        status="waiting_for_human_confirmation",
        execution_allowed=False,
        used_execution=False,
        cognitive_only=True,
        confirmed=False,
        notes=notes,
    )
