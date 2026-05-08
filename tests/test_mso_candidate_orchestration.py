from dataclasses import FrozenInstanceError

import pytest

from assistant_os.audit.sink import AuditSink
from assistant_os.missions.candidate_audit import CandidateAuditRecord
from assistant_os.missions.execution_candidate import (
    MissionExecutionCandidate,
    MissionExecutionCandidateStatus,
)
from assistant_os.missions.models import Mission
from assistant_os.missions.service import MissionRegistry
from assistant_os.missions.store import InMemoryMissionStore
from assistant_os.mso.candidate_orchestration import (
    CandidateOrchestrationOutcome,
    MSOCandidateOrchestrationRequest,
    MSOCandidateOrchestrationResult,
    orchestrate_mission_execution_candidate,
)
from assistant_os.police.models import PoliceAuditEvent, PoliceEvaluation


class RecordingAuditSink(AuditSink):
    def __init__(self) -> None:
        self.records: list[object] = []

    def emit(self, record: object) -> None:
        self.records.append(record)


def _registry_with_mission() -> tuple[MissionRegistry, Mission]:
    registry = MissionRegistry(InMemoryMissionStore())
    mission = Mission(
        title="Existing mission",
        macro_goal="Existing macro goal",
        created_by="test",
        source_surface="test",
    )
    registry.store.create_mission(mission)
    return registry, mission


def _request(mission: Mission, **overrides: object) -> MSOCandidateOrchestrationRequest:
    data = {
        "mission_id": mission.mission_id,
        "agent_name": "host_launcher",
        "operation_key": "op.host.launch",
        "requested_by": "mso",
        "requested_tool": "host.launch",
        "requested_environment": "controlled_host",
        "requested_capabilities": ("host_launch_app",),
        "risk_signals": (),
    }
    data.update(overrides)
    return MSOCandidateOrchestrationRequest(**data)


def _orchestrate(
    request: MSOCandidateOrchestrationRequest,
    sink: RecordingAuditSink | None = None,
) -> tuple[MSOCandidateOrchestrationResult, RecordingAuditSink]:
    registry, _mission = _registry_with_mission()
    if registry.store.get_mission(request.mission_id) is None:
        registry.store.create_mission(
            Mission(
                title="Imported mission",
                macro_goal="Imported macro goal",
                created_by="test",
                source_surface="test",
                mission_id=request.mission_id,
            )
        )
    resolved_sink = sink or RecordingAuditSink()
    return (
        orchestrate_mission_execution_candidate(
            request=request,
            mission_registry=registry,
            audit_sink=resolved_sink,
        ),
        resolved_sink,
    )


def test_request_is_frozen() -> None:
    _registry, mission = _registry_with_mission()
    request = _request(mission)

    with pytest.raises(FrozenInstanceError):
        request.agent_name = "mutated"  # type: ignore[misc]


def test_result_is_frozen() -> None:
    _registry, mission = _registry_with_mission()
    result, _sink = _orchestrate(_request(mission))

    with pytest.raises(FrozenInstanceError):
        result.detail = "mutated"  # type: ignore[misc]


def test_result_created_at_is_timezone_aware() -> None:
    _registry, mission = _registry_with_mission()
    result, _sink = _orchestrate(_request(mission))

    assert result.created_at.tzinfo is not None
    assert result.created_at.utcoffset() is not None


def test_allow_returns_live_objects_and_created_outcome() -> None:
    _registry, mission = _registry_with_mission()

    result, _sink = _orchestrate(_request(mission))

    assert result.outcome is CandidateOrchestrationOutcome.CANDIDATE_CREATED
    assert isinstance(result.police_evaluation, PoliceEvaluation)
    assert isinstance(result.police_audit_event, PoliceAuditEvent)
    assert isinstance(result.candidate, MissionExecutionCandidate)
    assert isinstance(result.candidate_audit_record, CandidateAuditRecord)


def test_allow_candidate_remains_pending_gate() -> None:
    _registry, mission = _registry_with_mission()

    result, _sink = _orchestrate(_request(mission))

    assert result.candidate is not None
    assert result.candidate.candidate_status is MissionExecutionCandidateStatus.PENDING_GATE


def test_allow_emits_police_audit_then_candidate_audit() -> None:
    _registry, mission = _registry_with_mission()
    sink = RecordingAuditSink()

    _orchestrate(_request(mission), sink)

    assert len(sink.records) == 2
    assert isinstance(sink.records[0], PoliceAuditEvent)
    assert isinstance(sink.records[1], CandidateAuditRecord)


