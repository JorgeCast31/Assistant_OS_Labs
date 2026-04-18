"""
MACHINE_OPERATOR Domain Pipeline v0

Entry point: execute(plan, context_id) -> DomainResult

This pipeline establishes the canonical MACHINE_OPERATOR lane without binding
the system to any backend transport or browser automation implementation.
The adapter translates; the MSO decides; OpenClaw executes; nobody crosses lanes.

Current scope:
- validate the canonical structured lane request
- enforce the fail-closed MACHINE_OPERATOR policy registry
- produce a typed stub MachineOperatorIntentResponse
- translate that stub response into a canonical DomainResult

This pipeline does NOT:
- execute OpenClaw
- call any gateway
- drive a browser
- claim that a real machine action occurred
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from ..contracts import (
    ACTION_MACHINE_OPERATOR_EXECUTE,
    DomainResult,
    RESULT_TYPE_MACHINE_OPERATOR_ACTION,
    make_domain_result,
)
from ..mso.contracts import (
    MachineOperatorBudgetUsage,
    MachineOperatorIntentResponse,
    MachineOperatorObservation,
    validate_machine_operator_response,
)
from ..mso.machine_operator_policy import enforce_machine_operator_request


def execute(plan: dict, context_id: str) -> DomainResult:
    """Execute a MACHINE_OPERATOR domain plan and return a canonical stub result."""
    try:
        return _dispatch(plan, context_id)
    except Exception as exc:  # pragma: no cover - defensive boundary
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
            domain="MACHINE_OPERATOR",
            message="Unexpected error in MACHINE_OPERATOR pipeline",
            data={"plan": dict(plan)},
            error={"type": "MachineOperatorPipelineError", "message": str(exc)},
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
                "lane_outcome": "invalid_request",
                "execution_id": execution_id,
                "contract_validation": {
                    "ok": False,
                    "reason_code": "invalid_request",
                    "message": decision.message,
                },
                "policy_validation": None,
                "backend_status": "not_implemented",
                "backend_execution_performed": False,
                "machine_action_performed": False,
            },
            error={
                "type": "InvalidMachineOperatorRequest",
                "message": decision.message,
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    if not decision.allowed:
        response = _build_stub_response(
            request=request,
            status="denied",
            summary="MACHINE_OPERATOR request denied by policy.",
            detail=decision.message,
            lane_outcome="rejected_by_policy",
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
                lane_outcome="rejected_by_policy",
            ),
            error={
                "type": "MachineOperatorPolicyViolation",
                "message": decision.message,
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    response = _build_stub_response(
        request=request,
        status="aborted",
        summary="MACHINE_OPERATOR lane accepted; backend not implemented.",
        detail="No real machine or browser action was performed.",
        lane_outcome="accepted_not_executed",
    )
    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
        domain="MACHINE_OPERATOR",
        message="MACHINE_OPERATOR lane accepted; backend execution is not implemented",
        data=_build_domain_data(
            action=action,
            execution_id=execution_id,
            request=request,
            decision=decision,
            response=response,
            lane_outcome="accepted_not_executed",
        ),
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
) -> MachineOperatorIntentResponse:
    response = MachineOperatorIntentResponse(
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
    ok, error = validate_machine_operator_response(response)
    if not ok:
        raise ValueError(f"Invalid MachineOperatorIntentResponse stub: {error}")
    return response


def _build_domain_data(
    *,
    action: str,
    execution_id: str,
    request: dict[str, Any],
    decision,
    response: MachineOperatorIntentResponse,
    lane_outcome: str,
) -> dict[str, Any]:
    return {
        "type": RESULT_TYPE_MACHINE_OPERATOR_ACTION,
        "action": action,
        "lane": "MACHINE_OPERATOR",
        "lane_outcome": lane_outcome,
        "execution_id": execution_id,
        "intent_id": request["intent_id"],
        "correlation_id": request["correlation_id"],
        "capability_name": request["capability_name"],
        "capability_tier": request["capability_tier"],
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
        "backend_status": "not_implemented",
        "backend_execution_performed": False,
        "machine_action_performed": False,
        "machine_operator_response": asdict(response),
    }


def _coerce_to_dict(payload: Any) -> dict[str, Any]:
    if is_dataclass(payload):
        return asdict(payload)
    if isinstance(payload, dict):
        return dict(payload)
    return {}
