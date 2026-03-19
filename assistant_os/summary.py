"""
Summary module - Genera resúmenes legibles de Response para consumo móvil.
Diseñado para iPhone Shortcuts y otros clientes que necesitan texto simple.
"""
from typing import Any, TypedDict, Optional

from .contracts import Response


class SummaryResponse(TypedDict):
    """Response estructurada para /command/summary."""
    ok: bool
    status: str  # Original response status: "ok", "pending", "error"
    context_id: str
    title: str
    summary: str
    details: dict[str, Any]
    raw: Optional[Response]


def summarize(response: Response, include_raw: bool = False) -> SummaryResponse:
    """
    Genera un resumen legible de una Response.
    
    Args:
        response: Response TypedDict del router
        include_raw: Si True, incluye la response original en "raw"
    
    Returns:
        SummaryResponse con campos amigables para humanos
    """
    agent = response.get("agent", "unknown")
    status = response.get("status", "error")
    output = response.get("output", {})
    error = response.get("error")
    
    is_ok = status in ("ok", "pending")
    
    # Special case: CodeAgent with error but files created is still considered OK
    # Test failures after module creation shouldn't make the whole operation "failed"
    if agent == "code" and not is_ok and output.get("module_name"):
        is_ok = True  # Module was created, even if tests failed
    
    # Build title - include action from plan if available
    status_icon = "OK" if is_ok else "ERROR"
    plan = output.get("plan", {})
    action = plan.get("action", "") if plan else ""
    if action:
        title = f"{status_icon} · {agent} [{action}]"
    else:
        title = f"{status_icon} · {agent}"
    
    # Build summary and details based on agent type
    # For code agent with error, still use code summarizer to get module info
    if agent == "code" and output.get("module_name"):
        summary, details = _summarize_code(output)
        # Add error info if present
        if error:
            err_msg = error.get("message", "")
            if err_msg and "test" in err_msg.lower():
                summary += f"\n⚠️ Tests: {err_msg}"
    elif not is_ok and error:
        summary, details = _summarize_error(error)
    elif agent == "code":
        summary, details = _summarize_code(output)
    elif agent == "doc":
        summary, details = _summarize_doc(output)
    elif agent == "jobs":
        summary, details = _summarize_jobs(output)
    elif agent == "biz":
        summary, details = _summarize_biz(output)
    elif agent == "work":
        summary, details = _summarize_work(output)
    elif agent == "classifier" or agent == "interpreter":
        summary, details = _summarize_classifier(output)
    elif agent == "fin":
        summary, details = _summarize_fin(output)
    else:
        summary, details = _summarize_generic(output, status)
    
    # Extract context_id and status from response
    context_id = response.get("context_id", "")
    original_status = response.get("status", "ok")
    
    result: SummaryResponse = {
        "ok": is_ok,
        "status": original_status,  # Pass through original status for UI flow control
        "context_id": context_id,
        "title": title,
        "summary": summary,
        "details": details,
        "raw": response if include_raw else None,
    }
    
    return result


def _summarize_error(error: dict) -> tuple[str, dict]:
    """Summarize error response."""
    err_type = error.get("type", "Error")
    message = error.get("message", "Unknown error")
    
    summary = f"{err_type}: {message}"
    details = {"error_type": err_type, "message": message}
    
    return summary, details


def _summarize_code(output: dict) -> tuple[str, dict]:
    """Summarize CodeAgent response."""
    module_name = output.get("module_name", "")
    paths = output.get("paths", {})
    module_path = paths.get("module", "")
    tests_path = paths.get("tests", "")
    iterations = output.get("iterations_used", 0)
    tests_info = output.get("tests", {})
    tests_status = tests_info.get("status", "unknown")
    tests_summary = tests_info.get("summary", "")
    action = output.get("action", "")
    files_created = output.get("files_created", [])
    notes = output.get("notes", [])
    
    # Build summary lines
    lines = []
    
    if module_name:
        lines.append(f"Module: {module_name}")
    
    if module_path:
        lines.append(f"Path: {module_path}")
    
    if tests_status:
        emoji = "✓" if tests_status == "passed" else "✗"
        lines.append(f"Tests: {emoji} {tests_status}")
        if tests_summary and tests_summary not in ("OK", "FAILED"):
            lines.append(f"  {tests_summary}")
    
    if iterations:
        lines.append(f"Iterations: {iterations}")
    
    summary = "\n".join(lines) if lines else "Code task completed"
    
    details = {
        "module_name": module_name,
        "module_path": module_path,
        "tests_path": tests_path,
        "tests_status": tests_status,
        "iterations": iterations,
        "files_count": len(files_created),
    }
    
    return summary, details


