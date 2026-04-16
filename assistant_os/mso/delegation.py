"""Structured delegation helpers for sovereign -> worker handoff."""

from __future__ import annotations

from dataclasses import asdict
import uuid

from ..contracts import now_iso
from .contracts import DelegationTask, ExecutionCapability, SovereignIntent

_BASIC_COGNITIVE_OPERATIONS = frozenset(
    {
        "read_system_state",
        "summarize_context",
        "classify_issue",
        "consistency_check",
        "simulate",
    }
)


def validate_sovereign_intent(intent: SovereignIntent) -> None:
    if not intent.user_request_ref:
        raise ValueError("SovereignIntent.user_request_ref is required")
    if not intent.intent_id or not intent.session_id:
        raise ValueError("SovereignIntent identity fields are required")


def validate_delegation_task(task: DelegationTask) -> None:
    if task.task_type != "BASIC_COGNITIVE_EXECUTION":
        raise ValueError("DelegationTask must map to BASIC_COGNITIVE_EXECUTION")
    if not task.allowed_operations:
        raise ValueError("DelegationTask.allowed_operations is required")
    if not task.scope:
        raise ValueError("DelegationTask.scope is required")
    if not task.expected_output_schema:
        raise ValueError("DelegationTask.expected_output_schema is required")
    invalid = [item for item in task.allowed_operations if item not in _BASIC_COGNITIVE_OPERATIONS]
    if invalid:
        raise ValueError(f"DelegationTask contains unsupported operations: {invalid}")


def issue_execution_capability(task: DelegationTask, *, issued_by: str = "kernel") -> ExecutionCapability:
    """Issue an explicit execution capability for a validated delegation task."""
    validate_delegation_task(task)
    return ExecutionCapability(
        capability_id=str(uuid.uuid4()),
        task_id=task.task_id,
        execution_class=task.task_type,
        allowed_operations=list(task.allowed_operations),
        scope=dict(task.scope),
        issued_at=now_iso(),
        expires_at=task.expiry,
        issued_by=issued_by,
        trace_id=task.trace_id,
    )


def coerce_sovereign_intent(raw: dict) -> SovereignIntent:
    intent = SovereignIntent(**raw)
    validate_sovereign_intent(intent)
    return intent


def coerce_delegation_task(raw: dict) -> DelegationTask:
    task = DelegationTask(**raw)
    validate_delegation_task(task)
    return task


def as_trace_dict(obj) -> dict:
    return asdict(obj)
