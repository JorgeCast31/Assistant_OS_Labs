"""
FIN Domain Pipeline v1

Entry point: execute(plan, context_id) -> DomainResult

Dispatches to the appropriate FIN execution helper based on plan action.
``parse_expense`` is lazy-imported from ``fin_expense`` — its authoritative
owner.  Prior to M0.8 it was imported from ``webhook_server`` (HTTP layer).
Test patches should target ``assistant_os.fin_expense.parse_expense``.

Sprint 2 additions:
  ACTION_FIN_PLAN     → _fin_plan_execute
  ACTION_FIN_COMMIT   → _fin_commit_execute
  ACTION_FIN_CONFIRM  → _fin_confirm_execute
  ACTION_FIN_CHAPERON → _fin_chaperon_execute
  ACTION_FIN_BATCH    → _fin_batch_execute
"""

from __future__ import annotations

from ..contracts import (
    DomainResult,
    make_domain_result,
    ACTION_FIN_EXPENSE,
    ACTION_FIN_BATCH,
    ACTION_FIN_PLAN,
    ACTION_FIN_COMMIT,
    ACTION_FIN_CONFIRM,
    ACTION_FIN_CHAPERON,
    RESULT_TYPE_FIN_EXPENSE,
    RESULT_TYPE_FIN_BATCH,
    RESULT_TYPE_FIN_PLAN,
    RESULT_TYPE_FIN_COMMIT,
    RESULT_TYPE_FIN_CONFIRM,
    RESULT_TYPE_FIN_CHAPERON,
    EXECUTION_STATUS_REAL,
    EXECUTION_STATUS_UNAVAILABLE,
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
    try:
        result = _dispatch(plan, context_id)
        result["execution_status"] = EXECUTION_STATUS_REAL
        return result
    except Exception as exc:  # pragma: no cover
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_FIN_EXPENSE,
            domain="FIN",
            message="Unexpected error in FIN pipeline",
            data={},
            error={"type": "FinPipelineError", "message": str(exc)},
            execution_status=EXECUTION_STATUS_UNAVAILABLE,
        )


def _dispatch(plan: dict, context_id: str) -> DomainResult:
    _context = get_context(context_id)  # noqa: F841 — reserved for future use

    action = plan.get("action", "")

    if action == ACTION_FIN_EXPENSE:
        return _fin_expense_execute(plan)
    if action == ACTION_FIN_BATCH:
        return _fin_batch_execute(plan)
    if action == ACTION_FIN_PLAN:
        return _fin_plan_execute(plan)
    if action == ACTION_FIN_COMMIT:
        return _fin_commit_execute(plan)
    if action == ACTION_FIN_CONFIRM:
        return _fin_confirm_execute(plan)
    if action == ACTION_FIN_CHAPERON:
        return _fin_chaperon_execute(plan)

    return make_domain_result(
        ok=False,
        result_type="fin_unknown",
        domain="FIN",
        message=f"Acción FIN desconocida: {action}",
        data={"plan": dict(plan)},
        error={"type": "UnknownAction", "message": f"No handler for FIN action: {action}"},
    )


def _append_expense_to_sheets(expense: dict, session_id: str = "") -> dict:
    """
    Shared helper: write one expense row to Google Sheets.

    Returns a plain dict with keys: ok, row_number, error_message.
    """
    from ..tools.google.append_expense_row_tool import AppendExpenseRowTool
    tool_result = AppendExpenseRowTool().execute({
        "fecha":        expense.get("fecha", ""),
        "descripcion":  expense.get("descripcion", ""),
        "factura":      expense.get("factura", ""),
        "responsable":  expense.get("responsable", ""),
        "monto":        expense.get("monto", 0),
        "moneda":       expense.get("moneda", "USD"),
        "itbms":        expense.get("itbms", False),
        "categoria":    expense.get("categoria", "otros"),
        "metodo_pago":  expense.get("metodo_pago", ""),
        "notas":        expense.get("notas", ""),
        "fuente":       expense.get("fuente", "Texto"),
        "link_archivo": expense.get("link_archivo", ""),
        "expense_id":   session_id or expense.get("expense_id", ""),
    })
    if tool_result.ok:
        return {"ok": True, "row_number": tool_result.data.get("row_number"), "error_message": ""}
    err_msg = tool_result.error.message if tool_result.error else "Sheets error"
    return {"ok": False, "row_number": None, "error_message": err_msg}


