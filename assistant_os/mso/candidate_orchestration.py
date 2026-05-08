from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from assistant_os.agents.permissions import (
    AgentPoliceRequest,
    build_agent_permission_profile,
    build_police_check_request,
    evaluate_agent_permissions,
)
from assistant_os.audit.sink import AuditSink
from assistant_os.missions.candidate_audit import (
    CandidateAuditRecord,
    build_candidate_created_audit,
)
from assistant_os.missions.execution_candidate import (
    MissionExecutionCandidate,
    build_mission_execution_candidate,
)
from assistant_os.missions.service import MissionRegistry
from assistant_os.police.audit import build_audit_event
from assistant_os.police.models import (
    PoliceAuditEvent,
    PoliceEvaluation,
    PoliceEvaluationType,
)


class CandidateOrchestrationOutcome(str, Enum):
    CANDIDATE_CREATED = "candidate_created"
    DENIED = "denied"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    AGENT_NOT_FOUND = "agent_not_found"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True, init=False)
class MSOCandidateOrchestrationRequest:
    mission_id: str
    agent_name: str
    operation_key: str
    requested_by: str
    requested_tool: str | None
    requested_environment: str | None
    requested_capabilities: tuple[str, ...]
    risk_signals: tuple[str, ...]
    activity_id: str | None = None
    workstream_id: str | None = None
    request_id: str = field(default_factory=lambda: str(uuid4()))

    def __init__(
        self,
        *,
        mission_id: str,
        agent_name: str,
        operation_key: str,
        requested_by: str,
        requested_tool: str | None,
        requested_environment: str | None,
        requested_capabilities: tuple[str, ...],
        risk_signals: tuple[str, ...],
        activity_id: str | None = None,
        workstream_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        resolved_request_id = request_id or str(uuid4())
        _require_non_empty("mission_id", mission_id)
        _require_non_empty("agent_name", agent_name)
        _require_non_empty("operation_key", operation_key)
        _require_non_empty("requested_by", requested_by)
        _require_non_empty("request_id", resolved_request_id)
        _require_tuple("requested_capabilities", requested_capabilities)
        _require_tuple("risk_signals", risk_signals)
        object.__setattr__(self, "mission_id", mission_id)
        object.__setattr__(self, "agent_name", agent_name)
        object.__setattr__(self, "operation_key", operation_key)
        object.__setattr__(self, "requested_by", requested_by)
        object.__setattr__(self, "requested_tool", requested_tool)
        object.__setattr__(self, "requested_environment", requested_environment)
        object.__setattr__(self, "requested_capabilities", requested_capabilities)
        object.__setattr__(self, "risk_signals", risk_signals)
        object.__setattr__(self, "activity_id", activity_id)
        object.__setattr__(self, "workstream_id", workstream_id)
        object.__setattr__(self, "request_id", resolved_request_id)


@dataclass(frozen=True, kw_only=True, init=False)
class MSOCandidateOrchestrationResult:
    outcome: CandidateOrchestrationOutcome
    request_id: str
    police_evaluation: PoliceEvaluation | None
    police_audit_event: PoliceAuditEvent | None
    candidate: MissionExecutionCandidate | None
    candidate_audit_record: CandidateAuditRecord | None
    detail: str
    created_at: datetime = field(default_factory=_now_utc)

    def __init__(
        self,
        *,
        outcome: CandidateOrchestrationOutcome,
        request_id: str,
        police_evaluation: PoliceEvaluation | None,
        police_audit_event: PoliceAuditEvent | None,
        candidate: MissionExecutionCandidate | None,
        candidate_audit_record: CandidateAuditRecord | None,
        detail: str,
        created_at: datetime | None = None,
    ) -> None:
        resolved_created_at = created_at or _now_utc()
        _require_non_empty("request_id", request_id)
        _require_non_empty("detail", detail)
        _require_aware_datetime("created_at", resolved_created_at)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "police_evaluation", police_evaluation)
        object.__setattr__(self, "police_audit_event", police_audit_event)
        object.__setattr__(self, "candidate", candidate)
        object.__setattr__(self, "candidate_audit_record", candidate_audit_record)
        object.__setattr__(self, "detail", detail)
        object.__setattr__(self, "created_at", resolved_created_at)