def _summarize_doc(output: dict) -> tuple[str, dict]:
    """Summarize DocAgent response."""
    doc = output.get("document", {})
    doc_id = doc.get("id", "")
    title = doc.get("title", "")
    local_path = doc.get("local_path", "")
    status = doc.get("status", "")
    format_type = doc.get("format", "")
    pages = doc.get("estimated_pages", 0)
    outline = doc.get("outline", [])
    
    lines = []
    
    if title:
        lines.append(f"Doc: {title}")
    
    if doc_id:
        lines.append(f"ID: {doc_id}")
    
    if local_path:
        lines.append(f"Path: {local_path}")
    
    if status:
        lines.append(f"Status: {status}")
    
    if pages:
        lines.append(f"Pages: ~{pages}")
    
    summary = "\n".join(lines) if lines else "Document task completed"
    
    details = {
        "doc_id": doc_id,
        "title": title,
        "path": local_path,
        "status": status,
        "format": format_type,
        "sections": len(outline),
    }
    
    return summary, details


def _summarize_jobs(output: dict) -> tuple[str, dict]:
    """Summarize JobAgent response."""
    results = output.get("results", [])
    query = output.get("query", "")
    
    count = len(results)
    
    lines = []
    lines.append(f"Found: {count} results")
    
    if query:
        lines.append(f"Query: {query}")
    
    # Top 3 titles
    if results:
        lines.append("Top results:")
        for i, job in enumerate(results[:3], 1):
            title = job.get("title", "Untitled")
            company = job.get("company", "")
            if company:
                lines.append(f"  {i}. {title} @ {company}")
            else:
                lines.append(f"  {i}. {title}")
    
    summary = "\n".join(lines)
    
    # Extract top 3 titles for details
    top_titles = [r.get("title", "Untitled") for r in results[:3]]
    
    details = {
        "count": count,
        "query": query,
        "top_titles": top_titles,
    }
    
    return summary, details


def _summarize_biz(output: dict) -> tuple[str, dict]:
    """Summarize BizAgent response."""
    next_actions = output.get("next_actions", [])
    risks = output.get("risks", [])
    summary_text = output.get("summary", "")
    
    lines = []
    
    if summary_text:
        lines.append(summary_text)
    
    action_count = len(next_actions)
    risk_count = len(risks)
    
    lines.append(f"Actions: {action_count} | Risks: {risk_count}")
    
    # Top 3 actions
    if next_actions:
        lines.append("Next actions:")
        for i, action in enumerate(next_actions[:3], 1):
            if isinstance(action, dict):
                # Try to get 'title' or 'action' key
                action_text = action.get("title") or action.get("action") or action.get("description", "")
            else:
                action_text = str(action)
            # Truncate if too long
            if len(action_text) > 50:
                action_text = action_text[:47] + "..."
            lines.append(f"  {i}. {action_text}")
    
    summary = "\n".join(lines)
    
    # Extract top 3 action titles for details
    top_actions = []
    for a in next_actions[:3]:
        if isinstance(a, dict):
            top_actions.append(a.get("title") or a.get("action") or str(a)[:50])
        else:
            top_actions.append(str(a)[:50])
    
    details = {
        "actions_count": action_count,
        "risks_count": risk_count,
        "top_actions": top_actions,
    }
    
    return summary, details


