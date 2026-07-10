"""Mission / Authorization Record v0 — auditable sovereign-authorization contract.

PR: Mission/Authorization Record v0 (closes TASK-0001 F1 groundwork).

WHAT THIS IS
------------
A small, validatable, auditable data contract that represents a sovereign
mission / authorization *in-repo* — so a future action never has to rely on
"Jorge said so in chat" (human-cable). It records objective, scope, limits,
required human confirmations, authority level, status, expiry and evidence.

WHAT THIS IS NOT
----------------
This module executes NOTHING. It has no Runner, no queue, no scheduler, no UI,
no network, and no backend. A record's existence — even an approved one — does
NOT grant execution. ``can_execute`` is hard-wired ``False`` in v0.

SECURITY INVARIANTS (never violated)
------------------------------------
1. An invalid record fails closed (``validate`` raises; ``is_valid`` is False).
2. An expired record is never ``active``.
3. A record without a recorded human confirmation is never ``approved``.
4. An approved record does NOT imply execution (``can_execute`` is always False).
5. A record must not contain secrets (secret-like content invalidates it).
6. Empty critical fields invalidate the record.
7. ``allowed_operations`` may not contradict ``forbidden_operations``.
8. If an operation is forbidden, forbidden wins.
9. ``authority_level`` / ``status`` / ``execution_policy`` are closed enums.
10. ``execution_policy`` can express ``NO_EXECUTION`` explicitly (the default).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MissionRecordError(ValueError):
    """Raised when a Mission/Authorization Record fails validation (fail-closed)."""


# --- Closed enums ----------------------------------------------------------

class MissionStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    COMPLETED = "COMPLETED"


class MissionAuthorityLevel(str, Enum):
    NONE = "NONE"
    READ_ONLY = "READ_ONLY"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    SOVEREIGN = "SOVEREIGN"


class MissionExecutionPolicy(str, Enum):
    # v0: none of these grant execution. They only DESCRIBE intent for a future
    # governed path. NO_EXECUTION is the explicit, safe default.
    NO_EXECUTION = "NO_EXECUTION"
    REQUIRES_HUMAN_CONFIRMATION = "REQUIRES_HUMAN_CONFIRMATION"
    GOVERNED_ONLY = "GOVERNED_ONLY"


# --- Secret detection (defense-in-depth) -----------------------------------

_SECRET_SUBSTRINGS = (
    "api_key", "apikey", "secret", "password", "passwd", "bearer ",
    "authorization:", "-----begin", "aws_secret", "private_key",
)
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),          # OpenAI-style keys
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),   # GitHub tokens
    re.compile(r"AKIA[0-9A-Z]{12,}"),            # AWS access key id
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), # Slack tokens
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),         # long hex blobs
)


def _looks_like_secret(text: str) -> bool:
    if not isinstance(text, str) or not text:
        return False
    low = text.lower()
    if any(s in low for s in _SECRET_SUBSTRINGS):
        return True
    return any(p.search(text) for p in _SECRET_PATTERNS)


# --- Helpers ---------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def now_iso() -> str:
    return _now_utc().isoformat()


# --- The record ------------------------------------------------------------

_CRITICAL_STR_FIELDS = ("mission_id", "created_at", "created_by", "objective", "scope")


@dataclass(slots=True)
class MissionAuthorizationRecord:
    """An auditable sovereign mission / authorization. Grants NO execution."""

    mission_id: str
    created_at: str
    created_by: str
    objective: str
    scope: str
    authority_level: MissionAuthorityLevel = MissionAuthorityLevel.NONE
    status: MissionStatus = MissionStatus.DRAFT
    execution_policy: MissionExecutionPolicy = MissionExecutionPolicy.NO_EXECUTION
    reason: str = ""
    allowed_operations: list[str] = field(default_factory=list)
    forbidden_operations: list[str] = field(default_factory=list)
    required_human_confirmations: list[str] = field(default_factory=list)
    expires_at: str | None = None
    linked_evidence: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    capability_requirements: list[str] = field(default_factory=list)
    audit_notes: str = ""

    # -- coercion ----------------------------------------------------------
    def __post_init__(self) -> None:
        # Coerce enums from raw strings (fail-closed on invalid values).
        object.__setattr__(self, "authority_level", _coerce_enum(MissionAuthorityLevel, self.authority_level, "authority_level"))
        object.__setattr__(self, "status", _coerce_enum(MissionStatus, self.status, "status"))
        object.__setattr__(self, "execution_policy", _coerce_enum(MissionExecutionPolicy, self.execution_policy, "execution_policy"))

    # -- validation --------------------------------------------------------
    def validation_errors(self) -> list[str]:
        errors: list[str] = []

        # 6. Empty critical fields invalidate the record.
        for name in _CRITICAL_STR_FIELDS:
            val = getattr(self, name)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"critical field empty: {name}")

        # 9. Closed enums (already coerced; defensive re-check).
        if not isinstance(self.authority_level, MissionAuthorityLevel):
            errors.append("authority_level not a valid enum")
        if not isinstance(self.status, MissionStatus):
            errors.append("status not a valid enum")
        if not isinstance(self.execution_policy, MissionExecutionPolicy):
            errors.append("execution_policy not a valid enum")

        # 7. allowed vs forbidden must not contradict.
        overlap = sorted(set(self.allowed_operations) & set(self.forbidden_operations))
        if overlap:
            errors.append(f"allowed/forbidden contradiction: {overlap}")

        # 3. HUMAN_APPROVED requires a recorded human confirmation.
        if self.status == MissionStatus.HUMAN_APPROVED and not self.required_human_confirmations:
            errors.append("HUMAN_APPROVED without any recorded human confirmation")

        # 5. No secrets anywhere in string/list fields.
        for name, val in self._iter_text_values():
            if _looks_like_secret(val):
                errors.append(f"secret-like content detected in field: {name}")

        return errors

    def is_valid(self) -> bool:
        return not self.validation_errors()

    def validate(self) -> "MissionAuthorizationRecord":
        """Fail-closed: raise MissionRecordError if invalid; else return self."""
        errs = self.validation_errors()
        if errs:
            raise MissionRecordError("; ".join(errs))
        return self

    # -- state semantics ---------------------------------------------------
    def is_expired(self, *, now: datetime | None = None) -> bool:
        dt = _parse_iso(self.expires_at)
        if dt is None:
            return False  # no expiry set → never auto-expires
        return dt <= (now or _now_utc())

    def is_approved(self, *, now: datetime | None = None) -> bool:
        # 3 + 2 + 1: approved requires valid, not expired, HUMAN_APPROVED, and a
        # recorded human confirmation.
        return (
            self.is_valid()
            and self.status == MissionStatus.HUMAN_APPROVED
            and bool(self.required_human_confirmations)
            and not self.is_expired(now=now)
        )

    def is_active(self, *, now: datetime | None = None) -> bool:
        # 2: expired is never active. Active == approved and in force.
        return self.is_approved(now=now)

    @property
    def can_execute(self) -> bool:
        # 4 + 10: v0 records NEVER grant execution. Execution authority is a
        # separate governed step outside this contract.
        return False

    def is_operation_allowed(self, operation: str) -> bool:
        # 8: forbidden wins over allowed, always.
        if operation in self.forbidden_operations:
            return False
        return operation in self.allowed_operations

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["authority_level"] = self.authority_level.value
        d["status"] = self.status.value
        d["execution_policy"] = self.execution_policy.value
        # Derived, read-only truth (never a grant).
        d["can_execute"] = False
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MissionAuthorizationRecord":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in allowed}
        return cls(**kwargs)

    # -- internal ----------------------------------------------------------
    def _iter_text_values(self):
        for name in ("mission_id", "created_at", "created_by", "objective",
                     "scope", "reason", "audit_notes"):
            yield name, getattr(self, name)
        for name in ("allowed_operations", "forbidden_operations",
                     "required_human_confirmations", "linked_evidence",
                     "risk_flags", "capability_requirements"):
            for item in getattr(self, name):
                if isinstance(item, str):
                    yield name, item


def _coerce_enum(enum_cls, value, field_name):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        raise MissionRecordError(f"invalid {field_name}: {value!r} (closed enum)")


__all__ = [
    "MissionRecordError",
    "MissionStatus",
    "MissionAuthorityLevel",
    "MissionExecutionPolicy",
    "MissionAuthorizationRecord",
    "now_iso",
]
