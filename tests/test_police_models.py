from datetime import datetime
from uuid import UUID

from assistant_os.police.models import (
    PoliceAuditEvent,
    PoliceEvaluation,
    PoliceEvaluationType,
    RiskLevel,
)


def test_evaluations_create_stable_ids():
    evaluation = PoliceEvaluation(
        request_id="req-1",
        outcome=PoliceEvaluationType.ALLOW,
        reason="Allowed.",
        risk_level=RiskLevel.LOW,
    )

    UUID(evaluation.evaluation_id)
    UUID(evaluation.audit_event_id)
    assert evaluation.evaluation_id != evaluation.audit_event_id
    assert evaluation.evaluation_id == evaluation.evaluation_id


def test_default_timestamps_are_timezone_aware():
    evaluation = PoliceEvaluation(
        request_id="req-1",
        outcome=PoliceEvaluationType.ALLOW,
        reason="Allowed.",
        risk_level=RiskLevel.LOW,
    )
    event = PoliceAuditEvent(
        request_id="req-1",
        evaluation_id=evaluation.evaluation_id,
        event_type="police.allow",
        message="Allowed.",
        actor="police",
    )

    assert isinstance(evaluation.created_at, datetime)
    assert evaluation.created_at.tzinfo is not None
    assert evaluation.created_at.utcoffset() is not None
    assert event.created_at.tzinfo is not None
    assert event.created_at.utcoffset() is not None


def test_police_evaluation_type_values():
    assert PoliceEvaluationType.ALLOW.value == "ALLOW"
    assert PoliceEvaluationType.DENY.value == "DENY"
    assert PoliceEvaluationType.REQUIRES_CONFIRMATION.value == "REQUIRES_CONFIRMATION"


def test_risk_level_values():
    assert RiskLevel.LOW.value == "LOW"
    assert RiskLevel.MEDIUM.value == "MEDIUM"
    assert RiskLevel.HIGH.value == "HIGH"
    assert RiskLevel.CRITICAL.value == "CRITICAL"


def test_police_audit_event_shape():
    event = PoliceAuditEvent(
        request_id="req-1",
        evaluation_id="eval-1",
        event_type="police.allow",
        message="Allowed.",
        actor="police",
        metadata={"risk_level": "LOW"},
    )

    UUID(event.event_id)
    assert event.request_id == "req-1"
    assert event.evaluation_id == "eval-1"
    assert event.event_type == "police.allow"
    assert event.message == "Allowed."
    assert event.actor == "police"
    assert event.metadata == {"risk_level": "LOW"}