def _fin_expense_execute(plan: dict) -> DomainResult:
    """Execute a FIN expense: parse, then auto-store to Sheets if complete and available."""
    from ..fin_expense import parse_expense, ExpenseRequest
    from ..integrations.sheets import check_sheets_available, get_sheets_last_error

    text = plan.get("raw_text", "")
    filters = plan.get("filters", {})
    # Build a proper ExpenseRequest so parse_expense receives the expected dict shape.
    expense_request: ExpenseRequest = {
        "text": text,
        "override": filters.get("override", {}),
        "session_id": filters.get("session_id", ""),
    }
    expense_result = parse_expense(expense_request)

    if not expense_result.get("ok"):
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_FIN_EXPENSE,
            domain="FIN",
            message=expense_result.get("error", "No se pudo parsear el gasto"),
            data={
                "stored": False,
                "expense": None,
                "row_number": None,
                "missing_fields": expense_result.get("missing_fields", []),
                "needs_confirmation": expense_result.get("needs_confirmation", False),
                "ambiguous_responsables": [],
                "sheets_available": check_sheets_available(),
                "sheets_error": None,
            },
            error={
                "type": "ExpenseParseError",
                "message": expense_result.get("error", "No se pudo parsear el gasto"),
            },
        )

    exp = expense_result["expense"]
    needs_confirmation = expense_result.get("needs_confirmation", False)
    missing_fields = expense_result.get("missing_fields", [])
    ambiguous_responsables = expense_result.get("ambiguous_responsables", [])

    # Missing fields — return parsed data for confirmation flow
    if needs_confirmation:
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_FIN_EXPENSE,
            domain="FIN",
            message=expense_result.get("message", "Gasto detectado"),
            data={
                "type": "expense_parsed",
                "stored": False,
                "expense": exp,
                "row_number": None,
                "missing_fields": missing_fields,
                "needs_confirmation": True,
                "ambiguous_responsables": ambiguous_responsables,
                "sheets_available": check_sheets_available(),
                "sheets_error": None,
                "message": expense_result.get("message", "Gasto detectado"),
            },
        )

    # All required fields present — check Sheets before storing
    sheets_available = check_sheets_available()
    if not sheets_available:
        last_error = get_sheets_last_error()
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_FIN_EXPENSE,
            domain="FIN",
            message="Gasto parseado pero Sheets no está disponible",
            data={
                "type": "expense_parsed",
                "stored": False,
                "expense": exp,
                "row_number": None,
                "missing_fields": missing_fields,
                "needs_confirmation": False,
                "ambiguous_responsables": ambiguous_responsables,
                "sheets_available": False,
                "sheets_error": last_error,
                "message": expense_result.get("message", "Gasto detectado"),
            },
        )

    # Auto-store to Sheets
    session_id = filters.get("session_id", "")
    result = _append_expense_to_sheets(exp, session_id)
    if result["ok"]:
        row_number = result["row_number"]
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_FIN_EXPENSE,
            domain="FIN",
            message=f"Guardado en Sheets (fila {row_number})",
            data={
                "type": "expense_stored",
                "stored": True,
                "expense": exp,
                "row_number": row_number,
                "missing_fields": [],
                "needs_confirmation": False,
                "ambiguous_responsables": ambiguous_responsables,
                "sheets_available": True,
                "sheets_error": None,
                "message": f"Guardado en Sheets (fila {row_number})",
            },
        )

    # Sheets write error
    err_msg = result["error_message"]
    last_error = get_sheets_last_error()
    if "Header mismatch" in err_msg:
        error_type = "SheetSchemaMismatch"
    elif last_error:
        error_type = last_error.get("type", "unknown_error")
    else:
        error_type = "unknown_error"
    return make_domain_result(
        ok=False,
        result_type=RESULT_TYPE_FIN_EXPENSE,
        domain="FIN",
        message=err_msg,
        data={
            "type": "expense_parsed",
            "stored": False,
            "expense": exp,
            "row_number": None,
            "missing_fields": [],
            "needs_confirmation": False,
            "ambiguous_responsables": ambiguous_responsables,
            "sheets_available": True,
            "sheets_error": last_error,
            "message": err_msg,
        },
        error={"type": error_type, "message": err_msg},
    )


