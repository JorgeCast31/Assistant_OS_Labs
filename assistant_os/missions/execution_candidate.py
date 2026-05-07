from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from assistant_os.agents.permissions import AgentPermissionProfile, AgentPoliceRequest
from assistant_os.police.models import PoliceEvaluation, PoliceEvaluationType


class MissionExecutionCandidateStatus(str, Enum):
    PENDING_GATE = "pending_gate"


def _new_candidate_id() -> str:
    return str(uuid4())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class MissionExecutionCandidate:
    candidate_id: str = field(default_factory=_new_candidate_id)
    mission_id: str
    activity_id: str | None
    workstream_id: str | None
    agent_id: str
    agent_profile_id: str
    agent_profile_version: str | None
    profile_derived_at: datetime
    request_id: str
    requested_tool: str | None
    requested_environment: str | None
    requested_capabilities: tuple[str, ...]
    police_evaluation_id: str
    police_evaluation_outcome: str
    evaluation_risk_level: str
    police_audit_event_id: str | None
    operation_key: str
    candidate_status: MissionExecutionCandidateStatus
    created_at: datetime = field(default_factory=_now_utc)

    def __post_init__(self) -> None:
        _require_uuid_string("candidate_id", self.candidate_id)
        _require_non_empty("mission_id", self.mission_id)
        _require_non_empty("agent_id", self.agent_id)
        _require_non_empty("agent_profile_id", self.agent_profile_id)
        _require_non_empty("request_id", self.request_id)
        _require_non_empty("police_evaluation_id", self.police_evaluation_id)
        _require_non_empty("police_evaluation_outcome", self.police_evaluation_outcome)
        _require_non_empty("evaluation_risk_level", self.evaluation_risk_level)
        _require_non_empty("operation_key", self.operation_key)

        if not isinstance(self.requested_capabilities, tuple):
            raise TypeError("requested_capabilities must be a tuple")

        _require_aware_datetime("profile_derived_at", self.profile_derived_at)
        _require_aware_datetime("created_at", self.created_at)

        if self.candidate_status is not MissionExecutionCandidateStatus.PENDING_GATE:
            raise ValueError("candidate_status must be pending_gate")

        if self.police_evaluation_outcome != PoliceEvaluationType.ALLOW.value:
            raise ValueError("candidate requires an allow evaluation outcome")


def _require_non_empty(field_name: str, value: str) -> None:
    if not value:
        raise ValueError(f"{field_name} must be non-empty")


def _require_uuid_string(field_name: str, value: str) -> None:
    _require_non_empty(field_name, value)
    try:
        UUID(value)
    except ValueError:
        raise ValueError(f"{field_name} must be a UUID string") from None


def _require_aware_datetime(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def build_mission_execution_candidate(
    *,
    mission_id: str,
    activity_id: str | None,
    workstream_id: str | None,
    agent_profile: AgentPermissionProfile,
    agent_request: AgentPoliceRequest,
    police_evaluation: PoliceEvaluation,
    operation_key: str,
) -> MissionExecutionCandidate:
    if police_evaluation.outcome is not PoliceEvaluationType.ALLOW:
        raise ValueError(
            "MissionExecutionCandidate requires PoliceEvaluationType.ALLOW"
        )

    return MissionExecutionCandidate(
        mission_id=mission_id,
        activity_id=activity_id,
        workstream_id=workstream_id,
        agent_id=agent_profile.agent_id,
        agent_profile_id=agent_profile.profile_id,
        agent_profile_version=agent_profile.version,
        profile_derived_at=agent_profile.derived_at,
        request_id=agent_request.request_id,
        requested_tool=agent_request.requested_tool,
        requested_environment=agent_request.requested_environment,
        requested_capabilities=tuple(agent_request.requested_capabilities),
        police_evaluation_id=police_evaluation.evaluation_id,
        police_evaluation_outcome=police_evaluation.outcome.value,
        evaluation_risk_level=police_evaluation.risk_level.value,
        police_audit_event_id=police_evaluation.audit_event_id,
        operation_key=operation_key,
        candidate_status=MissionExecutionCandidateStatus.PENDING_GATE,
    )