def test_deny_returns_live_police_objects_without_candidate_audit() -> None:
    _registry, mission = _registry_with_mission()
    sink = RecordingAuditSink()

    result, _sink = _orchestrate(_request(mission, requested_tool="outside.tool"), sink)

    assert result.outcome is CandidateOrchestrationOutcome.DENIED
    assert isinstance(result.police_evaluation, PoliceEvaluation)
    assert isinstance(result.police_audit_event, PoliceAuditEvent)
    assert result.candidate is None
    assert result.candidate_audit_record is None
    assert len(sink.records) == 1
    assert isinstance(sink.records[0], PoliceAuditEvent)


def test_requires_confirmation_returns_live_police_objects_without_candidate_audit() -> None:
    _registry, mission = _registry_with_mission()
    sink = RecordingAuditSink()

    result, _sink = _orchestrate(
        _request(
            mission,
            agent_name="code_executor",
            requested_tool="code.review",
            requested_environment="local",
            requested_capabilities=("code_execute",),
        ),
        sink,
    )

    assert result.outcome is CandidateOrchestrationOutcome.REQUIRES_CONFIRMATION
    assert isinstance(result.police_evaluation, PoliceEvaluation)
    assert isinstance(result.police_audit_event, PoliceAuditEvent)
    assert result.candidate is None
    assert result.candidate_audit_record is None
    assert result.detail == "Agent permission requires review."
    assert len(sink.records) == 1
    assert isinstance(sink.records[0], PoliceAuditEvent)


def test_audit_sink_is_mandatory() -> None:
    registry, mission = _registry_with_mission()

    with pytest.raises(TypeError):
        orchestrate_mission_execution_candidate(
            request=_request(mission),
            mission_registry=registry,
        )


def test_unknown_agent_returns_agent_not_found_without_audit() -> None:
    registry, mission = _registry_with_mission()
    sink = RecordingAuditSink()

    result = orchestrate_mission_execution_candidate(
        request=_request(mission, agent_name="missing_agent"),
        mission_registry=registry,
        audit_sink=sink,
    )

    assert result.outcome is CandidateOrchestrationOutcome.AGENT_NOT_FOUND
    assert result.police_evaluation is None
    assert result.police_audit_event is None
    assert result.candidate is None
    assert result.candidate_audit_record is None
    assert "Agent unavailable" in result.detail
    assert sink.records == []


def test_request_id_is_generated_or_preserved() -> None:
    _registry, mission = _registry_with_mission()

    generated = _request(mission)
    explicit = _request(mission, request_id="request-123")

    assert generated.request_id
    assert explicit.request_id == "request-123"


def test_operation_key_and_mission_fields_are_preserved() -> None:
    _registry, mission = _registry_with_mission()

    result, _sink = _orchestrate(
        _request(
            mission,
            operation_key="op.custom",
            activity_id="activity-1",
            workstream_id="workstream-1",
        )
    )

    assert result.candidate is not None
    assert result.candidate_audit_record is not None
    assert result.candidate.operation_key == "op.custom"
    assert result.candidate.mission_id == mission.mission_id
    assert result.candidate.activity_id == "activity-1"
    assert result.candidate.workstream_id == "workstream-1"
    assert result.candidate_audit_record.operation_key == "op.custom"
    assert result.candidate_audit_record.mission_id == mission.mission_id
    assert result.candidate_audit_record.activity_id == "activity-1"
    assert result.candidate_audit_record.workstream_id == "workstream-1"


def test_result_has_no_forbidden_fields() -> None:
    _registry, mission = _registry_with_mission()
    result, _sink = _orchestrate(_request(mission))

    assert not hasattr(result, "permitted")
    assert not hasattr(result, "token_ref")
    assert not hasattr(result, "entrypoint")
    assert not hasattr(result, "execute")


def test_audit_sink_emission_order_is_deterministic() -> None:
    _registry, mission = _registry_with_mission()
    sink = RecordingAuditSink()

    _orchestrate(_request(mission), sink)

    assert [type(record) for record in sink.records] == [
        PoliceAuditEvent,
        CandidateAuditRecord,
    ]


def test_request_rejects_non_tuple_collections() -> None:
    _registry, mission = _registry_with_mission()

    with pytest.raises(TypeError):
        _request(mission, requested_capabilities=["host_launch_app"])  # type: ignore[list-item]

    with pytest.raises(TypeError):
        _request(mission, risk_signals=["low"])  # type: ignore[list-item]
