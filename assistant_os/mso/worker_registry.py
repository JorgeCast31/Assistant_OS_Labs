"""Worker / Subagent Registry v0 — auditable descriptions of available workers.

PR: Worker / Subagent Registry v0.

Describes workers/subagents/models/tools that MAY receive a DelegationWorkPacket
(PR #264) in the future. This is a **registry, not a router**. It does NOT route,
execute, call models, contact external APIs, mint tokens, or grant authority.

- A ``WorkerProfile`` is a description, NOT an authorization.
- ``capabilities`` are descriptive, NOT permissions.
- A local model is NOT thereby allowed to see secrets.
- ``AVAILABLE`` does NOT mean executable; routing/execution is a separate,
  later, governed step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from .delegation_packet import CostTier, RiskLevel, TaskType


class WorkerProfileError(ValueError):
    """Raised when a WorkerProfile fails validation (fail-closed)."""


class WorkerType(str, Enum):
    CLAUDE_CODE = "CLAUDE_CODE"
    CODEX = "CODEX"
    GPT_MSO = "GPT_MSO"
    LOCAL_MODEL = "LOCAL_MODEL"
    HUMAN = "HUMAN"
    TOOL_ONLY = "TOOL_ONLY"
    VERIFIER = "VERIFIER"
    DOCS_AGENT = "DOCS_AGENT"
    TEST_AGENT = "TEST_AGENT"
    SAFETY_AGENT = "SAFETY_AGENT"


class WorkerStatus(str, Enum):
    DRAFT = "DRAFT"
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    BLOCKED = "BLOCKED"
    DEPRECATED = "DEPRECATED"


class PrivacyClass(str, Enum):
    PUBLIC_CONTEXT_OK = "PUBLIC_CONTEXT_OK"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    LOCAL_PREFERRED = "LOCAL_PREFERRED"
    LOCAL_ONLY = "LOCAL_ONLY"
    SECRET_PROHIBITED = "SECRET_PROHIBITED"


class ContextWindowClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    HUGE = "HUGE"
    UNKNOWN = "UNKNOWN"


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


def _coerce_enum(enum_cls, value, field_name):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        raise WorkerProfileError(f"invalid {field_name}: {value!r} (closed enum)")


_CRITICAL_STR_FIELDS = ("worker_id", "display_name")


@dataclass(slots=True)
class WorkerProfile:
    """A descriptive profile of an available worker/subagent. Grants nothing."""

    worker_id: str
    display_name: str
    worker_type: WorkerType = WorkerType.TOOL_ONLY
    provider: str = ""
    model_family: str = ""
    model_name: str = ""
    capabilities: list[str] = field(default_factory=list)
    preferred_task_types: list[str] = field(default_factory=list)
    forbidden_task_types: list[str] = field(default_factory=list)
    max_risk_level: RiskLevel = RiskLevel.READ_ONLY
    supported_cost_tiers: list[str] = field(default_factory=lambda: [CostTier.LOCAL_PREFERRED.value])
    default_cost_tier: CostTier = CostTier.LOCAL_PREFERRED
    context_window_class: ContextWindowClass = ContextWindowClass.UNKNOWN
    privacy_class: PrivacyClass = PrivacyClass.SECRET_PROHIBITED
    tool_access: list[str] = field(default_factory=list)
    requires_human_supervision: bool = True
    can_execute: bool = False
    can_write_external: bool = False
    can_access_secrets: bool = False
    status: WorkerStatus = WorkerStatus.DRAFT
    audit_notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "worker_type", _coerce_enum(WorkerType, self.worker_type, "worker_type"))
        object.__setattr__(self, "max_risk_level", _coerce_enum(RiskLevel, self.max_risk_level, "max_risk_level"))
        object.__setattr__(self, "default_cost_tier", _coerce_enum(CostTier, self.default_cost_tier, "default_cost_tier"))
        object.__setattr__(self, "context_window_class", _coerce_enum(ContextWindowClass, self.context_window_class, "context_window_class"))
        object.__setattr__(self, "privacy_class", _coerce_enum(PrivacyClass, self.privacy_class, "privacy_class"))
        object.__setattr__(self, "status", _coerce_enum(WorkerStatus, self.status, "status"))

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        for name in _CRITICAL_STR_FIELDS:
            v = getattr(self, name)
            if not isinstance(v, str) or not v.strip():
                errors.append(f"critical field empty: {name}")

        # closed-enum membership for list-typed enum fields
        for tt in list(self.preferred_task_types) + list(self.forbidden_task_types):
            if tt not in {t.value for t in TaskType}:
                errors.append(f"invalid task_type in list: {tt!r}")
        for ct in self.supported_cost_tiers:
            if ct not in {c.value for c in CostTier}:
                errors.append(f"invalid cost_tier in supported_cost_tiers: {ct!r}")

        overlap = sorted(set(self.preferred_task_types) & set(self.forbidden_task_types))
        if overlap:
            errors.append(f"preferred/forbidden task_types contradiction: {overlap}")

        # default_cost_tier must be within supported_cost_tiers
        if self.default_cost_tier.value not in self.supported_cost_tiers:
            errors.append("default_cost_tier not within supported_cost_tiers")

        # SECRET_PROHIBITED must not claim secret access
        if self.privacy_class == PrivacyClass.SECRET_PROHIBITED and self.can_access_secrets:
            errors.append("privacy_class SECRET_PROHIBITED contradicts can_access_secrets=true")

        # PREMIUM must be justified if represented
        if (CostTier.PREMIUM_REQUIRED.value in self.supported_cost_tiers
                or self.default_cost_tier == CostTier.PREMIUM_REQUIRED) and not self.audit_notes.strip():
            errors.append("PREMIUM_REQUIRED cost tier requires justification in audit_notes")

        for name, val in self._iter_text_values():
            if _looks_like_secret(val):
                errors.append(f"secret-like content detected in field: {name}")

        return errors

    def is_valid(self) -> bool:
        return not self.validation_errors()

    def validate(self) -> "WorkerProfile":
        errs = self.validation_errors()
        if errs:
            raise WorkerProfileError("; ".join(errs))
        return self

    def is_assignable(self) -> bool:
        # Only an AVAILABLE, valid worker may be *considered* for assignment.
        # DRAFT/DISABLED/BLOCKED/DEPRECATED are never assignable. Assignable is
        # NOT execution authority.
        return self.is_valid() and self.status == WorkerStatus.AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["worker_type"] = self.worker_type.value
        d["max_risk_level"] = self.max_risk_level.value
        d["default_cost_tier"] = self.default_cost_tier.value
        d["context_window_class"] = self.context_window_class.value
        d["privacy_class"] = self.privacy_class.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerProfile":
        allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def _iter_text_values(self):
        for name in ("worker_id", "display_name", "provider", "model_family",
                     "model_name", "audit_notes"):
            yield name, getattr(self, name)
        for name in ("capabilities", "tool_access"):
            for item in getattr(self, name):
                if isinstance(item, str):
                    yield name, item


__all__ = [
    "WorkerProfileError", "WorkerType", "WorkerStatus", "PrivacyClass",
    "ContextWindowClass", "WorkerProfile",
]
