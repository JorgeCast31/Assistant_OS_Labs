"""
Plan model — sovereign operator intent record, pre-authority.

A Plan is a structured, non-executing cognitive intent record produced by
Mission Control's Planner before any authority chain is engaged.

Design
------
This is intentionally NOT:
  - a PreparedAction          (queued for authority review)
  - an MSOExecutionProposal   (cognitive orchestrator output)
  - an AuthorityPreparationRequest (MSO-internal bridge artifact)
  - an AuthorizedPlan         (execution binding)
  - a PolicyDecision          (policy verdict)
  - a PoliceDecision          (police gate verdict)
  - a CapabilityToken         (execution capability)
  - an AuthorityArtifact      (any execution authority object)
  - an execution result       (something that ran)

This IS:
  - a human-authored operator intent record
  - held in the Draft Store (pre-authority, pre-MSO-escalation)
  - expressing what the operator wants to do before anyone decides if allowed
  - always pre-authority: no authority refs, no execution fields

Invariants (enforced by __post_init__, not negotiable)
------------------------------------------------------
  schema_version  = "1"  (any other value raises UnknownSchemaVersion)
  state           ∈ {"draft", "planning", "mso_review"}
  plan_id         must start with "plan_"

Prohibited fields (must never appear on PlanRecord)
---------------------------------------------------
  execution_allowed, execution_status, executionState, used_execution,
  policy_decision_ref, governance_ref, capability_token_ref,
  authority_artifact_ref, runner_ref, mission_id, prepared_action_id,
  any field containing "auto:" pattern.

Sprint: #228 — Draft Persistence Implementation, no prepare.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------

PlanState = Literal["draft", "planning", "mso_review"]
PlanRiskLevel = Literal["low", "medium", "high", "critical"]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PlanNotFound(KeyError):
    """No plan with this plan_id in the store."""


class InvalidTransition(ValueError):
    """The requested state transition is not permitted."""


class UnknownSchemaVersion(ValueError):
    """Fail-closed: encountered a schema_version this code does not understand."""


class InvalidPlanId(ValueError):
    """plan_id does not match the canonical format plan_<timestamp_ms>_<uuid4_short>."""


class PlanImmutable(ValueError):
    """Plan is in mso_review state and cannot be mutated."""


class OperatorSeatMismatch(PermissionError):
    """The requesting operator_seat does not own this plan."""


class InvalidPlanState(ValueError):
    """Plan state value is not in the permitted set."""


# ---------------------------------------------------------------------------
# Permitted transitions
# ---------------------------------------------------------------------------

# (from_state, to_state) → allowed
_PERMITTED_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("draft", "planning"),
    ("planning", "draft"),
    ("planning", "mso_review"),
})


def is_transition_allowed(from_state: str, to_state: str) -> bool:
    """Return True if the transition is in the permitted set."""
    return (from_state, to_state) in _PERMITTED_TRANSITIONS


# ---------------------------------------------------------------------------
# Domain dataclasses
# ---------------------------------------------------------------------------

_VALID_STATES: frozenset[str] = frozenset({"draft", "planning", "mso_review"})
_VALID_RISK_LEVELS: frozenset[str] = frozenset({"low", "medium", "high", "critical"})


@dataclass(frozen=True)
class PlanRecord:
    """Immutable snapshot of a Plan as stored and returned from the Draft Store.

    source: draft_store — not backend_read_model, not authority artifact.
    """

    plan_id: str
    title: str
    intent_summary: str
    domain: str
    state: PlanState
    operator_seat: str
    schema_version: str        # must be "1"
    created_at: str            # ISO 8601 UTC
    updated_at: str            # ISO 8601 UTC
    risk_level: Optional[PlanRiskLevel] = None
    target_actions: tuple[str, ...] = ()   # free-form strings, no capability registry coupling
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise UnknownSchemaVersion(
                f"Unknown schema_version '{self.schema_version}'. "
                "Fail-closed: this code only understands schema_version='1'."
            )
        if self.state not in _VALID_STATES:
            raise InvalidPlanState(
                f"Invalid Plan state: '{self.state}'. "
                f"Permitted: {sorted(_VALID_STATES)}"
            )
        if not self.plan_id.startswith("plan_"):
            raise InvalidPlanId(
                f"plan_id '{self.plan_id}' does not start with 'plan_'. "
                "Expected format: plan_<timestamp_ms>_<uuid4_short>."
            )
        if self.risk_level is not None and self.risk_level not in _VALID_RISK_LEVELS:
            raise ValueError(
                f"Invalid risk_level: '{self.risk_level}'. "
                f"Permitted: {sorted(_VALID_RISK_LEVELS)}"
            )

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON transport or storage."""
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "intent_summary": self.intent_summary,
            "domain": self.domain,
            "state": self.state,
            "operator_seat": self.operator_seat,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "risk_level": self.risk_level,
            "target_actions": list(self.target_actions),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanRecord":
        """Deserialize from a plain dict. Raises on unknown schema_version."""
        return cls(
            plan_id=data["plan_id"],
            title=data["title"],
            intent_summary=data["intent_summary"],
            domain=data["domain"],
            state=data["state"],
            operator_seat=data["operator_seat"],
            schema_version=data.get("schema_version", "1"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            risk_level=data.get("risk_level"),
            target_actions=tuple(data.get("target_actions", [])),
            notes=data.get("notes"),
        )


@dataclass(frozen=True)
class PlanUpdate:
    """Fields that may be mutated on a non-frozen Plan.

    Prohibited fields are not present by design.
    State is NOT here — use transition_plan() to change state.
    """

    title: Optional[str] = None
    intent_summary: Optional[str] = None
    domain: Optional[str] = None
    risk_level: Optional[PlanRiskLevel] = None
    target_actions: Optional[tuple[str, ...]] = None
    notes: Optional[str] = None

    # Explicitly excluded (must never appear here):
    #   state, plan_id, operator_seat, schema_version, created_at, updated_at
    #   execution_allowed, execution_status, used_execution,
    #   policy_decision_ref, governance_ref, capability_token_ref,
    #   authority_artifact_ref, runner_ref, mission_id, prepared_action_id

    def is_empty(self) -> bool:
        """Return True if no fields are set."""
        return all(v is None for v in (
            self.title, self.intent_summary, self.domain,
            self.risk_level, self.target_actions, self.notes,
        ))


@dataclass(frozen=True)
class PlanAuditEntry:
    """Immutable audit log entry for a Plan."""

    audit_id: str
    plan_id: str
    event: str             # see AUDIT_EVENTS below
    from_state: Optional[str]
    to_state: Optional[str]
    operator_seat: str
    occurred_at: str       # ISO 8601 UTC
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "audit_id": self.audit_id,
            "plan_id": self.plan_id,
            "event": self.event,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "operator_seat": self.operator_seat,
            "occurred_at": self.occurred_at,
            "notes": self.notes,
        }


# Permitted audit event names
AUDIT_EVENTS: frozenset[str] = frozenset({
    "created",
    "state_transition",
    "updated",
    "abandoned_from_planning",
    "escalated_to_mso_review",
})
