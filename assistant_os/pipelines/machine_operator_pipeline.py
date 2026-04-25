"""
MACHINE_OPERATOR Domain Pipeline v0

Entry point: execute(plan, context_id) -> DomainResult

This pipeline establishes the canonical MACHINE_OPERATOR lane without leaking
backend transport or browser protocol details into sovereign-facing contracts.
The adapter translates; the MSO decides; OpenClaw executes; nobody crosses lanes.

Current scope:
- validate the canonical structured lane request
- enforce the fail-closed MACHINE_OPERATOR policy registry
- invoke the adapter boundary after contract and policy approval
- translate the adapter result into a canonical DomainResult

This pipeline does NOT:
- implement backend transport details
- allow cross-lane fallback
- bypass policy or contract validation
- claim that a real machine action occurred when execution failed
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from ..contracts import (
    ACTION_MACHINE_OPERATOR_EXECUTE,
    DomainResult,
    EXECUTION_STATUS_PARTIAL,
    EXECUTION_STATUS_REAL,
    EXECUTION_STATUS_UNAVAILABLE,
    RESULT_TYPE_MACHINE_OPERATOR_ACTION,
    make_domain_result,
)
from ..mso.machine_operator_adapter import (
    DEFAULT_MACHINE_OPERATOR_ADAPTER,
    MachineOperatorAdapter,
    MachineOperatorAdapterContext,
    MachineOperatorAdapterResult,
)
from ..mso.contracts import (
    MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE,
    MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED,
    MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED,
    MACHINE_OPERATOR_OUTCOME_EXECUTION_PARTIAL,
    MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST,
    MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION,
    MACHINE_OPERATOR_OUTCOME_SUCCESS,
    MACHINE_OPERATOR_STATE_REQUESTED,
    MachineOperatorBudgetUsage,
    MachineOperatorIntentResponse,
    MachineOperatorObservation,
    MachineOperatorWorkflowResponse,
    is_machine_operator_transition_allowed,
    machine_operator_request_capabilities,
    machine_operator_request_capability_name,
    machine_operator_request_capability_tier,
    machine_operator_request_kind,
    machine_operator_request_step_count,
    validate_machine_operator_response,
)
from ..mso.machine_operator_policy import enforce_machine_operator_request


def execute(plan: dict, context_id: str) -> DomainResult:
    """Execute a MACHINE_OPERATOR domain plan and return a canonical lane result."""
    try:
        result = _dispatch(plan, context_id)
        lane_outcome = result.get("data", {}).get("lane_outcome", "")
        if lane_outcome == MACHINE_OPERATOR_OUTCOME_SUCCESS:
            result["execution_status"] = EXECUTION_STATUS_REAL
        elif lane_outcome == MACHINE_OPERATOR_OUTCOME_EXECUTION_PARTIAL:
            result["execution_status"] = EXECUTION_STATUS_PARTIAL
        else:
            result["execution_status"] = EXECUTION_STATUS_UNAVAILABLE
        return result
    except Exception as exc:  # pragma: no cover - defensive boundary
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
            domain="MACHINE_OPERATOR",
            message="Unexpected error in MACHINE_OPERATOR pipeline",
            data={"plan": dict(plan)},
            error={"type": "MachineOperatorPipelineError", "message": str(exc)},
            execution_status=EXECUTION_STATUS_UNAVAILABLE,
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )


def _dispatch(plan: dict, context_id: str) -> DomainResult:
    action = plan.get("action", "")
    if action != ACTION_MACHINE_OPERATOR_EXECUTE:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
            domain="MACHINE_OPERATOR",
            message=f"Unknown MACHINE_OPERATOR action: {action!r}",
            data={"plan_action": action},
            error={
                "type": "UnknownMachineOperatorAction",
                "message": f"No handler for MACHINE_OPERATOR action: {action!r}",
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    payload = plan.get("domain_payload")
    if not isinstance(payload, dict):
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
            domain="MACHINE_OPERATOR",
            message="domain_payload is missing or not a dict",
            data={"plan_action": action},
            error={
                "type": "InvalidMachineOperatorPayload",
                "message": "domain_payload must be a dict",
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    if "machine_operator_request" not in payload:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
            domain="MACHINE_OPERATOR",
            message="machine_operator_request is missing",
            data={"plan_action": action},
            error={
                "type": "InvalidMachineOperatorPayload",
                "message": "domain_payload must include machine_operator_request",
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    request_payload = payload.get("machine_operator_request")
    decision = enforce_machine_operator_request(request_payload)
    request = _coerce_to_dict(request_payload)
    execution_id = plan.get("plan_id") or context_id

    if not decision.allowed and decision.reason_code == "invalid_request":
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
            domain="MACHINE_OPERATOR",
            message="MACHINE_OPERATOR request rejected by contract validation",
            data={
                "type": RESULT_TYPE_MACHINE_OPERATOR_ACTION,
                "action": action,
                "lane": "MACHINE_OPERATOR",
                "lane_outcome": MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST,
                "execution_id": execution_id,
                "contract_validation": {
                    "ok": False,
                    "reason_code": "invalid_request",
                    "message": decision.message,
                },
                "policy_validation": None,
                "backend_status": "not_executed",
                "backend_execution_attempted": False,
                "backend_execution_performed": False,
                "machine_action_performed": False,
                "adapter_status": "not_executed",
            },
            error={
                "type": "InvalidMachineOperatorRequest",
                "message": decision.message,
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    if not decision.allowed:
        is_workflow_request = machine_operator_request_kind(request) == "workflow"
        response = _build_stub_response(
            request=request,
            status="aborted" if is_workflow_request else "denied",
            summary=(
                "MACHINE_OPERATOR workflow aborted by policy before execution."
                if is_workflow_request
                else "MACHINE_OPERATOR request denied by policy."
            ),
            detail=decision.message,
            lane_outcome=MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION,
        )
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
            domain="MACHINE_OPERATOR",
            message="MACHINE_OPERATOR request rejected by contract or policy",
            data=_build_domain_data(
                action=action,
                execution_id=execution_id,
                request=request,
                decision=decision,
                response=response,
                lane_outcome=MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION,
            ),
            error={
                "type": "MachineOperatorPolicyViolation",
                "message": decision.message,
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    adapter = _get_machine_operator_adapter()
    adapter_result = adapter.execute(
        request,
        _build_adapter_context(
            plan=plan,
            execution_id=execution_id,
            request=request,
            decision=decision,
        ),
    )
    response = _build_response_from_adapter_result(
        request=request,
        adapter_result=adapter_result,
    )
    domain_data = _build_domain_data(
        action=action,
        execution_id=execution_id,
        request=request,
        decision=decision,
        response=response,
        lane_outcome=adapter_result.metadata["lane_outcome"],
        adapter_metadata=adapter_result.metadata,
    )
    if _adapter_result_is_success(adapter_result):
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
            domain="MACHINE_OPERATOR",
            message="MACHINE_OPERATOR execution completed",
            data=domain_data,
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )
    return make_domain_result(
        ok=False,
        result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
        domain="MACHINE_OPERATOR",
        message=_adapter_failure_message(adapter_result),
        data=domain_data,
        error={
            "type": _adapter_failure_type(adapter_result),
            "message": _adapter_failure_message(adapter_result),
        },
        trace_id=plan.get("trace_id"),
        plan_id=plan.get("plan_id"),
    )


def _build_stub_response(
    *,
    request: dict[str, Any],
    status: str,
    summary: str,
    detail: str,
    lane_outcome: str,
) -> MachineOperatorIntentResponse | MachineOperatorWorkflowResponse:
    response_kwargs = dict(
        intent_id=request["intent_id"],
        correlation_id=request["correlation_id"],
        status=status,
        observation=MachineOperatorObservation(
            summary=summary,
            detail=detail,
            structured_data={
                "lane_outcome": lane_outcome,
                "backend_status": "not_implemented",
                "backend_execution_performed": False,
                "machine_action_performed": False,
            },
        ),
        evidence_refs=[],
        consumed_budget=MachineOperatorBudgetUsage(
            steps=0,
            duration_ms=0,
            output_bytes=0,
            side_effects=0,
        ),
        side_effects_declared=[],
        audit_event_ids=[],
    )
    if machine_operator_request_kind(request) == "workflow":
        response = MachineOperatorWorkflowResponse(
            **response_kwargs,
            step_results=[],
        )
    else:
        response = MachineOperatorIntentResponse(**response_kwargs)
    ok, error = validate_machine_operator_response(response)
    if not ok:
        raise ValueError(f"Invalid MachineOperatorIntentResponse stub: {error}")
    return response


def _build_response_from_adapter_result(
    *,
    request: dict[str, Any],
    adapter_result: MachineOperatorAdapterResult,
) -> MachineOperatorIntentResponse | MachineOperatorWorkflowResponse:
    response_kwargs = dict(
        intent_id=request["intent_id"],
        correlation_id=request["correlation_id"],
        status=adapter_result.status,
        observation=adapter_result.observation,
        evidence_refs=adapter_result.evidence_refs,
        consumed_budget=adapter_result.consumed_budget,
        side_effects_declared=adapter_result.side_effects_declared,
        audit_event_ids=list(adapter_result.audit_event_ids),
    )
    if machine_operator_request_kind(request) == "workflow":
        response = MachineOperatorWorkflowResponse(
            **response_kwargs,
            step_results=list(adapter_result.metadata.get("step_results", [])),
        )
    else:
        response = MachineOperatorIntentResponse(**response_kwargs)
    ok, error = validate_machine_operator_response(response)
    if not ok:
        raise ValueError(f"Invalid MachineOperatorIntentResponse from adapter: {error}")
    return response


def _build_adapter_context(
    *,
    plan: dict[str, Any],
    execution_id: str,
    request: dict[str, Any],
    decision,
) -> MachineOperatorAdapterContext:
    return MachineOperatorAdapterContext(
        plan_id=plan.get("plan_id", ""),
        execution_id=execution_id,
        trace_id=plan.get("trace_id", ""),
        policy_decision_ref=request["policy_context"]["policy_decision_ref"],
        capability_name=machine_operator_request_capability_name(request),
        capability_tier=machine_operator_request_capability_tier(request),
        policy_reason_code=decision.reason_code,
        policy_message=decision.message,
    )


def _build_domain_data(
    *,
    action: str,
    execution_id: str,
    request: dict[str, Any],
    decision,
    response: MachineOperatorIntentResponse | MachineOperatorWorkflowResponse,
    lane_outcome: str,
    adapter_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not is_machine_operator_transition_allowed(MACHINE_OPERATOR_STATE_REQUESTED, lane_outcome):
        raise ValueError(f"Unsupported MACHINE_OPERATOR lane_outcome: {lane_outcome}")
    metadata = adapter_metadata or {
        "backend_status": "not_executed",
        "backend_execution_attempted": False,
        "backend_execution_performed": False,
        "machine_action_performed": False,
        "adapter_status": "not_executed",
        "backend_latency_ms": 0,
        "backend_state": "",
        "backend_error_type": "",
        "circuit_state": "closed",
    }
    request_kind = machine_operator_request_kind(request)
    capability_name = machine_operator_request_capability_name(request)
    capability_tier = machine_operator_request_capability_tier(request)
    domain_data = {
        "type": RESULT_TYPE_MACHINE_OPERATOR_ACTION,
        "action": action,
        "lane": "MACHINE_OPERATOR",
        "lane_outcome": lane_outcome,
        "execution_id": execution_id,
        "intent_id": request["intent_id"],
        "correlation_id": request["correlation_id"],
        "capability_name": capability_name,
        "capability_tier": capability_tier,
        "contract_validation": {
            "ok": True,
            "reason_code": "valid_request",
            "message": "MACHINE_OPERATOR request satisfies contract validation.",
        },
        "policy_validation": {
            "ok": decision.allowed,
            "reason_code": decision.reason_code,
            "message": decision.message,
        },
        "policy": {
            "policy_level": decision.policy.policy_level,
            "approval_mode": decision.policy.approval_mode,
            "requires_allowlist": decision.policy.requires_allowlist,
            "allows_side_effects": decision.policy.allows_side_effects,
            "requires_secrets": decision.policy.requires_secrets,
            "allowed_by_default": decision.policy.allowed_by_default,
        },
        "backend_status": metadata["backend_status"],
        "backend_execution_attempted": metadata["backend_execution_attempted"],
        "backend_execution_performed": metadata["backend_execution_performed"],
        "machine_action_performed": metadata["machine_action_performed"],
        "adapter_status": metadata["adapter_status"],
        "backend_latency_ms": metadata.get("backend_latency_ms", 0),
        "backend_state": metadata.get("backend_state", ""),
        "backend_error_type": metadata.get("backend_error_type", ""),
        "circuit_state": metadata.get("circuit_state", "closed"),
        "session_mode": metadata.get("session_mode", ""),
        "session_reused": metadata.get("session_reused", False),
        "session_persisted": metadata.get("session_persisted", False),
        "session_retained_after_terminal": metadata.get("session_retained_after_terminal", False),
        "cleanup_semantics": metadata.get("cleanup_semantics", ""),
        "machine_operator_response": asdict(response),
        "request_kind": request_kind,
    }
    if request_kind == "workflow":
        domain_data.update(
            {
                "workflow_step_count": machine_operator_request_step_count(request),
                "workflow_capabilities": machine_operator_request_capabilities(request),
                "step_results": list(metadata.get("step_results", [])),
            }
        )
    return domain_data


def _get_machine_operator_adapter() -> MachineOperatorAdapter:
    return DEFAULT_MACHINE_OPERATOR_ADAPTER


def _adapter_result_is_success(adapter_result: MachineOperatorAdapterResult) -> bool:
    return (
        adapter_result.status == "ok"
        and adapter_result.metadata.get("lane_outcome") == MACHINE_OPERATOR_OUTCOME_SUCCESS
        and bool(adapter_result.metadata.get("backend_execution_performed"))
    )


def _adapter_failure_message(adapter_result: MachineOperatorAdapterResult) -> str:
    if adapter_result.status == "partial":
        prefix = "MACHINE_OPERATOR execution partially completed."
        detail = adapter_result.observation.summary.strip()
        if detail:
            return f"{prefix} {detail}".strip()
        return prefix
    if adapter_result.status == "aborted":
        summary = adapter_result.observation.summary.strip()
        detail = adapter_result.observation.detail.strip()
        if detail:
            return f"{summary} {detail}".strip()
        return summary or "MACHINE_OPERATOR execution aborted."
    summary = adapter_result.observation.summary.strip()
    detail = adapter_result.observation.detail.strip()
    if detail:
        return f"{summary} {detail}".strip()
    return summary or "MACHINE_OPERATOR execution failed."


def _adapter_failure_type(adapter_result: MachineOperatorAdapterResult) -> str:
    lane_outcome = str(adapter_result.metadata.get("lane_outcome", ""))
    if adapter_result.status == "partial":
        return "MachineOperatorExecutionPartial"
    if lane_outcome == MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE:
        return "MachineOperatorBackendUnavailable"
    if lane_outcome == MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST:
        return "InvalidMachineOperatorRequest"
    if lane_outcome == MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION:
        return "MachineOperatorPolicyViolation"
    if adapter_result.status == "aborted" or lane_outcome == MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED:
        return "MachineOperatorExecutionAborted"
    return "MachineOperatorExecutionFailed"


def _coerce_to_dict(payload: Any) -> dict[str, Any]:
    if is_dataclass(payload):
        return asdict(payload)
    if isinstance(payload, dict):
        return dict(payload)
    return {}