def _summarize_work(output: dict) -> tuple[str, dict]:
    """Summarize WORK query response with Plan info."""
    output_type = output.get("type", "")
    formatted = output.get("formatted", "")
    total = output.get("total", 0)
    filters = output.get("filters", {})
    plan = output.get("plan", {})
    
    # Build summary from formatted output or fallback
    preview = output.get("preview", "") or (plan.get("preview", "") if plan else "")
    candidates = output.get("candidates", [])


    # Bulk WORK_UPDATE proposal
    if output_type == "work_update_bulk_proposal":
        match_count = output.get("match_count", total)
        summary_lines = []
        if preview:
            summary_lines.append(preview)
        summary_lines.append(f"Bulk update: {match_count} tareas")
        summary = "\n".join(summary_lines)
        # Pass through the full payload so the UI can build the live form
        details = {
            "type": output_type,
            "context_id": output.get("context_id", ""),
            "resolved": output.get("resolved", True),
            "match_count": match_count,
            "matches": output.get("matches", []),
            "applied_changes": output.get("applied_changes", {}),
            "options": output.get("options", {}),
            "warning": output.get("warning", ""),
            "preview": preview,
            "requires_confirmation": output.get("requires_confirmation", True),
            "plan": output.get("plan", {}),
        }
        return summary, details

    # Singular WORK_UPDATE proposal (resolved/no_match)
    if output_type == "work_update_proposal":
        resolved = output.get("resolved", False)
        no_match = output.get("reason") == "no_match"
        if resolved:
            summary = preview or "Tarea encontrada y lista para actualizar"
        elif no_match:
            summary = "No se encontraron tareas para actualizar"
        else:
            summary = formatted or preview or "WORK_UPDATE propuesta"
        # Pass through the full payload so the UI can build the live form
        details = {
            "type": output_type,
            "context_id": output.get("context_id", ""),
            "resolved": resolved,
            "no_match": no_match,
            "title": output.get("title", ""),
            "notion_page_id": output.get("notion_page_id", ""),
            "current_values": output.get("current_values", {}),
            "proposed_changes": output.get("proposed_changes", []),
            "options": output.get("options", {}),
            "preview": preview,
            "requires_confirmation": output.get("requires_confirmation", True),
            "plan": output.get("plan", {}),
        }
        return summary, details

    # Default: general WORK case (query results, plan confirmations, etc.)
    if formatted:
        summary = formatted
    elif total > 0:
        summary = f"📋 {total} tarea(s) encontrada(s)"
    else:
        summary = "No se encontraron tareas"

    # Extract key filter info
    filter_info = []
    if filters.get("project"):
        filter_info.append(f"proyecto={filters['project']}")
    if filters.get("status"):
        status_val = filters['status']
        if isinstance(status_val, list):
            filter_info.append(f"status={','.join(status_val)}")
        else:
            filter_info.append(f"status={status_val}")
    if filters.get("title_keyword"):
        filter_info.append(f"keyword={filters['title_keyword']}")

    # Extract plan info
    action = plan.get("action", output_type) if plan else output_type
    preview = plan.get("preview", "") if plan else ""

    # Guarantee details["type"] is always a non-empty string.
    # When output has no "type" key (e.g. raw work_query results from the handler),
    # output_type is "". Fall back to "work_result" so chat_ui can always read it.
    effective_type = output_type or "work_result"

    details = {
        "type": effective_type,
        "total": total,
        "action": action,
        "filters": filter_info,
        "preview": preview,
    }

    return summary, details


def _summarize_classifier(output: dict) -> tuple[str, dict]:
    """Summarize classifier/interpreter response with Plan info."""
    output_type = output.get("type", "")
    domain = output.get("domain", "")
    action = output.get("action", "")
    plan = output.get("plan", {})
    message = output.get("message", "")
    preview = output.get("preview", "") or (plan.get("preview", "") if plan else "")
    
    # Build summary
    if preview:
        summary = preview
    elif message:
        summary = message
    elif plan:
        summary = f"Plan: {plan.get('action', 'UNKNOWN')} - {plan.get('target', '')[:50]}"
    else:
        summary = f"Dominio detectado: {domain}"
    
    details = {
        "type": output_type,
        "domain": domain,
        "action": action or (plan.get("action", "") if plan else ""),
        "preview": preview,
    }
    
    # Include full plan in details for confirmation flows
    # This allows UI to render ConfirmCard with all plan data
    if output_type == "plan_confirmation_required" and plan:
        details["plan"] = plan
    
    return summary, details


def _summarize_fin(output: dict) -> tuple[str, dict]:
    """Summarize FIN expense response."""
    output_type = output.get("type", "")
    message = output.get("message", "")
    expense = output.get("expense", {})
    
    # Build summary
    if message:
        summary = message
    elif expense:
        monto = expense.get("monto", 0)
        categoria = expense.get("categoria", "")
        summary = f"💰 Gasto: ${monto} ({categoria})"
    else:
        summary = "Procesando gasto..."
    
    details = {
        "type": output_type,
        "expense": expense,
    }
    
    return summary, details


def _summarize_generic(output: dict, status: str) -> tuple[str, dict]:
    """Summarize unknown/generic response."""
    summary = f"Task completed with status: {status}"
    
    # Include some basic info from output
    keys = list(output.keys())[:5]
    
    details = {
        "status": status,
        "output_keys": keys,
    }
    
    return summary, details
