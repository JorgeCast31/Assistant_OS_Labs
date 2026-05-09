"""
Delegated MSO Seat Contract — Process-Local Authority Binding.

Pure data types for delegable MSO seat recognition. No logic, no I/O, no LLM.

Design
------
A DelegatedMSOSeat is a formal contract that grants bounded, revocable authority
to an external agent (GPT, Claude, human, etc.) to perform specific operations
within the Assistant_OS_Labs execution system.

Seats are:
- Identifiable (seat_id, holder)
- Scoped (explicit list of allowed operations)
- Revocable (can be withdrawn at any time)
- Auditable (every action traced to seat_id + audit_ref)
- Temporal (can expire based on TTL)
- Restrictive (cannot directly execute, bypass policy, or invoke MACHINE_OPERATOR)

Constraints (Mirrored from Delegation Spec)
--------------------------------------------
- No persistence (process-local, in-memory only)
- No persistence across restarts (seats re-issued by kernel on startup)
- No caching of seat state (every action queries MSOSeatRegistry for fresh state)
- Fail-closed: invalid/expired/revoked seat → DENY
- Seat status changes are atomic (no partial updates)
- Audit ref is immutable once issued
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MSOSeatType(str, Enum):
    """Classification of delegated MSO seat holder."""

    GPT_CONVERSATIONAL = "gpt_conversational"  # GPT-4, GPT-4-turbo (advisory/conversational)
    CLAUDE_ANALYTICAL = "claude_analytical"  # Claude Opus, Sonnet (analytical/developer)
    HUMAN_OPERATOR = "human_operator"  # Human user (direct authority)
    EXTERNAL_MODEL = "external_model"  # Other model or system
    SERVICE_ACCOUNT = "service_account"  # System service


class MSOSeatScope(str, Enum):
    """Allowed operations for a delegated MSO seat."""

    PLAN = "plan"  # Propose plans, analyses
    AUDIT = "audit"  # Review logs, trace authority
    CLASSIFY = "classify"  # Categorize issues
    RECOMMEND = "recommend"  # Suggest actions
    PREPARE_EXECUTION_REQUEST = (
        "prepare_execution_request"  # Prepare AuthorizedPlan for execution
    )


class MSOSeatStatus(str, Enum):
    """Lifecycle state of a delegated MSO seat."""

    ACTIVE = "active"  # Seat is valid and usable
    EXPIRED = "expired"  # TTL exceeded
    REVOKED = "revoked"  # Explicitly revoked
    SUSPENDED = "suspended"  # Temporarily suspended
    PENDING_APPROVAL = "pending_approval"  # Awaiting authorization


# ---------------------------------------------------------------------------
# DelegatedMSOSeat Contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DelegatedMSOSeat:
    """
    Formal delegated MSO seat contract.

    Represents a bounded, auditable, revocable authority grant to an external
    agent (model, human, service) to perform specific operations.

    Fields
    ------
    seat_id : str
        Unique identifier for this seat. Typically a UUID or qualified name.

    seat_type : MSOSeatType
        Classification of seat holder (gpt, claude, human, etc.).

    holder : str
        Identity of the agent occupying the seat (e.g., "gpt-4", "claude-opus",
        "user@example.com"). Must be non-empty.

    issued_by : str
        Principal that issued this seat (e.g., "kernel", "human_operator").
        Provides audit trail for seat origin.

    issued_at : datetime
        ISO 8601 timestamp (timezone-aware) when seat was issued.
        Must be before expires_at (if set).

    scope : tuple[MSOSeatScope, ...]
        Immutable tuple of allowed operations. Checked at every action.
        Valid values: plan, audit, classify, recommend, prepare_execution_request.
        Empty scope means seat has no permissions (effectively revoked).

    forbidden_actions : tuple[str, ...]
        Immutable tuple of explicitly prohibited actions beyond scope.
        Examples: "direct_execution", "invoke_machine_operator", "modify_policy".
        These are checked in addition to scope validation.

    requires_policy : bool
        If True, actions from this seat must pass PolicyDecision.evaluate().
        If False, policy check is skipped (not recommended except for diagnostic seats).

    requires_police : bool
        If True, actions from this seat must pass Police.check().
        Note: Police gate is not yet implemented (S-POLICE-CORE-03 pending).
        This flag documents the requirement for future enforcement.

    requires_human_approval : bool
        If True, certain actions from this seat require explicit human confirmation.
        Used for high-impact operations (e.g., prepare_execution_request for dangerous plans).

    status : MSOSeatStatus
        Current lifecycle state: active, expired, revoked, suspended, pending_approval.

    expires_at : Optional[datetime]
        Optional TTL. If set, seat is automatically considered expired when
        expires_at < now(). Must be timezone-aware if set. Must be after issued_at.

    revoked_at : Optional[datetime]
        If set, seat has been revoked at this timestamp. Immutable once set.
        If revoked_at is set, status MUST be REVOKED.

    audit_ref : str
        Unique reference to the audit log entry that created this seat.
        Immutable, non-empty, used for traceability.

    revocation_reason : Optional[str]
        If revoked, the reason for revocation (e.g., "Security incident", "TTL cleanup").
        Immutable once revoked.
    """

    # Identity
    seat_id: str
    seat_type: MSOSeatType
    holder: str
    issued_by: str

    # Timing
    issued_at: datetime
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    # Scope and Restrictions
    scope: tuple[MSOSeatScope, ...] = field(default_factory=tuple)
    forbidden_actions: tuple[str, ...] = field(default_factory=tuple)

    # Authority Requirements
    requires_policy: bool = True
    requires_police: bool = True
    requires_human_approval: bool = False

    # Lifecycle
    status: MSOSeatStatus = MSOSeatStatus.ACTIVE

    # Audit
    audit_ref: str = field(default_factory=lambda: str(uuid4()))
    revocation_reason: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate seat contract on construction."""
        self.validate()

    def validate(self) -> None:
        """
        Validate all required fields and constraints.

        Raises
        ------
        ValueError — with descriptive message for first failing check.
        """
        # Identity checks
        if not self.seat_id or not self.seat_id.strip():
            raise ValueError("DelegatedMSOSeat.seat_id must be non-empty")

        if not self.holder or not self.holder.strip():
            raise ValueError("DelegatedMSOSeat.holder must be non-empty")

        if not self.issued_by or not self.issued_by.strip():
            raise ValueError("DelegatedMSOSeat.issued_by must be non-empty")

        # Timestamp checks
        if not self.issued_at:
            raise ValueError("DelegatedMSOSeat.issued_at is required")

        if not _is_timezone_aware(self.issued_at):
            raise ValueError("DelegatedMSOSeat.issued_at must be timezone-aware")

        if self.expires_at is not None:
            if not _is_timezone_aware(self.expires_at):
                raise ValueError("DelegatedMSOSeat.expires_at must be timezone-aware")

            if self.expires_at <= self.issued_at:
                raise ValueError(
                    "DelegatedMSOSeat.expires_at must be after issued_at"
                )

        # Scope checks
        if not self.scope:
            raise ValueError("DelegatedMSOSeat.scope must be non-empty")

        for op in self.scope:
            if not isinstance(op, MSOSeatScope):
                raise ValueError(
                    f"DelegatedMSOSeat.scope contains invalid operation: {op}"
                )

        # Audit checks
        if not self.audit_ref or not self.audit_ref.strip():
            raise ValueError("DelegatedMSOSeat.audit_ref must be non-empty")

        # Status consistency checks
        if self.status == MSOSeatStatus.REVOKED:
            if not self.revoked_at:
                raise ValueError(
                    "DelegatedMSOSeat.status is REVOKED but revoked_at is not set"
                )

        if self.revoked_at is not None:
            if not _is_timezone_aware(self.revoked_at):
                raise ValueError("DelegatedMSOSeat.revoked_at must be timezone-aware")

            if self.status != MSOSeatStatus.REVOKED:
                raise ValueError(
                    "DelegatedMSOSeat.revoked_at is set but status is not REVOKED"
                )

    def is_active(self) -> bool:
        """
        Check if seat is currently active (not revoked, not expired, not suspended).

        Note: This is a pure function. It does NOT consult external state or registry.
        To check if a seat is active at runtime, query MSOSeatRegistry.
        """
        if self.status == MSOSeatStatus.ACTIVE:
            if self.expires_at and self.expires_at < datetime.now(timezone.utc):
                return False  # Expired
            return True
        return False

    def is_expired(self) -> bool:
        """Check if seat has passed its TTL."""
        if not self.expires_at:
            return False
        return self.expires_at < datetime.now(timezone.utc)

    def is_revoked(self) -> bool:
        """Check if seat has been explicitly revoked."""
        return self.status == MSOSeatStatus.REVOKED or self.revoked_at is not None

    def can_perform_action(self, action: str) -> bool:
        """
        Check if this action is permitted by seat scope and forbidden_actions.

        Pure function; does NOT check registry or runtime state.

        Parameters
        ----------
        action : str
            Action to check (e.g., "plan", "audit", "direct_execution").

        Returns
        -------
        bool
            True if action is in scope and not forbidden, False otherwise.
        """
        # Check if action is explicitly forbidden
        if action in self.forbidden_actions:
            return False

        # Try to match against enum scope
        try:
            scope_enum = MSOSeatScope(action)
            return scope_enum in self.scope
        except ValueError:
            # Not an enum value, check as raw string in scope
            return action in [s.value for s in self.scope]

    def to_dict(self) -> dict:
        """Serialize seat to dict for audit/transport."""
        return {
            "seat_id": self.seat_id,
            "seat_type": self.seat_type.value,
            "holder": self.holder,
            "issued_by": self.issued_by,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "scope": [s.value for s in self.scope],
            "forbidden_actions": list(self.forbidden_actions),
            "requires_policy": self.requires_policy,
            "requires_police": self.requires_police,
            "requires_human_approval": self.requires_human_approval,
            "status": self.status.value,
            "audit_ref": self.audit_ref,
            "revocation_reason": self.revocation_reason,
        }


# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------


def _is_timezone_aware(value: datetime) -> bool:
    """Check if datetime is timezone-aware."""
    return value.tzinfo is not None and value.utcoffset() is not None


def validate_delegated_mso_seat(seat: DelegatedMSOSeat) -> None:
    """
    Standalone validation function.

    Called by DelegatedMSOSeat.__post_init__() but also available for
    runtime validation of deserialized seats.

    Parameters
    ----------
    seat : DelegatedMSOSeat
        Seat to validate.

    Raises
    ------
    ValueError
        If validation fails.
    """
    seat.validate()


def coerce_delegated_mso_seat(raw: dict) -> DelegatedMSOSeat:
    """
    Coerce raw dict to DelegatedMSOSeat with full validation.

    Used when deserializing seats from audit logs, cache, or external sources.

    Parameters
    ----------
    raw : dict
        Raw dict with seat fields.

    Returns
    -------
    DelegatedMSOSeat
        Validated seat.

    Raises
    ------
    ValueError, TypeError
        If coercion or validation fails.
    """
    # Coerce timestamps
    if isinstance(raw.get("issued_at"), str):
        raw["issued_at"] = datetime.fromisoformat(raw["issued_at"])
    if isinstance(raw.get("expires_at"), str):
        raw["expires_at"] = datetime.fromisoformat(raw["expires_at"])
    if isinstance(raw.get("revoked_at"), str):
        raw["revoked_at"] = datetime.fromisoformat(raw["revoked_at"])

    # Coerce enums
    if isinstance(raw.get("seat_type"), str):
        raw["seat_type"] = MSOSeatType(raw["seat_type"])

    if isinstance(raw.get("status"), str):
        raw["status"] = MSOSeatStatus(raw["status"])

    # Coerce scope list to tuple
    if isinstance(raw.get("scope"), list):
        raw["scope"] = tuple(MSOSeatScope(op) for op in raw["scope"])

    # Coerce forbidden_actions list to tuple
    if isinstance(raw.get("forbidden_actions"), list):
        raw["forbidden_actions"] = tuple(raw["forbidden_actions"])

    seat = DelegatedMSOSeat(**raw)
    validate_delegated_mso_seat(seat)
    return seat
