"""
FIN Domain Pipeline v1

Entry point: execute(plan, context_id) -> DomainResult

Dispatches to the appropriate FIN execution helper based on plan action.
Patchable names (parse_expense) are lazy-imported from webhook_server so
test patches remain effective.
"""

from __future__ import annotations

from ..contracts import (
    DomainResult,
    make_domain_result,
    ACTION_FIN_EXPENSE,
    RESULT_TYPE_FIN_EXPENSE,
)
from ..core.context import get_context


def execute(plan: dict, context_id: str) -> DomainResult:
    """
    Dispatch a FIN domain plan to the appropriate execution helper.

    Args:
        plan:       ExecutionPlan with action, raw_text, and metadata.
        context_id: Canonical context ID for this request.

    Returns:
        DomainResult — no transport wrapping.
    """
    # Retrieve execution context if available. Usage is optional — if no
    # context is stored for this context_id, behavior is identical to before.
    # Future FIN logic may inspect context.get("fin_hints") or similar fields.
    _context = get_context(context_id)  # noqa: F841 — reserved for future use

    action = plan.get("action", "")

    if action == ACTION_FIN_EXPENSE:
        return _fin_expense_execute(plan)

    return make_domain_result(
        ok=False,
        result_type="fin_unknown",
        domain="FIN",
        message=f"Acción FIN desconocida: {action}",
        data={"plan": dict(plan)},
        error={"type": "UnknownAction", "message": f"No handler for FIN action: {action}"},
    )


def _fin_expense_execute(plan: dict) -> DomainResult:
    """Execute a FIN expense parse and return DomainResult (no transport wrapping)."""
    from ..webhook_server import parse_expense

    text = plan.get("raw_text", "")
    expense_result = parse_expense(text)

    if expense_result.get("ok"):
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_FIN_EXPENSE,
            domain="FIN",
            message=expense_result.get("message", "Gasto detectado"),
            data={
                "type": "expense_parsed",
                "expense": expense_result.get("expense"),
                "message": expense_result.get("message", "Gasto detectado"),
            },
        )
    else:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_FIN_EXPENSE,
            domain="FIN",
            message=expense_result.get("error", "No se pudo parsear el gasto"),
            data={},
            error={
                "type": "ExpenseParseError",
                "message": expense_result.get("error", "No se pudo parsear el gasto"),
            },
        )
