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
"""

from __future__ import annotations

from ..contracts import (
    CanonicalRequest,
    DomainResult,
    make_domain_result,
    ACTION_UNKNOWN,
    RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
    RESULT_TYPE_PLAN_GENERATED,
    EXECUTION_MODE_AUTO,
    EXECUTION_MODE_CONFIRM,
    EXECUTION_MODE_CLARIFY,
)


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
    1. Semantic classification  → intent
    2. Structural planning      → ExecutionPlan
    3. Policy decision          → execution_mode
    4. Domain registry dispatch → DomainResult (or policy fallback)

    Args
    ----
    req:              Normalized CanonicalRequest produced by normalize_request().
                      req["context_id"] is used as the canonical request context ID.
    forced_operation: Optional operation string from the HTTP routing layer.
                      Must be one of the OP_* constants when provided.

    Returns
    -------
    DomainResult — canonical output contract. The caller adapts this to the
    legacy Response transport shape via _adapt_result_to_response.
    """
    from .semantic import classify
    from .planning import build_plan
    from .policy import build_policy
    from .routing import get_pipeline, action_domain

    context_id = req["context_id"]
    text = req["text"]

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

    # Stage 4 — Domain registry dispatch.
    #
    # Attach raw_text once so any pipeline that needs it (WORK_UPDATE,
    # FIN_EXPENSE) can read plan["raw_text"] without action-level branching.
    plan_for_exec = dict(plan)
    plan_for_exec["raw_text"] = text

    # execution_mode == "auto": policy determined this action is safe to execute
    # immediately. Only actions in _AUTO_EXECUTE_WHITELIST reach this path.
    if execution_mode == EXECUTION_MODE_AUTO:
        pipeline = get_pipeline(action_domain(action))
        if pipeline:
            return pipeline(plan_for_exec, context_id)
        # Defensive: whitelisted action but no registered pipeline → fall through.

    # execution_mode == "confirm" or "clarify": user must approve before execution.
    # "clarify" means required info is missing; treated as pending confirmation
    # until a dedicated clarify response type is introduced.
    if execution_mode in (EXECUTION_MODE_CONFIRM, EXECUTION_MODE_CLARIFY):
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
            domain=plan.get("domain", "UNKNOWN"),
            message=f"¿Confirmar: {plan.get('preview')}?",
            data={
                "type": "plan_confirmation_required",
                "plan": dict(plan),
                "confirmation_message": f"¿Confirmar: {plan.get('preview')}?",
            },
        )

    # execution_mode == "blocked" (or auto with no pipeline): unregistered domain
    # or unsupported action. Return the plan for informational routing.
    domain = plan.get("domain", "UNKNOWN")
    message = (
        f"Dominio detectado: {domain}. "
        "Use el chat o especifique un prefijo (CODE:, DOC:, JOBS:, BIZ:)."
    )
    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_PLAN_GENERATED,
        domain=domain,
        message=message,
        data={
            "type": "plan_generated",
            "plan": dict(plan),
            "domain": domain,
            "action": action,
            "confidence": plan.get("confidence", 0),
            "preview": plan.get("preview", ""),
            "message": message,
        },
    )
