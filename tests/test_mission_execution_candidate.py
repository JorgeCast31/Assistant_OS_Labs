from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from assistant_os.agents.permissions import AgentPermissionProfile, AgentPoliceRequest
from assistant_os.missions.execution_candidate import (
    MissionExecutionCandidate,
    MissionExecutionCandidateStatus,
    build_mission_execution_candidate,
)
from assistant_os.police.models import PoliceEvaluation, PoliceEvaluationType, RiskLevel


def _profile(**overrides):
    values = {
        "agent_id": "agent-1",
        "display_name": "Agent One",
        "role": "support",
        "version": "1.2.3",
        "declared_capabilities": frozenset({"read"}),
        "permitted_tools": frozenset({"search"}),
        "permitted_environments": frozenset({"local"}),
    }
    values.update(overrides)
    return AgentPermissionProfile(**values)


def _request(**overrides):
    values = {
        "request_id": "request-1",
        "agent_id": "agent-1",
        "requested_by": "operator",
        "requested_tool": "search",
        "requested_environment": "local",
        "requested_capabilities": ("read",),
        "mission_id": "mission-1",
        "activity_id": "activity-1",
    }
    values.update(overrides)
    return AgentPoliceRequest(**values)


def _evaluation(outcome=PoliceEvaluationType.ALLOW, **overrides):
    values = {
        "request_id": "request-1",
        "outcome": outcome,
        "reason": "checked",
        "risk_level": RiskLevel.LOW,
    }
    values.update(overrides)
    return PoliceEvaluation(**values)


def _candidate(
    *,
    profile=None,
    request=None,
    evaluation=None,
    operation_key="mission-1:activity-1:agent-1",
):
    return build_mission_execution_candidate(
        mission_id="mission-1",
        activity_id="activity-1",
        workstream_id="workstream-1",
        agent_profile=profile or _profile(),
        agent_request=request or _request(),
        police_evaluation=evaluation or _evaluation(),
        operation_key=operation_key,
    )


def test_candidate_is_frozen():
    candidate = _candidate()

    with pytest.raises(FrozenInstanceError):
        candidate.mission_id = "changed"


def test_candidate_status_is_always_pending_gate():
    candidate = _candidate()

    assert candidate.candidate_status is MissionExecutionCandidateStatus.PENDING_GATE
    assert [status.value for status in MissionExecutionCandidateStatus] == ["pending_gate"]


def test_allow_evaluation_creates_candidate():
    candidate = _candidate(evaluation=_evaluation(PoliceEvaluationType.ALLOW))

    assert isinstance(candidate, MissionExecutionCandidate)
    assert candidate.candidate_status is MissionExecutionCandidateStatus.PENDING_GATE


def test_deny_evaluation_raises_value_error():
    with pytest.raises(ValueError, match="requires PoliceEvaluationType.ALLOW"):
        _candidate(evaluation=_evaluation(PoliceEvaluationType.DENY))


def test_requires_confirmation_evaluation_raises_value_error():
    with pytest.raises(ValueError, match="requires PoliceEvaluationType.ALLOW"):
        _candidate(evaluation=_evaluation(PoliceEvaluationType.REQUIRES_CONFIRMATION))


def test_candidate_id_is_non_empty_uuid_string():
    candidate_id = _candidate().candidate_id

    assert candidate_id
    assert str(UUID(candidate_id)) == candidate_id


def test_created_at_is_timezone_aware():
    created_at = _candidate().created_at

    assert created_at.tzinfo is not None
    assert created_at.utcoffset() is not None


def test_requested_capabilities_is_tuple():
    candidate = _candidate(request=_request(requested_capabilities=("read", "inspect")))

    assert candidate.requested_capabilities == ("read", "inspect")
    assert isinstance(candidate.requested_capabilities, tuple)


def test_live_objects_are_not_stored():
    profile = _profile()
    request = _request()
    evaluation = _evaluation()

    candidate = _candidate(profile=profile, request=request, evaluation=evaluation)

    assert profile not in candidate.__dict__.values()
    assert request not in candidate.__dict__.values()
    assert evaluation not in candidate.__dict__.values()


def test_candidate_has_no_forbidden_authority_fields():
    candidate = _candidate()

    assert not hasattr(candidate, "permitted")
    assert not hasattr(candidate, "decision_id")
    assert not hasattr(candidate, "token_ref")
    assert not hasattr(candidate, "binding_ref")
    assert not hasattr(candidate, "authorized_plan_ref")
    assert not hasattr(candidate, "police_decision")
    assert not hasattr(candidate, "police_gate_request")


def test_candidate_has_no_callable_public_attributes():
    candidate = _candidate()

    for name in candidate.__dataclass_fields__:
        assert not callable(getattr(candidate, name))


def test_operation_key_is_non_empty():
    assert _candidate().operation_key

    with pytest.raises(ValueError, match="operation_key must be non-empty"):
        _candidate(operation_key="")


def test_evaluation_outcome_is_allow_snapshot_string():
    candidate = _candidate(evaluation=_evaluation(PoliceEvaluationType.ALLOW))

    assert candidate.police_evaluation_outcome == PoliceEvaluationType.ALLOW.value
    assert isinstance(candidate.police_evaluation_outcome, str)


def test_build_function_snapshots_mission_context():
    candidate = build_mission_execution_candidate(
        mission_id="mission-2",
        activity_id="activity-2",
        workstream_id="workstream-2",
        agent_profile=_profile(),
        agent_request=_request(),
        police_evaluation=_evaluation(),
        operation_key="mission-2:activity-2:agent-1",
    )

    assert candidate.mission_id == "mission-2"
    assert candidate.activity_id == "activity-2"
    assert candidate.workstream_id == "workstream-2"


def test_build_function_snapshots_agent_profile_refs():
    profile = _profile(version="2.0.0")

    candidate = _candidate(profile=profile)

    assert candidate.agent_profile_id == profile.profile_id
    assert candidate.agent_profile_version == "2.0.0"
    assert candidate.profile_derived_at == profile.derived_at


def test_build_function_snapshots_request_fields():
    request = _request(
        request_id="request-2",
        requested_tool="summarize",
        requested_environment="review",
        requested_capabilities=("read", "summarize"),
    )

    candidate = _candidate(request=request)

    assert candidate.request_id == "request-2"
    assert candidate.requested_tool == "summarize"
    assert candidate.requested_environment == "review"
    assert candidate.requested_capabilities == ("read", "summarize")


def test_build_function_snapshots_evaluation_fields():
    evaluation = _evaluation(risk_level=RiskLevel.MEDIUM)

    candidate = _candidate(evaluation=evaluation)

    assert candidate.police_evaluation_id == evaluation.evaluation_id
    assert candidate.evaluation_risk_level == "MEDIUM"
    assert candidate.police_audit_event_id == evaluation.audit_event_id


def test_candidate_invariants_reject_non_tuple_capabilities():
    with pytest.raises(TypeError, match="requested_capabilities must be a tuple"):
        MissionExecutionCandidate(
            mission_id="mission-1",
            activity_id=None,
            workstream_id=None,
            agent_id="agent-1",
            agent_profile_id="profile-1",
            agent_profile_version=None,
            profile_derived_at=_profile().derived_at,
            request_id="request-1",
            requested_tool=None,
            requested_environment=None,
            requested_capabilities=["read"],
            police_evaluation_id="evaluation-1",
            police_evaluation_outcome="ALLOW",
            evaluation_risk_level="LOW",
            police_audit_event_id=None,
            operation_key="op-1",
            candidate_status=MissionExecutionCandidateStatus.PENDING_GATE,
        )
