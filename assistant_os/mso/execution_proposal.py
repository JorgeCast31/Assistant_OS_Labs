"""
MSOExecutionProposal — non-executing cognitive orchestration artifact.

The Delegated MSO Seat produces this artifact in response to plan_request
interactions. It is the output of the *cognitive orchestrator*, NOT an
execution result.

Design
------
This is intentionally NOT:
  - an AuthorizedPlan          (execution binding)
  - a PolicyDecision           (policy verdict)
  - a PoliceDecision           (police gate verdict)
  - a CapabilityToken          (execution capability)
  - an OperationBinding        (action fingerprint)
  - an execution result        (something that ran)

This IS:
  - a structured cognitive planning artifact
  - produced by the seated model provider
  - expressing intent, domain, required authority chain, and risk level
  - always cognitive_only=True, used_execution=False, execution_allowed=False

Invariants (enforced by __post_init__, not negotiable)
------------------------------------------------------
  cognitive_only     = True   (always)
  used_execution     = False  (always)
  execution_allowed  = False  (always)

These invariants cannot be set to any other value. __post_init__ raises
ValueError if construction is attempted with any other value.

Authority chain required before ANY execution can occur
--------------------------------------------------------
  1. PolicyDecision
  2. CapabilityToken
  3. OperationBinding
  4. AuthorizedPlan
  5. PoliceGate

This proposal declares that chain in next_required_authority. It does not
satisfy any step of that chain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4


# ---------------------------------------------------------------------------
# Required authority chain — canonical order
# ---------------------------------------------------------------------------

REQUIRED_AUTHORITY_CHAIN: tuple[str, ...] = (
    "PolicyDecision",
    "CapabilityToken",
    "OperationBinding",
    "AuthorizedPlan",
    "PoliceGate",
)


# ---------------------------------------------------------------------------
# MSOExecutionProposal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MSOExecutionProposal:
    """
    Non-executing cognitive orchestration artifact produced by Delegated MSO Seat.

    This dataclass is frozen (immutable). The three safety invariants
    (cognitive_only, used_execution, execution_allowed) are enforced in
    __post_init__ and cannot be overridden after construction.

    Fields
    ------
    proposal_id : str
        Unique identifier for this proposal. Auto-generated UUID if not provided.

    user_intent : str
        The original user request or intent as received by the seat.

    domain : str
        Classified domain for this proposal (e.g., "CODE", "FIN", "WORK",
        "ASSISTANT", "UNKNOWN").

    requested_action : str
        The action the user is requesting (e.g., "CODE_REVIEW", "FIN_EXPENSE").
        Empty string if domain classification could not resolve a specific action.

    capability_name : str
        Name of the capability that would be required for execution
        (e.g., "code_review", "code_fix"). Empty if no specific capability needed.

    capability_scope : tuple[str, ...]
        Ordered list of capability scope values required (e.g., ("code_review",)).
        Empty tuple if no specific capability is declared.

    risk_level : str
        Assessed risk: "low" | "medium" | "high" | "unknown".

    requires_human_confirmation : bool
        Whether execution of this proposal would require explicit human approval.
        Always True for execution-class proposals from the seat.

    delegated_seat_ref : Optional[str]
        The seat reference that produced this proposal, for traceability.

    provider_name : Optional[str]
        Name of the cognitive provider that produced or contributed to the proposal.

    model_name : Optional[str]
        Specific model that contributed plan text, if applicable.

    plan_steps : tuple[str, ...]
        Ordered description of what the proposed execution would involve.
        These are informational — not instructions to execute.

    execution_allowed : bool
        INVARIANT: always False. Enforced in __post_init__.
        This proposal does not authorize execution.

    used_execution : bool
        INVARIANT: always False. Enforced in __post_init__.
        No execution was performed to produce this proposal.

    cognitive_only : bool
        INVARIANT: always True. Enforced in __post_init__.
        This is a pure cognitive artifact.

    next_required_authority : tuple[str, ...]
        The full authority chain that must be satisfied before any execution
        can occur. Canonical order: PolicyDecision, CapabilityToken,
        OperationBinding, AuthorizedPlan, PoliceGate.

    notes : str
        Human-readable rationale, context, or warnings about this proposal.

    artifact_type : str
        Constant identifier for this artifact type. Always "mso_execution_proposal".
    """

    # Identity
    proposal_id: str = field(default_factory=lambda: f"proposal-{uuid4()}")

    # Intent / classification
    user_intent: str = ""
    domain: str = "UNKNOWN"
    requested_action: str = ""

    # Capability declaration
    capability_name: str = ""
    capability_scope: tuple[str, ...] = field(default_factory=tuple)

    # Risk and confirmation
    risk_level: str = "unknown"
    requires_human_confirmation: bool = True

    # Traceability
    delegated_seat_ref: Optional[str] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None

    # Plan content (informational only)
    plan_steps: tuple[str, ...] = field(default_factory=tuple)

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    used_execution: bool = False
    cognitive_only: bool = True

    # Authority chain
    next_required_authority: tuple[str, ...] = field(
        default_factory=lambda: REQUIRED_AUTHORITY_CHAIN
    )

    # Notes / rationale
    notes: str = ""

    # Artifact type tag
    artifact_type: str = "mso_execution_proposal"

    def __post_init__(self) -> None:
        """Enforce non-negotiable safety invariants."""
        if self.execution_allowed is not False:
            raise ValueError(
                "MSOExecutionProposal.execution_allowed must always be False. "
                "This proposal is a cognitive planning artifact, not an execution authorization."
            )
        if self.used_execution is not False:
            raise ValueError(
                "MSOExecutionProposal.used_execution must always be False. "
                "No execution is performed to produce an orchestration proposal."
            )
        if self.cognitive_only is not True:
            raise ValueError(
                "MSOExecutionProposal.cognitive_only must always be True. "
                "This artifact is purely cognitive."
            )

    def to_dict(self) -> dict:
        """Serialize proposal for audit/transport. Never includes secrets."""
        return {
            "artifact_type": self.artifact_type,
            "proposal_id": self.proposal_id,
            "user_intent": self.user_intent,
            "domain": self.domain,
            "requested_action": self.requested_action,
            "capability_name": self.capability_name,
            "capability_scope": list(self.capability_scope),
            "risk_level": self.risk_level,
            "requires_human_confirmation": self.requires_human_confirmation,
            "delegated_seat_ref": self.delegated_seat_ref,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "plan_steps": list(self.plan_steps),
            "execution_allowed": self.execution_allowed,
            "used_execution": self.used_execution,
            "cognitive_only": self.cognitive_only,
            "next_required_authority": list(self.next_required_authority),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_execution_proposal(
    *,
    user_intent: str,
    domain: str = "UNKNOWN",
    requested_action: str = "",
    capability_name: str = "",
    capability_scope: tuple[str, ...] = (),
    risk_level: str = "unknown",
    requires_human_confirmation: bool = True,
    delegated_seat_ref: Optional[str] = None,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    plan_steps: tuple[str, ...] = (),
    notes: str = "",
) -> MSOExecutionProposal:
    """
    Build a validated MSOExecutionProposal with all safety invariants enforced.

    This is the canonical constructor — always use this instead of calling
    MSOExecutionProposal() directly, unless you have explicit test reasons.

    Parameters
    ----------
    user_intent : str
        The original user request or intent text.
    domain : str
        Classified domain (e.g., "CODE", "FIN", "WORK", "ASSISTANT", "UNKNOWN").
    requested_action : str
        Specific action within domain (e.g., "CODE_REVIEW"). Empty if unknown.
    capability_name : str
        Required capability name for execution. Empty if not applicable.
    capability_scope : tuple[str, ...]
        Capability scope values required for execution.
    risk_level : str
        "low" | "medium" | "high" | "unknown"
    requires_human_confirmation : bool
        Whether human approval is required before any execution.
    delegated_seat_ref : Optional[str]
        The seat that produced this proposal, for traceability.
    provider_name : Optional[str]
        The cognitive provider that contributed to the proposal.
    model_name : Optional[str]
        The specific model that contributed plan text.
    plan_steps : tuple[str, ...]
        Informational description of what the proposed execution would involve.
    notes : str
        Human-readable rationale or warnings.

    Returns
    -------
    MSOExecutionProposal
        Immutable, frozen proposal with all invariants enforced.
    """
    return MSOExecutionProposal(
        user_intent=user_intent,
        domain=domain,
        requested_action=requested_action,
        capability_name=capability_name,
        capability_scope=capability_scope,
        risk_level=risk_level,
        requires_human_confirmation=requires_human_confirmation,
        delegated_seat_ref=delegated_seat_ref,
        provider_name=provider_name,
        model_name=model_name,
        plan_steps=plan_steps,
        execution_allowed=False,
        used_execution=False,
        cognitive_only=True,
        next_required_authority=REQUIRED_AUTHORITY_CHAIN,
        notes=notes,
    )


def build_safe_fallback_proposal(
    *,
    user_intent: str,
    reason: str = "provider not available",
    delegated_seat_ref: Optional[str] = None,
) -> MSOExecutionProposal:
    """
    Build a safe deterministic fallback proposal when provider is unavailable.

    This is always returned instead of raising an exception. Fail-safe: the
    proposal is valid, cognitive_only, and declares the authority chain.

    Parameters
    ----------
    user_intent : str
        The original user request.
    reason : str
        Reason for fallback (e.g., "provider not configured").
    delegated_seat_ref : Optional[str]
        Seat reference for traceability.

    Returns
    -------
    MSOExecutionProposal
        Safe fallback proposal with unknown domain and full authority chain.
    """
    return MSOExecutionProposal(
        user_intent=user_intent,
        domain="UNKNOWN",
        requested_action="",
        capability_name="",
        capability_scope=(),
        risk_level="unknown",
        requires_human_confirmation=True,
        delegated_seat_ref=delegated_seat_ref,
        provider_name=None,
        model_name=None,
        plan_steps=(
            "Cognitive provider unavailable — deterministic fallback proposal.",
            "No action can be proposed without a configured seat provider.",
            "To proceed: configure MSO_SEAT_PROVIDER and ensure provider is reachable.",
        ),
        execution_allowed=False,
        used_execution=False,
        cognitive_only=True,
        next_required_authority=REQUIRED_AUTHORITY_CHAIN,
        notes=f"Fallback proposal. Reason: {reason}",
    )
