"""
machine_operator_audit.py -- Structured audit events for MACHINE_OPERATOR.

This audit model is lane-local and intentionally backend-agnostic.
It records control-plane milestones without implying any real execution.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from ..sandbox.audit import AuditLog


class MachineOperatorAuditEventType:
    MO_INTENT_RECEIVED = "mo_intent_received"
    MO_POLICY_EVALUATED = "mo_policy_evaluated"
    MO_STEP_STARTED = "mo_step_started"
    MO_STEP_COMPLETED = "mo_step_completed"
    MO_STEP_PARTIAL = "mo_step_partial"
    MO_EXECUTION_FAILED = "mo_execution_failed"
    MO_EXECUTION_SKIPPED = "mo_execution_skipped"
    MO_BACKEND_UNAVAILABLE = "mo_backend_unavailable"
    MO_ABORTED = "mo_aborted"
    MO_EPHEMERAL_SCOPE_CLOSED = "mo_ephemeral_scope_closed"


@dataclass(frozen=True)
class MachineOperatorAuditEvent:
    """Structured, log-safe audit event for the MACHINE_OPERATOR lane."""

    event_id: str
    event_type: str
    plan_id: str
    execution_id: str
    trace_id: str
    intent_id: str
    correlation_id: str
    capability_name: str
    status: str
    detail: str
    backend_state: str
    timestamp: float

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "plan_id": self.plan_id,
            "execution_id": self.execution_id,
            "trace_id": self.trace_id,
            "intent_id": self.intent_id,
            "correlation_id": self.correlation_id,
            "capability_name": self.capability_name,
            "status": self.status,
            "detail": self.detail,
            "backend_state": self.backend_state,
            "timestamp": self.timestamp,
        }


MACHINE_OPERATOR_AUDIT_LOG: AuditLog = AuditLog()


def emit_machine_operator_event(
    *,
    event_type: str,
    plan_id: str,
    execution_id: str,
    trace_id: str,
    intent_id: str,
    correlation_id: str,
    capability_name: str,
    status: str,
    detail: str,
    backend_state: str = "",
) -> str:
    """Emit one MACHINE_OPERATOR audit event and return its identifier."""
    event = MachineOperatorAuditEvent(
        event_id=f"moevt-{uuid.uuid4().hex[:12]}",
        event_type=event_type,
        plan_id=plan_id,
        execution_id=execution_id,
        trace_id=trace_id,
        intent_id=intent_id,
        correlation_id=correlation_id,
        capability_name=capability_name,
        status=status,
        detail=detail,
        backend_state=backend_state,
        timestamp=time.time(),
    )
    MACHINE_OPERATOR_AUDIT_LOG.emit(event)
    return event.event_id
