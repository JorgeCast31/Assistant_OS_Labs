"""MSO runtime loop for sovereign intent production and deterministic translation."""

from __future__ import annotations

from dataclasses import asdict
import uuid

from ..contracts import DomainResult, new_context_id
from ..core.orchestrator import handle_request
from ..storage.mso_store import (
    persist_cycle_record,
    persist_delegation_task,
    persist_escalation_request,
    persist_execution_capability,
    persist_execution_report,
    persist_intent,
    persist_translator_rejection,
)
from .contracts import DelegationTask, SovereignCycleRecord, SovereignIntent
from .system_state import build_system_state_snapshot
from .trace_aggregator import attach_persistence_refs, attach_sovereign_cycle
from .translator import TranslatorValidationError, translate_intent_to_canonical_request


def _should_delegate_cognitive(text: str) -> bool:
    lowered = text.lower()
    keywords = ("diagnostic", "state", "summary", "anomaly", "consistency", "simulate", "worker")
    return any(keyword in lowered for keyword in keywords)


def build_sovereign_intent(
    *,
    session_id: str,
    user_request_ref: str,
    text: str,
) -> SovereignIntent:
    """Produce a deterministic sovereign intent from user input and current system state."""
    snapshot = build_system_state_snapshot()
    delegation = "delegate_basic_cognitive_execution" if _should_delegate_cognitive(text) else "none"
    interpreted_goal = text.strip() or "Inspect current request."
    return SovereignIntent(
        intent_id=str(uuid.uuid4()),
        session_id=session_id,
        user_request_ref=user_request_ref,
        interpreted_goal=interpreted_goal,
        priority="high" if snapshot.operational_mode == "DEGRADED" else "normal",
        persistence_recommendation="persist_cognitive_artifacts" if delegation != "none" else "persist_trace_only",
        risk_posture_hint=snapshot.operational_mode.lower(),
        delegation_recommendation=delegation,
        justification_summary=f"Operational mode is {snapshot.operational_mode}; sovereign classified the request deterministically.",
        timestamp=snapshot.generated_at,
    )


def _build_delegation_task(intent: SovereignIntent, *, text: str) -> DelegationTask | None:
    if intent.delegation_recommendation != "delegate_basic_cognitive_execution":
        return None

    lowered = text.lower()
    allowed_operations = ["read_system_state"]
    required_artifacts = ["system_state"]
    if "summary" in lowered or "summar" in lowered:
        allowed_operations.append("summarize_context")
        required_artifacts.append("summary")
    if "consistency" in lowered:
        allowed_operations.append("consistency_check")
        required_artifacts.append("consistency_check")
    if "simulate" in lowered:
        allowed_operations.append("simulate")
        required_artifacts.append("simulation")
    if "error" in lowered or "failure" in lowered or "issue" in lowered:
        allowed_operations.append("classify_issue")
        required_artifacts.append("issue_classification")
    allowed_operations = list(dict.fromkeys(allowed_operations))
    required_artifacts = list(dict.fromkeys(required_artifacts))

    return DelegationTask(
        task_id=str(uuid.uuid4()),
        origin_intent_id=intent.intent_id,
        task_type="BASIC_COGNITIVE_EXECUTION",
        task_goal=intent.interpreted_goal,
        allowed_operations=allowed_operations,
        input_refs=[intent.user_request_ref, "state:current"],
        scope={
            "domain": "COGNITIVE",
            "max_items": 10,
            "max_operations": len(allowed_operations),
            "timeout_ms": 250,
        },
        requires_capability="BASIC_COGNITIVE_EXECUTION",
        expected_output_schema={"required_artifact_keys": required_artifacts},
        expiry="2099-01-01T00:00:00+00:00",
        trace_id=f"trace:{intent.intent_id}",
    )


def _build_cycle(
    *,
    cycle_id: str,
    intent: SovereignIntent,
    decision_type: str,
    canonical_request: dict | None,
    delegation_task: DelegationTask | None,
    result: DomainResult | None,
    translator_status: str,
    translator_rejection_ref: str = "",
    persistence_refs: dict[str, str] | None = None,
    notes: str = "",
) -> SovereignCycleRecord:
    metadata = canonical_request.get("metadata", {}) if canonical_request else {}
    return SovereignCycleRecord(
        cycle_id=cycle_id,
        session_id=intent.session_id,
        intent_id=intent.intent_id,
        user_request_ref=intent.user_request_ref,
        decision_type=decision_type,
        created_at=intent.timestamp,
        interpreted_goal=intent.interpreted_goal,
        translator_status=translator_status,
        canonical_context_id=(canonical_request or {}).get("context_id", ""),
        canonical_action=metadata.get("action", ""),
        canonical_domain=metadata.get("domain", ""),
        plan_id=(result or {}).get("plan_id", ""),
        trace_id=(result or {}).get("trace_id", "") or (delegation_task.trace_id if delegation_task else ""),
        delegation_task_id=delegation_task.task_id if delegation_task else "",
        translator_rejection_ref=translator_rejection_ref,
        persistence_recommendation=intent.persistence_recommendation,
        notes=notes,
        persistence_refs=dict(persistence_refs or {}),
    )


