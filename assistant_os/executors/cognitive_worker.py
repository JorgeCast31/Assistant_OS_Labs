"""Bounded local cognitive worker for BASIC_COGNITIVE_EXECUTION."""

from __future__ import annotations

import json
import re
import time
import uuid

from ..contracts import now_iso
from ..mso.contracts import (
    DelegationTask,
    EscalationRequest,
    ExecutionCapability,
    ExecutionReport,
    WorkerExecutionLimits,
    WorkerScopeValidationResult,
)
from ..mso.system_state import build_system_state_snapshot

WORKER_ID = "local_cognitive_worker"
DEFAULT_TIMEOUT_MS = 250
DEFAULT_MAX_INPUT_REFS = 8
DEFAULT_MAX_ARTIFACT_COUNT = 6
DEFAULT_MAX_ARTIFACT_BYTES = 4096
_SUPPORTED_OPERATIONS = frozenset(
    {
        "read_system_state",
        "summarize_context",
        "classify_issue",
        "consistency_check",
        "simulate",
    }
)
_ALLOWED_INPUT_REF_PATTERN = re.compile(r"^(request|state|trace|report|anomaly):[A-Za-z0-9._:-]+$")
_FORBIDDEN_INPUT_PATTERNS = ("..", "/", "\\", "%2f", "%5c", "http:", "https:", "file:", "socket:", "tcp:", "udp:")
_NETWORK_SCOPE_KEYS = ("allow_network", "network_access", "requires_network", "url", "host", "socket")


def _limits_for_task(task: DelegationTask) -> WorkerExecutionLimits:
    return WorkerExecutionLimits(
        timeout_ms=int(task.scope.get("timeout_ms", DEFAULT_TIMEOUT_MS)),
        max_operations=int(task.scope.get("max_operations", len(task.allowed_operations))),
        max_input_refs=int(task.scope.get("max_input_refs", DEFAULT_MAX_INPUT_REFS)),
        max_artifact_count=int(task.scope.get("max_artifact_count", DEFAULT_MAX_ARTIFACT_COUNT)),
        max_artifact_bytes=int(task.scope.get("max_artifact_bytes", DEFAULT_MAX_ARTIFACT_BYTES)),
        single_flight=True,
    )


def _build_escalation(task: DelegationTask, *, requested_capability: str, requested_scope: dict, reason: str, current_limit_hit: str) -> EscalationRequest:
    return EscalationRequest(
        escalation_id=str(uuid.uuid4()),
        task_id=task.task_id,
        worker_id=WORKER_ID,
        requested_capability=requested_capability,
        requested_scope=requested_scope,
        reason=reason,
        current_limit_hit=current_limit_hit,
        trace_id=task.trace_id,
        timestamp=now_iso(),
    )


def _validate_input_refs(task: DelegationTask, *, limits: WorkerExecutionLimits) -> WorkerScopeValidationResult:
    if len(task.input_refs) > limits.max_input_refs:
        return WorkerScopeValidationResult(
            allowed=False,
            reason_code="max_input_refs_exceeded",
            detail=f"Delegation task exceeded max_input_refs={limits.max_input_refs}.",
            rejected_refs=list(task.input_refs[limits.max_input_refs:]),
        )
    normalized_refs: list[str] = []
    rejected_refs: list[str] = []
    for ref in task.input_refs:
        lowered = ref.lower()
        if any(token in lowered for token in _FORBIDDEN_INPUT_PATTERNS):
            rejected_refs.append(ref)
            continue
        if not _ALLOWED_INPUT_REF_PATTERN.match(ref):
            rejected_refs.append(ref)
            continue
        normalized_refs.append(ref)
    if rejected_refs:
        return WorkerScopeValidationResult(
            allowed=False,
            reason_code="invalid_input_ref",
            detail=f"Input refs exceed bounded readable scope: {rejected_refs}",
            normalized_refs=normalized_refs,
            rejected_refs=rejected_refs,
        )
    return WorkerScopeValidationResult(
        allowed=True,
        reason_code="ok",
        detail="Input refs stayed within the bounded readable scope.",
        normalized_refs=normalized_refs,
    )


def _validate_network_posture(task: DelegationTask) -> WorkerScopeValidationResult:
    if any(bool(task.scope.get(key)) for key in _NETWORK_SCOPE_KEYS):
        return WorkerScopeValidationResult(
            allowed=False,
            reason_code="network_denied",
            detail="Worker tasks cannot request network access in Sprint 10.",
        )
    if any(ref.lower().startswith(("http:", "https:", "socket:", "tcp:", "udp:")) for ref in task.input_refs):
        return WorkerScopeValidationResult(
            allowed=False,
            reason_code="network_denied",
            detail="Worker input refs cannot require URL or socket access.",
            rejected_refs=list(task.input_refs),
        )
    return WorkerScopeValidationResult(allowed=True, reason_code="ok", detail="Network posture is deny-by-default.")


