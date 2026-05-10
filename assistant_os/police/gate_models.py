from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


def _new_id() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


class PoliceOutcome(str, Enum):
    PERMITTED = "permitted"
    DENIED = "denied"
    DEFERRED = "deferred"


class PoliceReason(str, Enum):
    ALLOWED = "allowed"
    TOKEN_MISSING = "token_missing"
    TOKEN_INVALID = "token_invalid"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_ALREADY_CONSUMED = "token_already_consumed"
    BINDING_MISMATCH = "binding_mismatch"
    BINDING_REF_MISSING = "binding_ref_missing"
    PLAN_BINDING_FAILURE = "plan_binding_failure"
    GOVERNANCE_REF_MISSING = "governance_ref_missing"
    POLICY_DECISION_REF_MISSING = "policy_decision_ref_missing"
    CAPABILITY_OUT_OF_SCOPE = "capability_out_of_scope"
    DELEGATED_SEAT_INVALID = "delegated_seat_invalid"
    TEMPORAL_RESTRICTION = "temporal_restriction"
    CONFIRMATION_REQUIRED = "confirmation_required"
    GATE_NOT_IMPLEMENTED = "gate_not_implemented"


@dataclass(frozen=True, kw_only=True)
class PoliceGateRequest:
    execution_id: str
    operation_key: str
    token_ref: str | None
    binding_ref: str | None
    authorized_plan_ref: str | None
    capability_name: str
    governance_ref: str | None
    policy_decision_ref: str | None
    trace_id: str
    delegated_seat_ref: str | None = None
    delegated_seat_action: str | None = None
    delegated_seat_required: bool = False
    active_restriction_refs: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.created_at or not _is_timezone_aware(self.created_at):
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True, kw_only=True)
class PoliceDecision:
    decision_id: str = field(default_factory=_new_id)
    execution_id: str
    trace_id: str
    outcome: PoliceOutcome
    reason: PoliceReason
    detail: str
    permitted: bool
    checked_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("decision_id must be non-empty")
        if not self.execution_id:
            raise ValueError("execution_id must be non-empty")
        if not self.trace_id:
            raise ValueError("trace_id must be non-empty")
        if not self.detail:
            raise ValueError("detail must be non-empty")
        if not self.checked_at or not _is_timezone_aware(self.checked_at):
            raise ValueError("checked_at must be timezone-aware")
        if self.permitted is not (self.outcome is PoliceOutcome.PERMITTED):
            raise ValueError("permitted must be True iff outcome is PERMITTED")