def run_mso_cycle(
    *,
    text: str,
    session_id: str = "",
    user_request_ref: str = "",
    context_id: str = "",
) -> dict:
    """Run one sovereign runtime cycle and return the resulting deterministic execution bundle."""
    cycle_id = str(uuid.uuid4())
    resolved_session_id = session_id or new_context_id()
    resolved_request_ref = user_request_ref or f"request:{resolved_session_id}"
    intent = build_sovereign_intent(
        session_id=resolved_session_id,
        user_request_ref=resolved_request_ref,
        text=text,
    )
    intent_path = persist_intent(intent)

    delegation_task = _build_delegation_task(intent, text=text)
    delegation_path = persist_delegation_task(delegation_task) if delegation_task is not None else ""
    try:
        request = translate_intent_to_canonical_request(
            intent,
            original_text=text,
            context_id=context_id or resolved_session_id,
            delegation_task=delegation_task,
        )
    except TranslatorValidationError as exc:
        rejection_path = persist_translator_rejection(exc.rejection)
        cycle = _build_cycle(
            cycle_id=cycle_id,
            intent=intent,
            decision_type="persist_only",
            canonical_request=None,
            delegation_task=delegation_task,
            result=None,
            translator_status="rejected",
            translator_rejection_ref=rejection_path,
            persistence_refs={
                "intent": intent_path,
                "delegation": delegation_path,
                "translator_rejection": rejection_path,
            },
            notes=exc.rejection.message,
        )
        cycle_path = persist_cycle_record(cycle)
        cycle.persistence_refs["cycle"] = cycle_path
        persist_cycle_record(cycle)
        return {
            "cycle": asdict(cycle),
            "sovereign_intent": asdict(intent),
            "delegation_task": asdict(delegation_task) if delegation_task else None,
            "canonical_request": None,
            "translator_rejection": asdict(exc.rejection),
            "result": None,
            "persistence_refs": {
                "intent": intent_path,
                "delegation": delegation_path,
                "translator_rejection": rejection_path,
                "cycle": cycle_path,
            },
        }

    result: DomainResult = handle_request(request)

    persistence_refs = {"intent": intent_path}
    if delegation_path:
        persistence_refs["delegation"] = delegation_path
    result_data = result.get("data") or {}
    if result_data.get("execution_capability"):
        capability_path = persist_execution_capability(result_data["execution_capability"])
        persistence_refs["capability"] = capability_path
    if result_data.get("execution_report"):
        report_path = persist_execution_report(result_data["execution_report"])
        persistence_refs["report"] = report_path
    if result_data.get("escalation_request"):
        escalation_path = persist_escalation_request(result_data["escalation_request"])
        persistence_refs["escalation"] = escalation_path

    if delegation_task is not None:
        decision_type = "delegate"
    elif request.get("metadata", {}).get("action"):
        decision_type = "execute_through_kernel"
    else:
        decision_type = "respond"

    cycle = _build_cycle(
        cycle_id=cycle_id,
        intent=intent,
        decision_type=decision_type,
        canonical_request=request,
        delegation_task=delegation_task,
        result=result,
        translator_status="translated",
        persistence_refs=persistence_refs,
        notes=result.get("result_type", ""),
    )
    cycle_path = persist_cycle_record(cycle)
    cycle.persistence_refs["cycle"] = cycle_path
    persist_cycle_record(cycle)
    persistence_refs["cycle"] = cycle_path

    if result.get("plan_id"):
        attach_persistence_refs(result["plan_id"], persistence_refs)
        attach_sovereign_cycle(result["plan_id"], cycle)
    enriched_data = dict(result_data)
    if persistence_refs:
        enriched_data["persistence_refs"] = persistence_refs
        result["data"] = enriched_data

    return {
        "cycle": asdict(cycle),
        "sovereign_intent": asdict(intent),
        "delegation_task": asdict(delegation_task) if delegation_task else None,
        "canonical_request": request,
        "translator_rejection": None,
        "result": result,
    }
