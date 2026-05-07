from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
from uuid import UUID

import pytest

from assistant_os.missions.candidate_audit import (
    CandidateAuditEventType,
    CandidateAuditRecord,
    build_candidate_created_audit,
)
from assistant_os.missions.execution_candidate import (
    MissionExecutionCandidate,
    MissionExecutionCandidateStatus,
)


def _candidate() -> MissionExecutionCandidate:
    return MissionExecutionCandidate(
        mission_id="mission-1",
        activity_id="activity-1",
        workstream_id="workstream-1",
        agent_id="agent-1",
        agent_profile_id="profile-1",
        agent_profile_version="v1",
        profile_derived_at=datetime.now(timezone.utc),
        request_id="request-1",
        requested_tool="tool-1",
        requested_environment="local",
        requested_capabilities=("read",),
        police_evaluation_id="evaluation-1",
        police_evaluation_outcome="ALLOW",
        evaluation_risk_level="LOW",
        police_audit_event_id="police-audit-1",
        operation_key="mission-1:activity-1:agent-1",
        candidate_status=MissionExecutionCandidateStatus.PENDING_GATE,
    )


def _record(**overrides: object) -> CandidateAuditRecord:
    values = {
        "event_type": CandidateAuditEventType.CANDIDATE_CREATED,
        "candidate_id": "candidate-1",
        "mission_id": "mission-1",
        "activity_id": "activity-1",
        "workstream_id": "workstream-1",
        "agent_id": "agent-1",
        "agent_profile_id": "profile-1",
        "request_id": "request-1",
        "police_evaluation_id": "evaluation-1",
        "police_evaluation_outcome": "ALLOW",
        "operation_key": "mission-1:activity-1:agent-1",
    }
    values.update(overrides)
    return CandidateAuditRecord(**values)


def test_candidate_audit_record_is_frozen() -> None:
    record = _record()

    with pytest.raises(FrozenInstanceError):
        record.mission_id = "changed"  # type: ignore[misc]


def test_audit_id_is_generated_and_non_empty() -> None:
    record = _record()

    assert record.audit_id
    UUID(record.audit_id)


def test_created_at_is_timezone_aware() -> None:
    record = _record()

    assert record.created_at.tzinfo is not None
    assert record.created_at.utcoffset() is not None


def test_event_type_is_candidate_created() -> None:
    record = _record()

    assert record.event_type is CandidateAuditEventType.CANDIDATE_CREATED


def test_build_candidate_created_audit_snapshots_candidate_fields() -> None:
    candidate = _candidate()

    record = build_candidate_created_audit(candidate)

    assert record.candidate_id == candidate.candidate_id
    assert record.mission_id == candidate.mission_id
    assert record.activity_id == candidate.activity_id
    assert record.workstream_id == candidate.workstream_id
    assert record.agent_id == candidate.agent_id
    assert record.agent_profile_id == candidate.agent_profile_id
    assert record.request_id == candidate.request_id
    assert record.police_evaluation_id == candidate.police_evaluation_id
    assert record.police_evaluation_outcome == candidate.police_evaluation_outcome
    assert record.operation_key == candidate.operation_key


def test_audit_record_does_not_store_candidate_object() -> None:
    candidate = _candidate()
    record = build_candidate_created_audit(candidate)

    assert candidate not in record.__dict__.values()


def test_details_is_immutable_tuple() -> None:
    record = _record(details=("created",))

    assert record.details == ("created",)
    assert isinstance(record.details, tuple)

    with pytest.raises(TypeError):
        _record(details=["created"])


@pytest.mark.parametrize(
    "field_name",
    [
        "audit_id",
        "candidate_id",
        "mission_id",
        "agent_id",
        "agent_profile_id",
        "police_evaluation_id",
        "police_evaluation_outcome",
        "operation_key",
    ],
)
def test_required_string_fields_are_non_empty(field_name: str) -> None:
    with pytest.raises(ValueError, match=f"{field_name} must be non-empty"):
        _record(**{field_name: ""})


def test_audit_record_has_no_runtime_authority_fields() -> None:
    names = {field.name for field in fields(CandidateAuditRecord)}

    assert "permitted" not in names
    assert "authorized" not in names
    assert "PoliceDecision" not in names
    assert "token_ref" not in names
    assert "binding_ref" not in names
    assert "authorized_plan_ref" not in names


def test_no_callable_public_record_attributes() -> None:
    record = _record()

    public_values = [
        value for name, value in vars(record).items() if not name.startswith("_")
    ]

    assert public_values
    assert all(not callable(value) for value in public_values)


def test_building_audit_does_not_mutate_candidate() -> None:
    candidate = _candidate()
    before = candidate.__dict__.copy()

    build_candidate_created_audit(candidate)

    assert candidate.__dict__ == before


def test_audit_can_be_built_from_pending_gate_candidate() -> None:
    candidate = _candidate()

    assert candidate.candidate_status is MissionExecutionCandidateStatus.PENDING_GATE
    record = build_candidate_created_audit(candidate)

    assert record.candidate_id == candidate.candidate_id


def test_audit_stores_police_evaluation_outcome_as_scalar_string_only() -> None:
    record = build_candidate_created_audit(_candidate())

    assert record.police_evaluation_outcome == "ALLOW"
    assert isinstance(record.police_evaluation_outcome, str)
