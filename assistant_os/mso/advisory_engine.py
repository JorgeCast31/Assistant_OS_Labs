"""Structured advisory layer on top of the local LLM adapter."""

from __future__ import annotations

from typing import Any

from .contracts import (
    AdvisoryDecisionTrace,
    AdvisorySummary,
    CodePackagingHint,
    LocalLlmRequest,
    OrchestratorAdvisory,
    RoutingHint,
)
from .local_llm_adapter import consult_advisory


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif value:
        raw = [value]
    else:
        raw = []
    return [str(item).strip() for item in raw if str(item).strip()]


def _build_summary(raw: dict[str, Any]) -> AdvisorySummary:
    text = str(raw.get("reasoning_summary", "")).strip()
    confidence_note = str(raw.get("confidence_note", "")).strip()
    summary: AdvisorySummary = {}
    if text:
        summary["text"] = text
    if confidence_note:
        summary["confidence_note"] = confidence_note
    return summary


def _build_routing_hint(raw: dict[str, Any]) -> RoutingHint:
    routing_hint: RoutingHint = {}
    if str(raw.get("routing_hint", "")).strip():
        routing_hint["summary"] = str(raw.get("routing_hint", "")).strip()
    if str(raw.get("suggested_domain", "")).strip():
        routing_hint["suggested_domain"] = str(raw.get("suggested_domain", "")).strip()
    if str(raw.get("suggested_action", "")).strip():
        routing_hint["suggested_action"] = str(raw.get("suggested_action", "")).strip()
    if str(raw.get("execution_posture_hint", "")).strip():
        routing_hint["execution_posture_hint"] = str(raw.get("execution_posture_hint", "")).strip()
    if str(raw.get("confidence_note", "")).strip():
        routing_hint["confidence_note"] = str(raw.get("confidence_note", "")).strip()
    return routing_hint


def _build_code_package(raw: dict[str, Any], planned_action: str) -> CodePackagingHint:
    if not planned_action.startswith("CODE_"):
        return {}

    code_package: CodePackagingHint = {}
    if str(raw.get("code_task_summary", "")).strip():
        code_package["task_summary"] = str(raw.get("code_task_summary", "")).strip()
    if str(raw.get("repo_context", "")).strip():
        code_package["repo_context"] = str(raw.get("repo_context", "")).strip()
    constraints = _clean_list(raw.get("constraints"))
    if constraints:
        code_package["constraints"] = constraints
    if str(raw.get("expected_artifact", "")).strip():
        code_package["expected_artifact"] = str(raw.get("expected_artifact", "")).strip()
    risk_notes = _clean_list(raw.get("risk_notes"))
    if risk_notes:
        code_package["risk_notes"] = risk_notes
    return code_package


def consult_orchestrator_advisory(
    *,
    text: str,
    intent: dict,
    plan: dict,
) -> OrchestratorAdvisory:
    """Consult the local advisory model and normalize the result for orchestrator use."""
    request: LocalLlmRequest = {
        "task": "orchestrator_advisory_bundle",
        "advisory_role": "orchestrator",
        "text": text,
        "classifier_operation": intent.get("operation", ""),
        "classifier_domain": intent.get("domain", ""),
        "planned_action": plan.get("action", ""),
        "plan_preview": plan.get("preview", ""),
        "metadata": dict(plan.get("domain_payload") or {}),
    }
    response = consult_advisory(request)
    result: OrchestratorAdvisory = {
        "consulted_roles": [],
        "status": response.get("status", "error"),
        "provider": response.get("provider", ""),
        "model": response.get("model", ""),
        "latency_ms": response.get("latency_ms", 0),
        "error": response.get("error"),
    }
    if response.get("status") != "ok":
        return result

    raw = dict(response.get("advisory") or {})
    summary = _build_summary(raw)
    routing_hint = _build_routing_hint(raw)
    code_package = _build_code_package(raw, plan.get("action", ""))

    consulted_roles: list[str] = []
    if summary:
        consulted_roles.append("reasoning_summary")
        result["summary"] = summary
    if routing_hint:
        consulted_roles.append("routing_hint")
        result["routing_hint"] = routing_hint
    if code_package:
        consulted_roles.append("code_packaging")
        result["code_package"] = code_package

    result["consulted_roles"] = consulted_roles
    result["raw_advisory"] = raw
    if not consulted_roles:
        result["status"] = "ignored"
        result["error"] = "Local advisory returned no usable structured fields"
    return result


def build_advisory_trace(
    advisory: OrchestratorAdvisory | None,
    *,
    final_domain: str,
    final_action: str,
    final_execution_mode: str,
) -> AdvisoryDecisionTrace:
    """Build an inspectable advisory-vs-decision trace."""
    advisory = advisory or {}
    routing_hint = dict(advisory.get("routing_hint") or {})
    summary = dict(advisory.get("summary") or {})
    trace: AdvisoryDecisionTrace = {
        "consulted": bool(advisory),
        "consulted_roles": list(advisory.get("consulted_roles") or []),
        "status": advisory.get("status", "disabled" if not advisory else ""),
        "provider": advisory.get("provider", ""),
        "model": advisory.get("model", ""),
        "latency_ms": advisory.get("latency_ms", 0),
        "final_domain": final_domain,
        "final_action": final_action,
        "final_execution_mode": final_execution_mode,
        "routing_hint_action": routing_hint.get("suggested_action", ""),
        "routing_hint_domain": routing_hint.get("suggested_domain", ""),
        "reasoning_summary": summary.get("text", ""),
        "code_packaged": bool(advisory.get("code_package")),
        "error": advisory.get("error"),
    }
    return trace