def _fin_plan_execute(plan: dict) -> DomainResult:
    """Execute FIN plan analysis — calls generate_fin_plan and returns items."""
    from ..fin_plan import generate_fin_plan

    text = plan.get("raw_text", "")
    filters = plan.get("filters", {})
    session_context = filters.get("session_context")

    plan_response = generate_fin_plan(text, session_context)

    if plan_response.get("ok"):
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_FIN_PLAN,
            domain="FIN",
            message=plan_response.get("message", "Plan generado"),
            data={
                "kind":               plan_response.get("kind", "fin_plan"),
                "mode":               plan_response.get("mode", "single"),
                "total_items":        plan_response.get("total_items", 0),
                "items":              plan_response.get("items", []),
                "needs_clarification": plan_response.get("needs_clarification", False),
                "clarification_prompt": plan_response.get("clarification_prompt", ""),
                "session_context":    plan_response.get("session_context", {}),
                "message":            plan_response.get("message", "Plan generado"),
            },
            plan_id=plan.get("plan_id"),
            trace_id=plan.get("trace_id"),
        )
    return make_domain_result(
        ok=False,
        result_type=RESULT_TYPE_FIN_PLAN,
        domain="FIN",
        message=plan_response.get("message", "No se pudo generar el plan"),
        data={},
        error={"type": "FinPlanError", "message": plan_response.get("message", "Error generando plan")},
        plan_id=plan.get("plan_id"),
        trace_id=plan.get("trace_id"),
    )


def _fin_commit_execute(plan: dict) -> DomainResult:
    """Execute FIN commit — canonicalize and store one expense to Sheets."""
    from .fin_normalization import canonicalize_commit_expense

    filters = plan.get("filters", {})
    expense = filters.get("expense", {})
    session_id = filters.get("session_id", "")

    if expense:
        expense = canonicalize_commit_expense(expense)

    if not expense:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_FIN_COMMIT,
            domain="FIN",
            message="No se proporcionó el gasto para guardar",
            data={},
            error={"type": "MissingExpense", "message": "expense dict is required in filters"},
            plan_id=plan.get("plan_id"),
            trace_id=plan.get("trace_id"),
        )

    result = _append_expense_to_sheets(expense, session_id)
    if result["ok"]:
        row_number = result["row_number"]
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_FIN_COMMIT,
            domain="FIN",
            message=f"Gasto guardado en Sheets (fila {row_number})",
            data={
                "stored": True,
                "row_number": row_number,
                "expense": expense,
            },
            plan_id=plan.get("plan_id"),
            trace_id=plan.get("trace_id"),
        )
    return make_domain_result(
        ok=False,
        result_type=RESULT_TYPE_FIN_COMMIT,
        domain="FIN",
        message=result["error_message"],
        data={"stored": False},
        error={"type": "SheetsError", "message": result["error_message"]},
        plan_id=plan.get("plan_id"),
        trace_id=plan.get("trace_id"),
    )


def _fin_confirm_execute(plan: dict) -> DomainResult:
    """Execute FIN confirm — store confirmed expense fields to Sheets."""
    filters = plan.get("filters", {})
    # confirm passes individual fields (not nested 'expense' dict)
    expense = {
        "fecha":       filters.get("fecha", ""),
        "monto":       filters.get("monto", 0),
        "moneda":      filters.get("moneda", "USD"),
        "descripcion": filters.get("descripcion", ""),
        "responsable": filters.get("responsable", ""),
        "categoria":   filters.get("categoria", "otros"),
        "itbms":       filters.get("itbms", False),
        "metodo_pago": filters.get("metodo_pago", ""),
        "notas":       filters.get("notas", ""),
        "factura":     filters.get("factura", ""),
    }
    session_id = filters.get("session_id", "")

    result = _append_expense_to_sheets(expense, session_id)
    if result["ok"]:
        row_number = result["row_number"]
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_FIN_CONFIRM,
            domain="FIN",
            message=f"Guardado en Sheets (fila {row_number})",
            data={
                "stored": True,
                "row_number": row_number,
                "expense": expense,
            },
            plan_id=plan.get("plan_id"),
            trace_id=plan.get("trace_id"),
        )
    return make_domain_result(
        ok=False,
        result_type=RESULT_TYPE_FIN_CONFIRM,
        domain="FIN",
        message=result["error_message"],
        data={"stored": False},
        error={"type": "SheetsError", "message": result["error_message"]},
        plan_id=plan.get("plan_id"),
        trace_id=plan.get("trace_id"),
    )


