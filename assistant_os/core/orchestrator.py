"""
Assistant Kernel — Orchestrator v1

Single coordination point for the canonical request pipeline:

  CanonicalRequest
    → semantic.classify    (intent)
    → planning.build_plan  (ExecutionPlan)
    → policy.build_policy  (PolicyDecision)
    → routing.get_pipeline (domain registry dispatch)
    → domain pipeline      (WORK or FIN)
    → DomainResult

The kernel has NO dependency on WebhookHandler or any HTTP transport object.
Transport adaption (DomainResult → Response) happens in webhook_server._adapt_result_to_response.

Public API
----------
handle_request(req: CanonicalRequest, *, forced_operation: str = "") -> DomainResult

Confirmation flow (Phase 3C)
-----------------------------
When a plan requires user confirmation (execution_mode=confirm), the orchestrator:
  1. Stores the plan in context_store keyed by plan["plan_id"].
  2. Returns DomainResult{result_type="plan_confirmation_required", data.plan_id}.

On the next call, the caller supplies metadata["confirm_plan_id"] = plan_id.
The orchestrator retrieves the plan, removes it (single-use), and executes the pipeline.
This guarantees that ALL execution goes through the orchestrator — no direct pipeline calls.
"""

from __future__ import annotations

from dataclasses import asdict
import logging

from ..contracts import (
    CanonicalRequest,
    DomainResult,
    now_iso,
    make_domain_result,
    ACTION_UNKNOWN,
    RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
    RESULT_TYPE_PLAN_GENERATED,
    RESULT_TYPE_CONFIRM_ERROR,
    EXECUTION_MODE_AUTO,
    EXECUTION_MODE_BLOCKED,
    EXECUTION_MODE_CONFIRM,
    EXECUTION_MODE_CLARIFY,
)

_log = logging.getLogger(__name__)


def _consult_mso_advisory(
    req: CanonicalRequest,
    *,
    intent: dict,
    plan: dict,
) -> dict | None:
    """Consult the local advisory engine without affecting deterministic routing."""
    try:
        from ..mso.advisory_engine import consult_orchestrator_advisory

        response = consult_orchestrator_advisory(
            text=req.get("text", ""),
            intent=intent,
            plan=plan,
        )
        return response if response.get("status") in {"ok", "ignored"} else response
    except Exception as exc:
        _log.debug("local_llm advisory consultation failed non-fatally: %s", exc)
        return None


def _build_advisory_trace(
    advisory: dict | None,
    *,
    final_domain: str,
    final_action: str,
    final_execution_mode: str,
) -> dict | None:
    if advisory is None:
        return None

    from ..mso.advisory_engine import build_advisory_trace

    return build_advisory_trace(
        advisory,
        final_domain=final_domain,
        final_action=final_action,
        final_execution_mode=final_execution_mode,
    )


def _attach_advisory_metadata(plan: dict, advisory: dict | None, trace: dict | None) -> dict:
    plan_for_exec = dict(plan)
    if advisory:
        plan_for_exec["_mso_advisory"] = advisory
        if advisory.get("code_package"):
            payload = dict(plan_for_exec.get("domain_payload") or {})
            payload["_mso_code_package"] = dict(advisory["code_package"])
            plan_for_exec["domain_payload"] = payload
    if trace:
        plan_for_exec["_mso_trace"] = trace
    return plan_for_exec


def _log_advisory_trace(trace: dict | None) -> None:
    if not trace:
        return
    _log.info(
        "mso advisory consulted=%s status=%s roles=%s suggested_action=%s final_action=%s final_mode=%s",
        trace.get("consulted"),
        trace.get("status"),
        ",".join(trace.get("consulted_roles") or []),
        trace.get("routing_hint_action", ""),
        trace.get("final_action", ""),
        trace.get("final_execution_mode", ""),
    )


