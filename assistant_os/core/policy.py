"""
Kernel — Policy Layer

Responsibility: given the classified intent and structural plan, determine
the execution_mode (auto / confirm / clarify / blocked) that governs how
the orchestrator routes the request.

PolicyDecision is an explicit architectural layer between planning and
routing. It must not be collapsed into planning or routing.
"""

from __future__ import annotations

from ..contracts import (
    CanonicalRequest,
    PolicyDecision,
    build_policy_decision,
    ACTION_UNKNOWN,
    RISK_MEDIUM,
)


def build_policy(
    req: CanonicalRequest,
    intent: dict,
    plan: dict,
) -> PolicyDecision:
    """
    Build a PolicyDecision from request context, classified intent, and plan.

    Args:
        req:    Normalized CanonicalRequest (provides text for risk context).
        intent: Intent dict from the semantic layer (confidence, operation).
        plan:   ExecutionPlan from the planning layer (action, domain, etc.).

    Returns:
        PolicyDecision with execution_mode, reasoning, and metadata.
    """
    action = plan.get("action", ACTION_UNKNOWN)

    return build_policy_decision(
        text=req["text"],
        action=action,
        domain=plan.get("domain", "UNKNOWN"),
        risk_level=plan.get("risk_level", RISK_MEDIUM),
        requires_confirmation=plan.get("requires_confirmation", False),
        confidence=intent.get("confidence", 0.0),
        classifier_intent=intent.get("operation"),
        parsed_payload=plan.get("filters", {}),
        trace_id=plan.get("trace_id"),
    )