def _fin_batch_execute(plan: dict) -> DomainResult:
    """Execute FIN batch — parse and store multiple expenses."""
    from ..fin_expense import parse_expense

    filters = plan.get("filters", {})
    items = filters.get("items", [])

    if not items:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_FIN_BATCH,
            domain="FIN",
            message="No se proporcionaron items para el lote",
            data={},
            error={"type": "MissingItems", "message": "items list is required in filters"},
            plan_id=plan.get("plan_id"),
            trace_id=plan.get("trace_id"),
        )

    results = []
    stored_count = 0
    sheets_available = True

    for i, item in enumerate(items):
        # Build expense request from item
        raw_segment = item.get("raw_segment", "")
        if not raw_segment:
            # Reconstruct text from confirmed fields if raw_segment missing
            raw_segment = " ".join(filter(None, [
                str(item.get("monto", "")),
                item.get("moneda", ""),
                item.get("descripcion", ""),
                f"para {item.get('responsable', '')}" if item.get("responsable") else "",
            ]))

        expense_request = {
            "text": raw_segment,
            "override": item.get("override", {}),
            "session_id": item.get("session_id", ""),
        }
        expense_result = parse_expense(expense_request)

        if not expense_result.get("ok"):
            results.append({
                "index": i,
                "ok": False,
                "stored": False,
                "row_number": None,
                "expense": None,
                "error": expense_result.get("error", "Parse error"),
            })
            continue

        expense = expense_result["expense"]
        # Override with any confirmed field values from the item
        for field in ["fecha", "monto", "moneda", "descripcion", "categoria",
                      "responsable", "itbms", "metodo_pago", "notas", "factura"]:
            if field in item and item[field] is not None:
                expense[field] = item[field]

        append_result = _append_expense_to_sheets(expense, item.get("session_id", ""))
        if append_result["ok"]:
            stored_count += 1
            results.append({
                "index": i,
                "ok": True,
                "stored": True,
                "row_number": append_result["row_number"],
                "expense": expense,
            })
        else:
            sheets_available = False
            results.append({
                "index": i,
                "ok": False,
                "stored": False,
                "row_number": None,
                "expense": expense,
                "error": append_result["error_message"],
            })

    total_items = len(items)
    message = f"Lote procesado: {stored_count}/{total_items} guardados"
    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_FIN_BATCH,
        domain="FIN",
        message=message,
        data={
            "total_items":      total_items,
            "stored_count":     stored_count,
            "sheets_available": sheets_available,
            "results":          results,
            "message":          message,
        },
        plan_id=plan.get("plan_id"),
        trace_id=plan.get("trace_id"),
    )


def _fin_chaperon_execute(plan: dict) -> DomainResult:
    """Execute FIN chaperon analysis — run chaperon on text."""
    from ..chaperon import run_chaperon

    text = plan.get("raw_text", "")
    filters = plan.get("filters", {})
    domain = filters.get("domain", "FIN")
    session_context = filters.get("session_context")

    chaperon_response = run_chaperon(text, domain, session_context)
    action_plan = chaperon_response.get("action_plan", {})

    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_FIN_CHAPERON,
        domain="FIN",
        message=action_plan.get("summary_text", "Análisis completado"),
        data={
            "action_plan":          action_plan,
            "should_execute":       chaperon_response.get("should_execute", True),
            "confirmation_message": chaperon_response.get("confirmation_message"),
            "raw_text":             chaperon_response.get("raw_text", text),
            "detected_domain":      chaperon_response.get("detected_domain", domain),
        },
        plan_id=plan.get("plan_id"),
        trace_id=plan.get("trace_id"),
    )