def orchestrate_mission_execution_candidate(
    *,
    request: MSOCandidateOrchestrationRequest,
    mission_registry: MissionRegistry,
    audit_sink: AuditSink,
) -> MSOCandidateOrchestrationResult:
    _require_mission(request, mission_registry)
    try:
        agent_profile = build_agent_permission_profile(request.agent_name)
    except (KeyError, ValueError) as exc:
        return MSOCandidateOrchestrationResult(
            outcome=CandidateOrchestrationOutcome.AGENT_NOT_FOUND,
            request_id=request.request_id,
            police_evaluation=None,
            police_audit_event=None,
            candidate=None,
            candidate_audit_record=None,
            detail=f"Agent unavailable for candidate orchestration: {exc}",
        )

    agent_request = AgentPoliceRequest(
        request_id=request.request_id,
        agent_id=agent_profile.agent_id,
        requested_by=request.requested_by,
        requested_tool=request.requested_tool,
        requested_environment=request.requested_environment,
        requested_capabilities=request.requested_capabilities,
        risk_signals=request.risk_signals,
        mission_id=request.mission_id,
        activity_id=request.activity_id,
    )
    police_request = build_police_check_request(agent_request)
    police_evaluation = evaluate_agent_permissions(agent_profile, agent_request)
    police_audit_event = build_audit_event(police_request, police_evaluation)

    if police_evaluation.outcome is PoliceEvaluationType.ALLOW:
        candidate = build_mission_execution_candidate(
            mission_id=request.mission_id,
            activity_id=request.activity_id,
            workstream_id=request.workstream_id,
            agent_profile=agent_profile,
            agent_request=agent_request,
            police_evaluation=police_evaluation,
            operation_key=request.operation_key,
        )
        candidate_audit_record = build_candidate_created_audit(candidate)
        audit_sink.emit(police_audit_event)
        audit_sink.emit(candidate_audit_record)
        return MSOCandidateOrchestrationResult(
            outcome=CandidateOrchestrationOutcome.CANDIDATE_CREATED,
            request_id=request.request_id,
            police_evaluation=police_evaluation,
            police_audit_event=police_audit_event,
            candidate=candidate,
            candidate_audit_record=candidate_audit_record,
            detail="Candidate created and waiting for the next authority layer.",
        )

    audit_sink.emit(police_audit_event)
    if police_evaluation.outcome is PoliceEvaluationType.DENY:
        return MSOCandidateOrchestrationResult(
            outcome=CandidateOrchestrationOutcome.DENIED,
            request_id=request.request_id,
            police_evaluation=police_evaluation,
            police_audit_event=police_audit_event,
            candidate=None,
            candidate_audit_record=None,
            detail=police_evaluation.why_blocked or police_evaluation.reason,
        )

    if police_evaluation.outcome is PoliceEvaluationType.REQUIRES_CONFIRMATION:
        return MSOCandidateOrchestrationResult(
            outcome=CandidateOrchestrationOutcome.REQUIRES_CONFIRMATION,
            request_id=request.request_id,
            police_evaluation=police_evaluation,
            police_audit_event=police_audit_event,
            candidate=None,
            candidate_audit_record=None,
            detail=(
                police_evaluation.required_confirmation_reason
                or police_evaluation.reason
            ),
        )

    raise ValueError(f"unsupported Police evaluation: {police_evaluation.outcome!r}")


def _require_mission(
    request: MSOCandidateOrchestrationRequest,
    mission_registry: MissionRegistry,
) -> None:
    mission = mission_registry.store.get_mission(request.mission_id)
    if mission is None:
        raise KeyError(f"unknown mission: {request.mission_id}")


def _require_non_empty(field_name: str, value: str) -> None:
    if not value:
        raise ValueError(f"{field_name} must be non-empty")


def _require_tuple(field_name: str, value: tuple[str, ...]) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")


def _require_aware_datetime(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
