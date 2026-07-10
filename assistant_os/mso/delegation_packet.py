"""Delegation / Work Packet v0 — auditable delegable unit of work (no execution).

PR: Delegation / Work Packet v0.

WHAT THIS IS
------------
A small, stdlib-only contract for a unit of work that MAY be delegated (to
Claude Code / Codex / GPT-MSO / a local model / a tool / a human), tied to a
Mission (PR #262), with limits, suggested model, cost tier, risk level, allowed
inputs/operations, forbidden operations, expected outputs and a verification
plan.

WHAT THIS IS NOT
----------------
It executes NOTHING, calls NO model, contacts NO external API, does NO
auto-routing, and grants NO authority. A packet is never a capability token.
``model_preference`` is a *preference*, not an authorization. ``can_execute``
is hard-wired ``False`` — even at ``APPROVED_FOR_HANDOFF``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DelegationPacketError(ValueError):
    """Raised when a Delegation/Work Packet fails validation (fail-closed)."""


class DelegationStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED_FOR_HANDOFF = "APPROVED_FOR_HANDOFF"
    IN_PROGRESS = "IN_PROGRESS"
    RETURNED = "RETURNED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"
    REVOKED = "REVOKED"


class TargetWorker(str, Enum):
    CLAUDE_CODE = "CLAUDE_CODE"
    CODEX = "CODEX"
    GPT_MSO = "GPT_MSO"
    LOCAL_MODEL = "LOCAL_MODEL"
    HUMAN = "HUMAN"
    TOOL_ONLY = "TOOL_ONLY"
    UNASSIGNED = "UNASSIGNED"


class TaskType(str, Enum):
    REPO_INSPECTION = "REPO_INSPECTION"
    CODE_PATCH = "CODE_PATCH"
    TESTING = "TESTING"
    DOCUMENTATION = "DOCUMENTATION"
    SUMMARIZATION = "SUMMARIZATION"
    CLASSIFICATION = "CLASSIFICATION"
    PLANNING = "PLANNING"
    REVIEW = "REVIEW"
    EXTRACTION = "EXTRACTION"


class CostTier(str, Enum):
    LOCAL_PREFERRED = "LOCAL_PREFERRED"
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    PREMIUM_REQUIRED = "PREMIUM_REQUIRED"


class RiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    DOCS_ONLY = "DOCS_ONLY"
    PATCH_ALLOWED = "PATCH_ALLOWED"
    EXTERNAL_WRITE_PROHIBITED = "EXTERNAL_WRITE_PROHIBITED"
    EXTERNAL_WRITE_REQUIRES_CONFIRMATION = "EXTERNAL_WRITE_REQUIRES_CONFIRMATION"
    BLOCKED = "BLOCKED"


# Detect secret *values*, not deny-list *names*. A packet legitimately names
# forbidden inputs like "secrets" or "credentials"; those must NOT trip the
# detector. We flag token-shaped strings and "<sensitive> = <value>" forms.
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
        raise DelegationPacketError(f"invalid {field_name}: {value!r} (closed enum)")


_CRITICAL_STR_FIELDS = ("packet_id", "mission_id", "created_at", "created_by", "objective")


@dataclass(slots=True)
class DelegationWorkPacket:
    """An auditable delegable unit of work. Executes nothing; grants nothing."""

    packet_id: str
    mission_id: str
    created_at: str
    created_by: str
    objective: str
    task_title: str = ""
    task_type: TaskType = TaskType.REPO_INSPECTION
    target_worker: TargetWorker = TargetWorker.UNASSIGNED
    model_preference: str = ""
    cost_tier: CostTier = CostTier.LOCAL_PREFERRED
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    status: DelegationStatus = DelegationStatus.DRAFT
    human_review_required: bool = True
    allowed_inputs: list[str] = field(default_factory=list)
    forbidden_inputs: list[str] = field(default_factory=list)
    allowed_operations: list[str] = field(default_factory=list)
    forbidden_operations: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    verification_plan: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    expires_at: str | None = None
    linked_evidence: list[str] = field(default_factory=list)
    audit_notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_type", _coerce_enum(TaskType, self.task_type, "task_type"))
        object.__setattr__(self, "target_worker", _coerce_enum(TargetWorker, self.target_worker, "target_worker"))
        object.__setattr__(self, "cost_tier", _coerce_enum(CostTier, self.cost_tier, "cost_tier"))
        object.__setattr__(self, "risk_level", _coerce_enum(RiskLevel, self.risk_level, "risk_level"))
        object.__setattr__(self, "status", _coerce_enum(DelegationStatus, self.status, "status"))

    # -- validation --------------------------------------------------------
    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        for name in _CRITICAL_STR_FIELDS:
            v = getattr(self, name)
            if not isinstance(v, str) or not v.strip():
                errors.append(f"critical field empty: {name}")

        op_overlap = sorted(set(self.allowed_operations) & set(self.forbidden_operations))
        if op_overlap:
            errors.append(f"allowed/forbidden operations contradiction: {op_overlap}")
        in_overlap = sorted(set(self.allowed_inputs) & set(self.forbidden_inputs))
        if in_overlap:
            errors.append(f"allowed/forbidden inputs contradiction: {in_overlap}")

        # PREMIUM_REQUIRED must be justified.
        if self.cost_tier == CostTier.PREMIUM_REQUIRED and not self.audit_notes.strip():
            errors.append("cost_tier PREMIUM_REQUIRED requires justification in audit_notes")

        for name, val in self._iter_text_values():
            if _looks_like_secret(val):
                errors.append(f"secret-like content detected in field: {name}")

        return errors

    def is_valid(self) -> bool:
        return not self.validation_errors()

    def validate(self) -> "DelegationWorkPacket":
        errs = self.validation_errors()
        if errs:
            raise DelegationPacketError("; ".join(errs))
        return self

    # -- state semantics ---------------------------------------------------
    def is_expired(self, *, now: datetime | None = None) -> bool:
        dt = _parse_iso(self.expires_at)
        return False if dt is None else dt <= (now or _now_utc())

    def is_active(self, *, now: datetime | None = None) -> bool:
        # Live, handoff-ready packet. Expired is never active. Still NOT executable.
        return (
            self.is_valid()
            and self.status == DelegationStatus.APPROVED_FOR_HANDOFF
            and not self.is_expired(now=now)
        )

    @property
    def can_execute(self) -> bool:
        # Hard-false: a packet never executes and never grants execution — even
        # at APPROVED_FOR_HANDOFF and regardless of target_worker/model_preference.
        return False

    def is_auto_executable(self) -> bool:
        return False

    def is_operation_allowed(self, operation: str) -> bool:
        if operation in self.forbidden_operations:
            return False
        return operation in self.allowed_operations

    def is_input_allowed(self, input_ref: str) -> bool:
        if input_ref in self.forbidden_inputs:
            return False
        return input_ref in self.allowed_inputs

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["task_type"] = self.task_type.value
        d["target_worker"] = self.target_worker.value
        d["cost_tier"] = self.cost_tier.value
        d["risk_level"] = self.risk_level.value
        d["status"] = self.status.value
        d["can_execute"] = False  # derived, never a grant
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DelegationWorkPacket":
        allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def _iter_text_values(self):
        for name in ("packet_id", "mission_id", "created_at", "created_by",
                     "task_title", "objective", "model_preference", "audit_notes"):
            yield name, getattr(self, name)
        for name in ("allowed_inputs", "forbidden_inputs", "allowed_operations",
                     "forbidden_operations", "expected_outputs", "verification_plan",
                     "acceptance_criteria", "linked_evidence"):
            for item in getattr(self, name):
                if isinstance(item, str):
                    yield name, item


__all__ = [
    "DelegationPacketError",
    "DelegationStatus", "TargetWorker", "TaskType", "CostTier", "RiskLevel",
    "DelegationWorkPacket", "now_iso",
]
