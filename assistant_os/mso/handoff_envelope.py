"""Handoff Envelope v0 — auditable package for a POSSIBLE future handoff (no dispatch).

PR: Handoff Envelope v0.

Bundles a task that COULD be handed to a recommended worker, linking a Mission
Record (#262), a Delegation Work Packet (#264), a Routing Recommendation (#266)
and an expected WorkerProfile (#265), plus input refs, constraints, expected
outputs, a verification plan and evidence refs.

WHAT THIS IS NOT
----------------
It does NOT dispatch, execute, call models, contact external APIs, run a Runner,
use a queue, mint a capability token, or grant authority. ``can_dispatch`` and
``can_execute`` are hard-wired ``False`` in v0.

> handoff envelope ≠ dispatch · dispatch ≠ execution · human_approval_ref ≠ authority ·
> evidence_refs ≠ execution proof · refs, not secrets or raw contents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class HandoffEnvelopeError(ValueError):
    """Raised when a HandoffEnvelope fails validation (fail-closed)."""


class HandoffStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED_FOR_HANDOFF = "APPROVED_FOR_HANDOFF"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    COMPLETED = "COMPLETED"


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),
    re.compile(r"(?i)(password|passwd|api[_-]?key|secret|token|bearer)\s*[:=]\s*\S"),
    re.compile(r"(?i)authorization:\s*\S"),
    re.compile(r"(?i)-----begin"),
)
_MAX_ITEM_LEN = 4096  # refs, not raw file contents


def _looks_like_secret(text: str) -> bool:
    if not isinstance(text, str) or not text:
        return False
    return any(p.search(text) for p in _SECRET_PATTERNS)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def now_iso() -> str:
    return _now_utc().isoformat()


def _coerce_enum(enum_cls, value, field_name):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        raise HandoffEnvelopeError(f"invalid {field_name}: {value!r} (closed enum)")


_CRITICAL = ("handoff_id", "mission_id", "packet_id", "routing_decision_id",
             "target_worker_id", "created_at", "created_by", "objective")

_DERIVED_IGNORED = frozenset({"can_dispatch", "can_execute", "is_dispatchable"})


@dataclass(slots=True)
class HandoffEnvelope:
    """A reviewable handoff package. Dispatches nothing; grants nothing."""

    handoff_id: str
    mission_id: str
    packet_id: str
    routing_decision_id: str
    target_worker_id: str
    created_at: str
    created_by: str
    objective: str
    target_worker_type: str = ""
    handoff_status: HandoffStatus = HandoffStatus.DRAFT
    input_refs: list[str] = field(default_factory=list)
    forbidden_input_refs: list[str] = field(default_factory=list)
    allowed_operations: list[str] = field(default_factory=list)
    forbidden_operations: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    verification_plan: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    requires_human_review: bool = True
    human_approval_ref: str = ""
    expires_at: str | None = None
    audit_notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "handoff_status",
                           _coerce_enum(HandoffStatus, self.handoff_status, "handoff_status"))

    # -- hard invariants: never dispatch, never execute (cannot be flipped) --
    @property
    def can_dispatch(self) -> bool:
        return False

    @property
    def can_execute(self) -> bool:
        return False

    def is_dispatchable(self) -> bool:
        return False

    # -- validation --------------------------------------------------------
    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        for name in _CRITICAL:
            v = getattr(self, name)
            if not isinstance(v, str) or not v.strip():
                errors.append(f"critical field empty: {name}")

        op_overlap = sorted(set(self.allowed_operations) & set(self.forbidden_operations))
        if op_overlap:
            errors.append(f"allowed/forbidden operations contradiction: {op_overlap}")
        in_overlap = sorted(set(self.input_refs) & set(self.forbidden_input_refs))
        if in_overlap:
            errors.append(f"input_refs/forbidden_input_refs contradiction: {in_overlap}")

        for name, val in self._iter_text_values():
            if _looks_like_secret(val):
                errors.append(f"secret-like content detected in field: {name}")
            if len(val) > _MAX_ITEM_LEN:
                errors.append(f"field too large (use refs, not raw contents): {name}")
        return errors

    def is_valid(self) -> bool:
        return not self.validation_errors()

    def validate(self) -> "HandoffEnvelope":
        errs = self.validation_errors()
        if errs:
            raise HandoffEnvelopeError("; ".join(errs))
        return self

    # -- state semantics ---------------------------------------------------
    def is_expired(self, *, now: datetime | None = None) -> bool:
        dt = _parse_iso(self.expires_at)
        return False if dt is None else dt <= (now or _now_utc())

    def is_active(self, *, now: datetime | None = None) -> bool:
        # Live, review-approved envelope. Still NOT dispatchable/executable.
        return (self.is_valid()
                and self.handoff_status == HandoffStatus.APPROVED_FOR_HANDOFF
                and not self.is_expired(now=now))

    def is_operation_allowed(self, operation: str) -> bool:
        if operation in self.forbidden_operations:
            return False
        return operation in self.allowed_operations

    def is_input_allowed(self, input_ref: str) -> bool:
        if input_ref in self.forbidden_input_refs:
            return False
        return input_ref in self.input_refs

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["handoff_status"] = self.handoff_status.value
        d["can_dispatch"] = False   # derived, never a grant
        d["can_execute"] = False    # derived, never a grant
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HandoffEnvelope":
        allowed = set(cls.__dataclass_fields__) - _DERIVED_IGNORED  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def _iter_text_values(self):
        for name in ("handoff_id", "mission_id", "packet_id", "routing_decision_id",
                     "target_worker_id", "target_worker_type", "created_by",
                     "objective", "human_approval_ref", "audit_notes"):
            yield name, getattr(self, name)
        for name in ("input_refs", "forbidden_input_refs", "allowed_operations",
                     "forbidden_operations", "constraints", "expected_outputs",
                     "verification_plan", "acceptance_criteria", "evidence_refs"):
            for item in getattr(self, name):
                if isinstance(item, str):
                    yield name, item


__all__ = [
    "HandoffEnvelopeError", "HandoffStatus", "HandoffEnvelope", "now_iso",
]