def _evaluate_mso_governance(
    *,
    plan: dict,
    execution_mode: str,
    advisory_trace: dict | None,
) -> object:
    from ..mso.governance_engine import evaluate_governance
    from ..mso.risk_engine import evaluate_risk

    risk = evaluate_risk(
        domain=plan.get("domain", "UNKNOWN"),
        action=plan.get("action", ""),
        risk_level=plan.get("risk_level", "medium"),
        execution_mode=execution_mode,
        advisory_trace=advisory_trace,
    )
    return evaluate_governance(
        action=plan.get("action", ""),
        domain=plan.get("domain", "UNKNOWN"),
        base_execution_mode=execution_mode,
        risk=risk,
        created_at=now_iso(),
    )


def _log_governance_trace(governance_trace: dict | None) -> None:
    if not governance_trace:
        return
    _log.info(
        "mso governance action=%s base_mode=%s effective_mode=%s risk=%s",
        governance_trace.get("action", ""),
        governance_trace.get("base_execution_mode", ""),
        governance_trace.get("effective_execution_mode", ""),
        governance_trace.get("risk_level", ""),
    )


def _attach_governance_metadata(plan: dict, governance_trace: dict | None) -> dict:
    plan_for_exec = dict(plan)
    if governance_trace:
        plan_for_exec["_mso_governance"] = governance_trace
    return plan_for_exec


def _attach_governance_result_metadata(result: DomainResult, governance_trace: dict | None) -> DomainResult:
    if not governance_trace:
        return result
    data = dict(result.get("data") or {})
    data["governance_trace"] = governance_trace
    result["data"] = data
    return result


def _publish_mso_observation(
    *,
    req: CanonicalRequest,
    intent: dict,
    plan: dict,
    execution_mode: str,
    final_execution_mode: str,
    advisory_trace: dict | None,
    governance_trace: dict | None,
    result: DomainResult,
    executed: bool,
) -> DomainResult:
    """Publish additive MSO state without affecting canonical execution."""
    try:
        from ..mso.contracts import DeterministicDecisionTrace, GovernanceDecision, TaskRecord
        from ..mso.task_registry import register_task, transition_task
        from ..mso.trace_aggregator import begin_trace_chain, finalize_trace_chain

        timestamp = now_iso()
        plan_id = plan.get("plan_id", "")
        trace_id = plan.get("trace_id", "")
        domain = plan.get("domain", "UNKNOWN")
        action = plan.get("action", "")
        task_id = plan_id or trace_id or req.get("context_id", "")
        advisory_ref = f"advisory:{plan_id}" if advisory_trace else ""
        decision_ref = f"decision:{plan_id}" if plan_id else ""
        governance_ref = governance_trace.get("governance_ref", "") if governance_trace else ""

        if final_execution_mode == EXECUTION_MODE_AUTO:
            initial_status = "active"
        elif final_execution_mode in (EXECUTION_MODE_CONFIRM, EXECUTION_MODE_CLARIFY):
            initial_status = "pending"
        else:
            initial_status = "blocked"

        decision_trace = DeterministicDecisionTrace(
            decision_ref=decision_ref,
            context_id=req.get("context_id", ""),
            trace_id=trace_id,
            plan_id=plan_id,
            domain=domain,
            action=action,
            execution_mode=execution_mode,
            operation=intent.get("operation", ""),
            preview=plan.get("preview", ""),
            created_at=timestamp,
            advisory_trace_ref=advisory_ref,
            governance_trace_ref=governance_ref,
        )
        governance_decision = GovernanceDecision(**governance_trace) if governance_trace else None
        register_task(
            TaskRecord(
                task_id=task_id,
                context_id=req.get("context_id", ""),
                trace_id=trace_id,
                plan_id=plan_id,
                domain=domain,
                status=initial_status,
                created_at=timestamp,
                updated_at=timestamp,
                last_known_action=action,
                request_text=req.get("text", ""),
                execution_mode=final_execution_mode,
                started_at=timestamp if initial_status == "active" else "",
                advisory_trace_ref=advisory_ref,
                decision_trace_ref=decision_ref,
                governance_trace_ref=governance_ref,
            )
        )
        begin_trace_chain(
            task_id=task_id,
            context_id=req.get("context_id", ""),
            trace_id=trace_id,
            plan_id=plan_id,
            request_text=req.get("text", ""),
            operation=intent.get("operation", ""),
            domain=domain,
            action=action,
            execution_mode=execution_mode,
            created_at=timestamp,
            advisory_trace=advisory_trace,
            decision_trace=decision_trace,
            governance_trace=governance_trace,
            governance_decision=governance_decision,
        )
        finalize_trace_chain(
            plan_id,
            executed=executed,
            result=result,
            execution_id=result.get("plan_id", "") or plan_id,
        )

        if executed:
            terminal_status = "completed" if result.get("ok") else "failed"
            transition_task(
                task_id,
                to_status=terminal_status,
                reason=result.get("result_type", ""),
                result_type=result.get("result_type", ""),
                error_type=(result.get("error") or {}).get("type", ""),
                error_message=(result.get("error") or {}).get("message", ""),
                execution_id=result.get("plan_id", "") or plan_id,
            )
        return result
    except Exception as exc:
        _log.debug("mso state publication failed non-fatally: %s", exc)
        return result


