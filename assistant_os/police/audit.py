from .models import PoliceAuditEvent, PoliceCheckRequest, PoliceEvaluation


def build_audit_event(
    request: PoliceCheckRequest,
    evaluation: PoliceEvaluation,
    actor: str = "police",
) -> PoliceAuditEvent:
    return PoliceAuditEvent(
        event_id=evaluation.audit_event_id,
        request_id=request.request_id,
        evaluation_id=evaluation.evaluation_id,
        event_type=f"police.{evaluation.outcome.value.lower()}",
        message=evaluation.reason,
        actor=actor,
        metadata={
            "agent_id": request.agent_id,
            "requested_by": request.requested_by,
            "risk_level": evaluation.risk_level.value,
        },
    )
