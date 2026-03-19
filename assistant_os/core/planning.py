"""
Kernel — Planning Layer

Responsibility: build a structural ExecutionPlan from a CanonicalRequest
and its classified intent.

Planning here is structural only — it determines action, domain, risk
level, filters, and confirmation requirements. Domain-specific resolution
(e.g. resolving a Notion page) happens inside domain pipelines, not here.

_create_plan_from_intent is lazy-imported from webhook_server so that
test patches applied to that namespace remain effective.
"""

from __future__ import annotations

from ..contracts import CanonicalRequest


def build_plan(req: CanonicalRequest, intent: dict) -> dict:
    """
    Build an ExecutionPlan from a CanonicalRequest and classified intent.

    Args:
        req:    Normalized CanonicalRequest.
        intent: Intent dict produced by the semantic layer.

    Returns:
        ExecutionPlan dict with action, domain, risk_level, filters,
        requires_confirmation, trace_id, plan_id, and schema metadata.
    """
    from ..webhook_server import _create_plan_from_intent

    return _create_plan_from_intent(req["text"], intent)