def handle_request(
    req: CanonicalRequest,
    *,
    forced_operation: str = "",
) -> DomainResult:
    """
    Orchestrate a CanonicalRequest through the full domain pipeline.

    No HTTP transport objects are accepted or returned. The caller (WebhookHandler)
    is responsible for normalizing the raw request before calling this function and
    for adapting the returned DomainResult into the legacy Response shape.

    Pipeline stages
    ---------------
    NL path (default):
    1. Semantic classification  → intent
    2. Structural planning      → ExecutionPlan
    3. Policy decision          → execution_mode
    4. Domain registry dispatch → DomainResult (or policy fallback)

    Structured path (when req["metadata"]["action"] is set):
    - Skips NL classification and plan building.
    - Builds plan directly from req["filters"] + req["metadata"].
    - Still runs policy decision and domain dispatch.
    - Used by structured HTTP endpoints (pre-parsed filters, known action).

    Args
    ----
    req:              Normalized CanonicalRequest produced by normalize_request().
                      req["context_id"] is used as the canonical request context ID.
    forced_operation: Optional operation string from the HTTP routing layer.
                      Must be one of the OP_* constants when provided.
                      Ignored when req["metadata"]["action"] is set (structured path).

    Returns
    -------
    DomainResult — canonical output contract. The caller adapts this to the
    legacy Response transport shape via _adapt_result_to_response.
    """
    from .policy import build_policy
    from .routing import get_pipeline, action_domain

    context_id = req["context_id"]
    text = req["text"]

    # ---------------------------------------------------------------------------
    # Confirm path (Phase 3C): execute a previously stored plan.
    # Checked FIRST so confirm_plan_id takes priority over action/NL paths.
    # ---------------------------------------------------------------------------
    meta = req.get("metadata", {})
    if meta.get("confirm_plan_id"):
        return _execute_confirmed_plan(
            plan_id=meta["confirm_plan_id"],
            context_id=context_id,
        )

    # ---------------------------------------------------------------------------
    # Structured path: when metadata["action"] is present, skip NL classification
    # and planning. Build plan directly from req["filters"] + req["metadata"].
    # This handles structured HTTP endpoints where the action and filters are
    # already known (pre-parsed), bypassing NL text parsing entirely.
    # ---------------------------------------------------------------------------
    if meta.get("action"):
        from ..contracts import make_plan, RISK_LOW
        structured_action = meta["action"]
        derived_domain = action_domain(structured_action)
        structured_plan = make_plan(
            domain=meta.get("domain", derived_domain),
            action=structured_action,
            target=meta.get("target", structured_action),
            filters=req.get("filters", {}),
            risk_level=meta.get("risk_level", RISK_LOW),
            raw_text=text,
            requires_confirmation=meta.get("requires_confirmation", False),
        )
        if meta.get("domain_payload"):
            structured_plan["domain_payload"] = meta["domain_payload"]
        structured_intent = {
            "operation": structured_action,
            "domain": meta.get("domain", derived_domain),
            "confidence": 1.0,
            "reason": "structured_path",
        }
        policy = build_policy(req, structured_intent, structured_plan)
        execution_mode = policy.get("execution_mode", EXECUTION_MODE_AUTO)
        advisory = _consult_mso_advisory(req, intent=structured_intent, plan=structured_plan)
        advisory_trace = _build_advisory_trace(
            advisory,
            final_domain=structured_plan.get("domain", derived_domain),
            final_action=structured_action,
            final_execution_mode=execution_mode,
        )
        _log_advisory_trace(advisory_trace)
        governance = _evaluate_mso_governance(
            plan=structured_plan,
            execution_mode=execution_mode,
            advisory_trace=advisory_trace,
        )
        governance_trace = asdict(governance)
        execution_mode = governance.effective_execution_mode
        _log_governance_trace(governance_trace)

        plan_for_exec = _attach_advisory_metadata(structured_plan, advisory, advisory_trace)
        plan_for_exec = _attach_governance_metadata(plan_for_exec, governance_trace)
        plan_for_exec["raw_text"] = text

        if execution_mode == EXECUTION_MODE_AUTO:
            pipeline = get_pipeline(derived_domain)
            if pipeline:
                result = pipeline(plan_for_exec, context_id)
                return _publish_mso_observation(
                    req=req,
                    intent=structured_intent,
                    plan=structured_plan,
                    execution_mode=governance.base_execution_mode,
                    final_execution_mode=execution_mode,
                    advisory_trace=advisory_trace,
                    governance_trace=governance_trace,
                    result=result,
                    executed=True,
                )

        if execution_mode in (EXECUTION_MODE_CONFIRM, EXECUTION_MODE_CLARIFY):
            _store_pending_plan(structured_plan, structured_action, text)
            plan_id = structured_plan.get("plan_id", "")
            result = make_domain_result(
                ok=True,
                result_type=RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
                domain=structured_plan.get("domain", "UNKNOWN"),
                message=f"¿Confirmar: {structured_plan.get('preview')}?",
                data={
                    "type": "plan_confirmation_required",
                    "plan": dict(structured_plan),
                    "plan_id": plan_id,
                    "confirmation_message": f"¿Confirmar: {structured_plan.get('preview')}?",
                    "advisory_trace": advisory_trace or {},
                    "governance_trace": governance_trace,
                },
            )
            result = _attach_governance_result_metadata(result, governance_trace)
            return _publish_mso_observation(
                req=req,
                intent=structured_intent,
                plan=structured_plan,
                execution_mode=governance.base_execution_mode,
                final_execution_mode=execution_mode,
                advisory_trace=advisory_trace,
                governance_trace=governance_trace,
                result=result,
                executed=False,
            )

        domain = structured_plan.get("domain", "UNKNOWN")
        message = f"Dominio detectado: {domain}. Acción: {structured_action}."
        result = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_PLAN_GENERATED,
            domain=domain,
            message=(
                    "Ejecucion bloqueada por gobernanza MSO. "
                f"{governance.justification}"
                if execution_mode == EXECUTION_MODE_BLOCKED
                else message
            ),
            data={
                "type": "plan_generated",
                "plan": dict(structured_plan),
                "advisory_trace": advisory_trace or {},
                "governance_trace": governance_trace,
                "governance_blocked": execution_mode == EXECUTION_MODE_BLOCKED,
            },
        )
        result = _attach_governance_result_metadata(result, governance_trace)
        return _publish_mso_observation(
            req=req,
            intent=structured_intent,
            plan=structured_plan,
            execution_mode=governance.base_execution_mode,
            final_execution_mode=execution_mode,
            advisory_trace=advisory_trace,
            governance_trace=governance_trace,
            result=result,
            executed=False,
        )

    # ---------------------------------------------------------------------------
    # NL path: classify text → build plan → policy → dispatch
    # ---------------------------------------------------------------------------
    from .semantic import classify
    from .planning import build_plan

    # Stage 1 — Semantic: classify text and apply routing hint.
    intent = classify(req, forced_operation)

    # Stage 2 — Planning: build structural ExecutionPlan.
    plan = build_plan(req, intent)
    action = plan.get("action", ACTION_UNKNOWN)

    # Stage 3 — Policy: determine execution_mode.
    # policy.execution_mode is the authoritative dispatch signal from this point.
    # plan.requires_confirmation is NOT read here — it feeds into policy as input
    # and is preserved in the plan data for downstream consumers (e.g. UI, audit).
    policy = build_policy(req, intent, plan)
    execution_mode = policy.get("execution_mode", EXECUTION_MODE_CONFIRM)
    advisory = _consult_mso_advisory(req, intent=intent, plan=plan)
    advisory_trace = _build_advisory_trace(
        advisory,
        final_domain=plan.get("domain", "UNKNOWN"),
        final_action=action,
        final_execution_mode=execution_mode,
    )
    _log_advisory_trace(advisory_trace)
    governance = _evaluate_mso_governance(
        plan=plan,
        execution_mode=execution_mode,
        advisory_trace=advisory_trace,
    )
    governance_trace = asdict(governance)
    execution_mode = governance.effective_execution_mode
    _log_governance_trace(governance_trace)

    # Stage 4 — Domain registry dispatch.
    #
    # Attach raw_text once so any pipeline that needs it (WORK_UPDATE,
    # FIN_EXPENSE) can read plan["raw_text"] without action-level branching.
    plan_for_exec = _attach_advisory_metadata(plan, advisory, advisory_trace)
    plan_for_exec = _attach_governance_metadata(plan_for_exec, governance_trace)
    plan_for_exec["raw_text"] = text

    # execution_mode == "auto": policy determined this action is safe to execute
    # immediately. Only actions in _AUTO_EXECUTE_WHITELIST reach this path.
    if execution_mode == EXECUTION_MODE_AUTO:
        pipeline = get_pipeline(action_domain(action))
        if pipeline:
            result = pipeline(plan_for_exec, context_id)
            return _publish_mso_observation(
                req=req,
                intent=intent,
                plan=plan,
                execution_mode=governance.base_execution_mode,
                final_execution_mode=execution_mode,
                advisory_trace=advisory_trace,
                governance_trace=governance_trace,
                result=result,
                executed=True,
            )
        # Defensive: whitelisted action but no registered pipeline → fall through.

    # execution_mode == "confirm" or "clarify": user must approve before execution.
    # "clarify" means required info is missing; treated as pending confirmation
    # until a dedicated clarify response type is introduced.
    if execution_mode in (EXECUTION_MODE_CONFIRM, EXECUTION_MODE_CLARIFY):
        _store_pending_plan(plan, action, text)
        plan_id = plan.get("plan_id", "")
        result = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
            domain=plan.get("domain", "UNKNOWN"),
            message=f"¿Confirmar: {plan.get('preview')}?",
            data={
                "type": "plan_confirmation_required",
                "plan": dict(plan),
                "plan_id": plan_id,
                "confirmation_message": f"¿Confirmar: {plan.get('preview')}?",
                "advisory_trace": advisory_trace or {},
                "governance_trace": governance_trace,
            },
        )
        result = _attach_governance_result_metadata(result, governance_trace)
        return _publish_mso_observation(
            req=req,
            intent=intent,
            plan=plan,
            execution_mode=governance.base_execution_mode,
            final_execution_mode=execution_mode,
            advisory_trace=advisory_trace,
            governance_trace=governance_trace,
            result=result,
            executed=False,
        )

    # execution_mode == "blocked" (or auto with no pipeline): unregistered domain
    # or unsupported action. Return the plan for informational routing.
    domain = plan.get("domain", "UNKNOWN")
    message = (
        f"Dominio detectado: {domain}. "
        "Use el chat o especifique un prefijo (CODE:, DOC:, JOBS:, BIZ:)."
    )
    result = make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_PLAN_GENERATED,
        domain=domain,
        message=(
            "Ejecucion bloqueada por gobernanza MSO. "
            f"{governance.justification}"
            if execution_mode == EXECUTION_MODE_BLOCKED
            else message
        ),
        data={
            "type": "plan_generated",
            "plan": dict(plan),
            "domain": domain,
            "action": action,
            "confidence": plan.get("confidence", 0),
            "preview": plan.get("preview", ""),
            "message": message,
            "advisory_trace": advisory_trace or {},
            "governance_trace": governance_trace,
            "governance_blocked": execution_mode == EXECUTION_MODE_BLOCKED,
        },
    )
    result = _attach_governance_result_metadata(result, governance_trace)
    return _publish_mso_observation(
        req=req,
        intent=intent,
        plan=plan,
        execution_mode=governance.base_execution_mode,
        final_execution_mode=execution_mode,
        advisory_trace=advisory_trace,
        governance_trace=governance_trace,
        result=result,
        executed=False,
    )


