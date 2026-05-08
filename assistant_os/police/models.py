from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def _new_id() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PoliceEvaluationType(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class PoliceViolation:
    code: str
    message: str
    severity: RiskLevel
    field: str | None = None


@dataclass
class ToolPermission:
    tool_name: str
    allowed: bool
    reason: str | None = None


@dataclass
class EnvironmentPermission:
    environment: str
    allowed: bool
    reason: str | None = None


@dataclass
class AgentPermission:
    agent_id: str
    allowed_tools: list[str]
    allowed_environments: list[str]
    capability_scope: list[str]
    requires_review: bool = False


@dataclass
class PoliceCheckRequest:
    request_id: str
    requested_by: str
    agent_id: str
    requested_capabilities: list[str]
    risk_signals: list[str]
    mission_id: str | None = None
    activity_id: str | None = None
    requested_tool: str | None = None
    requested_environment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PoliceEvaluation:
    request_id: str
    outcome: PoliceEvaluationType
    reason: str
    risk_level: RiskLevel
    evaluation_id: str = field(default_factory=_new_id)
    why_blocked: str | None = None
    required_confirmation_reason: str | None = None
    violations: list[PoliceViolation] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    allowed_environments: list[str] = field(default_factory=list)
    denied_environments: list[str] = field(default_factory=list)
    capability_scope: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
    audit_event_id: str = field(default_factory=_new_id)


@dataclass(frozen=True)
class PoliceAuditEvent:
    request_id: str
    evaluation_id: str
    event_type: str
    message: str
    actor: str
    event_id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)
