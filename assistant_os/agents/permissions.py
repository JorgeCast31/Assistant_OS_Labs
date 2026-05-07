from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from assistant_os.agents.registry import get_agent
from assistant_os.police.enforcer import PoliceEnforcer
from assistant_os.police.models import (
    AgentPermission,
    PoliceCheckRequest,
    PoliceEvaluation,
    PoliceEvaluationType,
    RiskLevel,
)


class AgentOperationalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


def _new_profile_id() -> str:
    return str(uuid4())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class AgentPermissionProfile:
    profile_id: str = field(default_factory=_new_profile_id)
    agent_id: str
    display_name: str
    role: str
    domain: str | None = None
    version: str | None = None
    declared_capabilities: frozenset[str] = field(default_factory=frozenset)
    permitted_tools: frozenset[str] = field(default_factory=frozenset)
    permitted_environments: frozenset[str] = field(default_factory=frozenset)
    requires_review: bool = False
    status: AgentOperationalStatus = AgentOperationalStatus.ACTIVE
    derived_at: datetime = field(default_factory=_now_utc)


@dataclass(frozen=True, kw_only=True)
class AgentPoliceRequest:
    request_id: str
    agent_id: str
    requested_by: str
    requested_tool: str | None
    requested_environment: str | None
    requested_capabilities: tuple[str, ...]
    risk_signals: tuple[str, ...] = ()
    mission_id: str | None = None
    activity_id: str | None = None


AGENT_POLICE_PERMISSION_CONFIG: dict[str, dict[str, tuple[str, ...]]] = {
    "code_executor": {
        "permitted_tools": ("code.review",),
        "permitted_environments": ("local",),
    },
    "host_launcher": {
        "permitted_tools": ("host.launch",),
        "permitted_environments": ("controlled_host",),
    },
    "machine_operator": {
        "permitted_tools": ("browser.snapshot", "browser.screenshot"),
        "permitted_environments": ("local_browser",),
    },
}


def build_agent_permission_profile(agent_name: str) -> AgentPermissionProfile:
    try:
        definition = get_agent(agent_name)
    except KeyError:
        raise KeyError(f"Unknown agent permission profile: {agent_name!r}") from None

    try:
        config = AGENT_POLICE_PERMISSION_CONFIG[agent_name]
    except KeyError:
        raise ValueError(
            f"Missing Police permission config for agent: {agent_name!r}"
        ) from None

    agent_id = str(definition.get("name", agent_name))
    declared = definition.get("capability_scope", ())

    return AgentPermissionProfile(
        agent_id=agent_id,
        display_name=agent_id,
        role=str(definition.get("description", "registered agent")),
        domain=definition.get("domain"),
        version=definition.get("version"),
        declared_capabilities=frozenset(str(value) for value in declared),
        permitted_tools=frozenset(config.get("permitted_tools", ())),
        permitted_environments=frozenset(config.get("permitted_environments", ())),
        requires_review=bool(definition.get("requires_review", True)),
    )


def profile_to_agent_permission(profile: AgentPermissionProfile) -> AgentPermission:
    return AgentPermission(
        agent_id=profile.agent_id,
        allowed_tools=sorted(profile.permitted_tools),
        allowed_environments=sorted(profile.permitted_environments),
        capability_scope=sorted(profile.declared_capabilities),
        requires_review=profile.requires_review
        or profile.status is AgentOperationalStatus.DEGRADED,
    )


def build_police_check_request(request: AgentPoliceRequest) -> PoliceCheckRequest:
    return PoliceCheckRequest(
        request_id=request.request_id,
        requested_by=request.requested_by,
        agent_id=request.agent_id,
        requested_capabilities=list(request.requested_capabilities),
        risk_signals=list(request.risk_signals),
        mission_id=request.mission_id,
        activity_id=request.activity_id,
        requested_tool=request.requested_tool,
        requested_environment=request.requested_environment,
    )


def evaluate_agent_permissions(
    profile: AgentPermissionProfile,
    request: AgentPoliceRequest,
) -> PoliceEvaluation:
    if profile.status in {
        AgentOperationalStatus.DISABLED,
        AgentOperationalStatus.INACTIVE,
    }:
        return PoliceEvaluation(
            request_id=request.request_id,
            outcome=PoliceEvaluationType.DENY,
            reason="Agent is not currently active.",
            why_blocked=f"Agent status is {profile.status.value}.",
            risk_level=RiskLevel.HIGH,
        )

    police_request = build_police_check_request(request)
    police_permission = profile_to_agent_permission(profile)
    return PoliceEnforcer().evaluate(police_request, police_permission)