def _validate_task_scope(task: DelegationTask, capability: ExecutionCapability) -> EscalationRequest | None:
    limits = _limits_for_task(task)
    if capability.execution_class != "BASIC_COGNITIVE_EXECUTION":
        return _build_escalation(
            task,
            requested_capability="BASIC_COGNITIVE_EXECUTION",
            requested_scope=task.scope,
            reason="Capability execution class mismatch.",
            current_limit_hit="execution_class_mismatch",
        )
    invalid_operations = [item for item in task.allowed_operations if item not in _SUPPORTED_OPERATIONS]
    if invalid_operations:
        return _build_escalation(
            task,
            requested_capability=task.requires_capability,
            requested_scope=task.scope,
            reason=f"Unsupported operations requested: {invalid_operations}",
            current_limit_hit="unsupported_operation",
        )
    if set(task.allowed_operations) - set(capability.allowed_operations):
        return _build_escalation(
            task,
            requested_capability=task.requires_capability,
            requested_scope=task.scope,
            reason="Requested operations exceed issued capability.",
            current_limit_hit="operation_not_allowed",
        )
    scope_domain = capability.scope.get("domain")
    task_domain = task.scope.get("domain")
    if scope_domain and task_domain and scope_domain != task_domain:
        return _build_escalation(
            task,
            requested_capability=task.requires_capability,
            requested_scope=task.scope,
            reason="Delegation task scope exceeded capability scope.",
            current_limit_hit="scope_violation",
        )
    if not task.scope.get("domain"):
        return _build_escalation(
            task,
            requested_capability=task.requires_capability,
            requested_scope=task.scope,
            reason="Delegation task scope requires a domain boundary.",
            current_limit_hit="scope_missing_domain",
        )
    if len(task.allowed_operations) > limits.max_operations:
        return _build_escalation(
            task,
            requested_capability=task.requires_capability,
            requested_scope=task.scope,
            reason=f"Delegation task exceeded max_operations={limits.max_operations}.",
            current_limit_hit="scope_max_operations",
        )
    ref_validation = _validate_input_refs(task, limits=limits)
    if not ref_validation.allowed:
        return _build_escalation(
            task,
            requested_capability=task.requires_capability,
            requested_scope=task.scope,
            reason=ref_validation.detail,
            current_limit_hit=ref_validation.reason_code,
        )
    network_validation = _validate_network_posture(task)
    if not network_validation.allowed:
        return _build_escalation(
            task,
            requested_capability=task.requires_capability,
            requested_scope=task.scope,
            reason=network_validation.detail,
            current_limit_hit=network_validation.reason_code,
        )
    return None


def _check_timeout(started_at: float, timeout_ms: int, task: DelegationTask) -> EscalationRequest | None:
    elapsed_ms = (time.monotonic() - started_at) * 1000
    if elapsed_ms > timeout_ms:
        return _build_escalation(
            task,
            requested_capability=task.requires_capability,
            requested_scope=task.scope,
            reason=f"Worker exceeded timeout budget of {timeout_ms}ms.",
            current_limit_hit="timeout",
        )
    return None


def _artifact_size_bytes(artifacts: dict) -> int:
    return len(json.dumps(artifacts, ensure_ascii=False).encode("utf-8"))


