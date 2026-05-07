from assistant_os.police.audit import build_audit_event
from assistant_os.police.enforcer import PoliceEnforcer
from assistant_os.police.models import (
    AgentPermission,
    PoliceCheckRequest,
    PoliceEvaluationType,
    RiskLevel,
)


def _permission(requires_review=False):
    return AgentPermission(
        agent_id="agent-1",
        allowed_tools=["search", "read_file"],
        allowed_environments=["local", "sandbox"],
        capability_scope=["read", "inspect"],
        requires_review=requires_review,
    )


def _request(**overrides):
    values = {
        "request_id": "req-1",
        "requested_by": "user",
        "agent_id": "agent-1",
        "requested_tool": "search",
        "requested_environment": "local",
        "requested_capabilities": ["read"],
        "risk_signals": [],
    }
    values.update(overrides)
    return PoliceCheckRequest(**values)


def test_allow_when_tool_env_capabilities_are_permitted():
    evaluation = PoliceEnforcer().evaluate(_request(), _permission())

    assert evaluation.outcome is PoliceEvaluationType.ALLOW
    assert evaluation.why_blocked is None
    assert evaluation.violations == []
    assert evaluation.risk_level is RiskLevel.LOW


def test_deny_unauthorized_tool():
    evaluation = PoliceEnforcer().evaluate(
        _request(requested_tool="write_file"),
        _permission(),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.denied_tools == ["write_file"]
    assert evaluation.why_blocked
    assert evaluation.violations[0].code == "TOOL_NOT_PERMITTED"


def test_deny_unauthorized_environment():
    evaluation = PoliceEnforcer().evaluate(
        _request(requested_environment="prod"),
        _permission(),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.denied_environments == ["prod"]
    assert evaluation.violations[0].code == "ENVIRONMENT_NOT_PERMITTED"


def test_deny_missing_capability():
    evaluation = PoliceEnforcer().evaluate(
        _request(requested_capabilities=["read", "write"]),
        _permission(),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert [violation.code for violation in evaluation.violations] == [
        "CAPABILITY_NOT_PERMITTED"
    ]


def test_deny_critical_risk():
    evaluation = PoliceEnforcer().evaluate(
        _request(risk_signals=["critical"]),
        _permission(),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.risk_level is RiskLevel.CRITICAL
    assert evaluation.violations[0].code == "CRITICAL_RISK_SIGNAL"


def test_requires_confirmation_when_agent_requires_review():
    evaluation = PoliceEnforcer().evaluate(
        _request(),
        _permission(requires_review=True),
    )

    assert evaluation.outcome is PoliceEvaluationType.REQUIRES_CONFIRMATION
    assert evaluation.required_confirmation_reason == "Agent permission requires review."
    assert evaluation.why_blocked is None


def test_deny_has_priority_over_requires_confirmation():
    evaluation = PoliceEnforcer().evaluate(
        _request(requested_tool="write_file"),
        _permission(requires_review=True),
    )

    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.required_confirmation_reason is None
    assert evaluation.denied_tools == ["write_file"]


def test_audit_event_can_be_built_from_evaluation():
    request = _request()
    evaluation = PoliceEnforcer().evaluate(request, _permission())

    event = build_audit_event(request, evaluation)

    assert event.event_id == evaluation.audit_event_id
    assert event.request_id == request.request_id
    assert event.evaluation_id == evaluation.evaluation_id
    assert event.event_type == "police.allow"
    assert event.actor == "police"
    assert event.metadata["risk_level"] == "LOW"
