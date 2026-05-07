from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from assistant_os.missions.execution_candidate import MissionExecutionCandidate


class CandidateAuditEventType(str, Enum):
    CANDIDATE_CREATED = "candidate_created"


def _new_audit_id() -> str:
    return str(uuid4())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class CandidateAuditRecord:
    audit_id: str = field(default_factory=_new_audit_id)
    event_type: CandidateAuditEventType
    candidate_id: str
    mission_id: str
    activity_id: str | None
    workstream_id: str | None
    agent_id: str
    agent_profile_id: str
    request_id: str | None
    police_evaluation_id: str
    police_evaluation_outcome: str
    operation_key: str
    created_at: datetime = field(default_factory=_now_utc)
    details: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty("audit_id", self.audit_id)
        _require_non_empty("candidate_id", self.candidate_id)
        _require_non_empty("mission_id", self.mission_id)
        _require_non_empty("agent_id", self.agent_id)
        _require_non_empty("agent_profile_id", self.agent_profile_id)
        _require_non_empty("police_evaluation_id", self.police_evaluation_id)
        _require_non_empty(
            "police_evaluation_outcome", self.police_evaluation_outcome
        )
        _require_non_empty("operation_key", self.operation_key)
        _require_aware_datetime("created_at", self.created_at)

        if self.event_type is not CandidateAuditEventType.CANDIDATE_CREATED:
            raise ValueError("event_type must be candidate_created")

        if not isinstance(self.details, tuple):
            raise TypeError("details must be a tuple")


def _require_non_empty(field_name: str, value: str) -> None:
    if not value:
        raise ValueError(f"{field_name} must be non-empty")


def _require_aware_datetime(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def build_candidate_created_audit(
    candidate: MissionExecutionCandidate,
) -> CandidateAuditRecord:
    return CandidateAuditRecord(
        event_type=CandidateAuditEventType.CANDIDATE_CREATED,
        candidate_id=candidate.candidate_id,
        mission_id=candidate.mission_id,
        activity_id=candidate.activity_id,
        workstream_id=candidate.workstream_id,
        agent_id=candidate.agent_id,
        agent_profile_id=candidate.agent_profile_id,
        request_id=candidate.request_id,
        police_evaluation_id=candidate.police_evaluation_id,
        police_evaluation_outcome=candidate.police_evaluation_outcome,
        operation_key=candidate.operation_key,
    )
