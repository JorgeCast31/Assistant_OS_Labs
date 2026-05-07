from assistant_os.agents.permissions import (
    AgentOperationalStatus,
    AgentPermissionProfile,
    AgentPoliceRequest,
    build_police_check_request,
    evaluate_agent_permissions,
)
from assistant_os.police.models import PoliceEvaluationType


def _profile(**overrides):
    values = {
        "agent_id": "agent-1",
        "display_name": "Agent One",
        "role": "support",
        "declared_capabilities": frozenset({"read"}),
        "permitted_tools": frozenset({"search"}),
        "permitted_environments": frozenset({"local"}),
    }
    values.update(overrides)
    return AgentPermissionProfile(**values)


def _request(**overrides):
    values = {
        "request_id": "req-1",
        "agent_id": "agent-1",
        "requested_by": "operator",
        "requested_tool": "search",
        "requested_environment": "local",
        "requested_capabilities": ("read",),
    }
    values.update(overrides)
    return AgentPoliceRequest(**values)


def test_allowed_agent_tool_environment_and_capability_returns_allow():
    evaluation = evaluate_agent_permissions(_profile(), _request())

    assert evaluation.outcome is PoliceEvaluationType.ALLOW


def test_forbidden_tool_returns_deny():
    evaluation = evaluate_agent_permissions(
        _profile(),
        _request(requested_tool="write_file"),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.denied_tools == ["write_file"]


def test_forbidden_environment_returns_deny():
    evaluation = evaluate_agent_permissions(
        _profile(),
        _request(requested_environment="prod"),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.denied_environments == ["prod"]


def test_missing_capability_returns_deny():
    evaluation = evaluate_agent_permissions(
        _profile(),
        _request(requested_capabilities=("read", "write")),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.violations[0].code == "CAPABILITY_NOT_PERMITTED"


def test_requires_review_returns_requires_confirmation():
    evaluation = evaluate_agent_permissions(
        _profile(requires_review=True),
        _request(),
    )

    assert evaluation.outcome is PoliceEvaluationType.REQUIRES_CONFIRMATION
    assert evaluation.required_confirmation_reason == "Agent permission requires review."


def test_disabled_agent_returns_deny():
    evaluation = evaluate_agent_permissions(
        _profile(status=AgentOperationalStatus.DISABLED),
        _request(),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.why_blocked == "Agent status is DISABLED."


def test_inactive_agent_returns_deny():
    evaluation = evaluate_agent_permissions(
        _profile(status=AgentOperationalStatus.INACTIVE),
        _request(),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.why_blocked == "Agent status is INACTIVE."


def test_degraded_agent_requires_confirmation_when_otherwise_allowed():
    evaluation = evaluate_agent_permissions(
        _profile(status=AgentOperationalStatus.DEGRADED),
        _request(),
    )

    assert evaluation.outcome is PoliceEvaluationType.REQUIRES_CONFIRMATION
    assert evaluation.required_confirmation_reason == "Agent permission requires review."


def test_degraded_agent_still_denies_forbidden_requests():
    evaluation = evaluate_agent_permissions(
        _profile(status=AgentOperationalStatus.DEGRADED),
        _request(requested_tool="write_file"),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.denied_tools == ["write_file"]


def test_mission_id_and_activity_id_are_threaded_into_police_check_request():
    police_request = build_police_check_request(
        _request(mission_id="mission-1", activity_id="activity-1")
    )

    assert police_request.mission_id == "mission-1"
    assert police_request.activity_id == "activity-1"


def test_allow_outcome_is_pre_evaluation_not_execution_authorization():
    evaluation = evaluate_agent_permissions(_profile(), _request())

    assert evaluation.outcome is PoliceEvaluationType.ALLOW
    assert not hasattr(evaluation, "permitted")
    assert not hasattr(evaluation, "authorization")
    assert not hasattr(evaluation, "grant")