def _perform_operations(task: DelegationTask, *, started_at: float, timeout_ms: int, limits: WorkerExecutionLimits) -> tuple[list[str], dict, EscalationRequest | None]:
    artifacts: dict = {}
    operations_performed: list[str] = []

    for operation in task.allowed_operations:
        timeout_hit = _check_timeout(started_at, timeout_ms, task)
        if timeout_hit is not None:
            return operations_performed, artifacts, timeout_hit
        operations_performed.append(operation)
        if operation == "read_system_state":
            snapshot = build_system_state_snapshot()
            artifacts["system_state"] = {
                "operational_mode": snapshot.operational_mode,
                "active_tasks": len(snapshot.active_tasks),
                "pending_tasks": len(snapshot.pending_tasks),
                "blocked_tasks": len(snapshot.blocked_tasks),
                "recent_anomalies": len(snapshot.recent_anomaly_signals),
            }
        elif operation == "summarize_context":
            artifacts["summary"] = f"Task goal: {task.task_goal}. Input refs: {', '.join(task.input_refs) or 'none'}."
        elif operation == "classify_issue":
            goal = task.task_goal.lower()
            if "failure" in goal or "error" in goal:
                artifacts["issue_classification"] = "failure_analysis"
            elif "consistency" in goal:
                artifacts["issue_classification"] = "consistency_review"
            else:
                artifacts["issue_classification"] = "general_diagnostic"
        elif operation == "consistency_check":
            required_keys = task.expected_output_schema.get("required_artifact_keys") or []
            artifacts["consistency_check"] = {
                "required_keys": required_keys,
                "present_keys": sorted(list(artifacts.keys())),
            }
        elif operation == "simulate":
            delay_ms = int(task.scope.get("simulate_delay_ms", 0))
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
            artifacts["simulation"] = {
                "mode": "dry_run",
                "scope": dict(task.scope),
                "task_goal": task.task_goal,
            }
        if len(artifacts) > limits.max_artifact_count:
            return operations_performed, artifacts, _build_escalation(
                task,
                requested_capability=task.requires_capability,
                requested_scope=task.scope,
                reason=f"Worker exceeded max_artifact_count={limits.max_artifact_count}.",
                current_limit_hit="max_artifact_count_exceeded",
            )
        if _artifact_size_bytes(artifacts) > limits.max_artifact_bytes:
            return operations_performed, artifacts, _build_escalation(
                task,
                requested_capability=task.requires_capability,
                requested_scope=task.scope,
                reason=f"Worker exceeded max_artifact_bytes={limits.max_artifact_bytes}.",
                current_limit_hit="max_artifact_bytes_exceeded",
            )
        timeout_hit = _check_timeout(started_at, timeout_ms, task)
        if timeout_hit is not None:
            return operations_performed, artifacts, timeout_hit

    return operations_performed, artifacts, None


def execute_delegation_task(task: DelegationTask, capability: ExecutionCapability) -> tuple[ExecutionReport, EscalationRequest | None]:
    """Execute a bounded delegation task and return only report/escalation contracts."""
    started_at = time.monotonic()
    limits = _limits_for_task(task)
    escalation = _validate_task_scope(task, capability)
    if escalation is not None:
        report = ExecutionReport(
            report_id=str(uuid.uuid4()),
            task_id=task.task_id,
            worker_id=WORKER_ID,
            status="blocked",
            operations_performed=[],
            artifacts={},
            findings_summary="Worker halted because the issued capability did not cover the task scope.",
            confidence=0.0,
            requires_escalation=True,
            trace_id=task.trace_id,
            completed_at=now_iso(),
        )
        return report, escalation

    operations_performed, artifacts, timeout_or_scope = _perform_operations(
        task,
        started_at=started_at,
        timeout_ms=limits.timeout_ms,
        limits=limits,
    )
    if timeout_or_scope is not None and timeout_or_scope.current_limit_hit == "timeout":
        report = ExecutionReport(
            report_id=str(uuid.uuid4()),
            task_id=task.task_id,
            worker_id=WORKER_ID,
            status="timeout",
            operations_performed=operations_performed,
            artifacts=artifacts,
            findings_summary="Worker exceeded its bounded execution timeout.",
            confidence=0.0,
            requires_escalation=True,
            trace_id=task.trace_id,
            completed_at=now_iso(),
        )
        return report, timeout_or_scope
    if timeout_or_scope is not None:
        report = ExecutionReport(
            report_id=str(uuid.uuid4()),
            task_id=task.task_id,
            worker_id=WORKER_ID,
            status="blocked",
            operations_performed=operations_performed,
            artifacts=artifacts,
            findings_summary="Worker halted after hitting a bounded execution limit.",
            confidence=0.0,
            requires_escalation=True,
            trace_id=task.trace_id,
            completed_at=now_iso(),
        )
        return report, timeout_or_scope

    required_keys = task.expected_output_schema.get("required_artifact_keys") or []
    missing = [item for item in required_keys if item not in artifacts]
    escalation = None
    status = "completed"
    findings_summary = f"Worker completed {len(operations_performed)} bounded cognitive operation(s)."
    confidence = 0.82 if operations_performed else 0.5
    if missing:
        escalation = _build_escalation(
            task,
            requested_capability=task.requires_capability,
            requested_scope=task.scope,
            reason=f"Expected output schema requires missing artifacts: {missing}",
            current_limit_hit="expected_output_schema",
        )
        status = "needs_escalation"
        findings_summary = "Worker reached output-schema limits and requires escalation."
        confidence = 0.4

    report = ExecutionReport(
        report_id=str(uuid.uuid4()),
        task_id=task.task_id,
        worker_id=WORKER_ID,
        status=status,
        operations_performed=operations_performed,
        artifacts=artifacts,
        findings_summary=findings_summary,
        confidence=confidence,
        requires_escalation=escalation is not None,
        trace_id=task.trace_id,
        completed_at=now_iso(),
    )
    return report, escalation