# ---------------------------------------------------------------------------
# Phase 3C — confirmation flow helpers (module-private)
# ---------------------------------------------------------------------------


def _store_pending_plan(plan: dict, operation: str, raw_text: str) -> None:
    """
    Persist plan in context_store keyed by plan["plan_id"].

    Called whenever the orchestrator returns plan_confirmation_required so
    the caller can later submit metadata["confirm_plan_id"] to execute it.

    Best-effort: if the store fails (disk error, etc.) the plan is simply
    not persisted — the caller receives plan_confirmation_required and the
    subsequent confirm call will return a "plan not found" error.
    """
    from ..context_store import store_pending_plan
    plan_id = plan.get("plan_id")
    if not plan_id:
        return  # Defensive: plan without plan_id cannot be confirmed by id
    try:
        store_pending_plan(
            context_id=plan_id,
            plan=plan,
            operation=operation,
            raw_text=raw_text,
        )
    except Exception:
        pass  # Best-effort — never block the confirmation_required response


def _execute_confirmed_plan(plan_id: str, context_id: str) -> DomainResult:
    """
    Execute a previously stored plan identified by plan_id.

    Invariants
    ----------
    - Single-use: plan is removed BEFORE pipeline execution to prevent replay.
    - plan_id is preserved end-to-end (plan["plan_id"] == the original plan_id).
    - No policy re-evaluation: the plan already passed policy in pass 1.
    - Control plane / confirmed gates still fire inside the pipeline.

    Error paths
    -----------
    - plan not found or expired → ok=False, result_type=confirm_error
    - no registered pipeline for domain → ok=False, result_type=confirm_error
    """
    from ..context_store import get_pending_plan, remove_pending_plan
    from .routing import get_pipeline, action_domain

    stored = get_pending_plan(plan_id)
    if stored is None:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CONFIRM_ERROR,
            domain="UNKNOWN",
            message=f"No pending plan found for plan_id {plan_id!r} (not found or expired)",
            data={"plan_id": plan_id},
            error={
                "type": "PlanNotFound",
                "message": f"No pending plan: {plan_id!r}",
            },
        )

    plan = stored["plan"]
    action = plan.get("action", "")
    domain = action_domain(action)

    pipeline = get_pipeline(domain)
    if pipeline is None:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CONFIRM_ERROR,
            domain=domain,
            message=f"No pipeline registered for domain {domain!r}",
            data={"plan_id": plan_id, "action": action, "domain": domain},
            error={
                "type": "NoPipeline",
                "message": f"No pipeline for domain: {domain!r}",
            },
        )

    # Single-use: remove before executing to prevent replay on pipeline error.
    remove_pending_plan(plan_id)

    return pipeline(plan, context_id)
