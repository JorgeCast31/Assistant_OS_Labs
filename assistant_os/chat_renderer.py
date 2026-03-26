"""
Chat Renderer - Layer 2: Converts structured ChatCoreResponse to user messages.

This module ONLY transforms Layer 1 output into display text.
It must NOT:
- Modify numbers, dates, counts, IDs, options, or actions
- Make decisions or inferences
- Call external services

It MUST:
- Use templates for all message generation
- Pass through ui_actions and context_id unchanged
- Be purely transformational
"""
from typing import Any

from .contracts import ChatCoreResponse, UIAction, ChatSession


# ---------------------------------------------------------------------------
# Response for UI
# ---------------------------------------------------------------------------

class RenderedResponse:
    """Output from chat renderer for UI consumption."""
    
    __slots__ = ("message", "ui_actions", "context_id")
    
    def __init__(
        self,
        message: str,
        ui_actions: list[UIAction],
        context_id: str,
    ):
        self.message = message
        self.ui_actions = ui_actions
        self.context_id = context_id
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "ui_actions": list(self.ui_actions),
            "context_id": self.context_id,
        }


# ---------------------------------------------------------------------------
# Template Registry
# ---------------------------------------------------------------------------

# Domain display names
DOMAIN_NAMES = {
    "WORK": "Trabajo",
    "FIN": "Finanzas",
    "CODE": "Código",
    "PRO_DIAG": "Proyecto Diagnóstico",
    "REL": "Relaciones",
    "HEALTH": "Salud",
    "EIPROTA": "Creativo/Filosófico",
    "ENERGY": "Energía/Foco",
}

# Intent templates by (domain, intent) or just intent
INTENT_TEMPLATES: dict[tuple[str, str] | str, str] = {
    # Generic intents
    ("*", "pending_flow"): "Tienes un flujo pendiente. Responde la pregunta anterior antes de continuar.",
    ("*", "error"): "Error: {error_message}",
    ("*", "empty"): "No entendí tu mensaje. ¿Puedes reformularlo?",
    
    # FIN domain
    ("FIN", "add"):           "Registrando gasto: {summary}",
    ("FIN", "confirm"):       "¿Confirmas este gasto?\n{plan_summary}",
    ("FIN", "multi_add"):     "Detecté {count} gastos:\n{plan_summary}\n¿Confirmo todos?",
    ("FIN", "missing_fields"):"Faltan datos: {missing}. Por favor completa.",
    ("FIN", "query"):         "Consultando gastos...",
    # M13: real execution feedback
    ("FIN", "committed"):     "✓ {committed_summary}",
    ("FIN", "execute"):       "Gasto confirmado. Procesando registro...",
    ("FIN", "cancelled"):     "Acción cancelada.",

    # WORK domain
    ("WORK", "query"):        "Tengo {count} tarea(s):\n{items_summary}",
    ("WORK", "query_error"):  "No pude consultar las tareas: {error_message}",
    ("WORK", "query_result"): "Encontré {count} tarea(s):\n{items_summary}",
    ("WORK", "add"):              "Creando tarea: {summary}",
    ("WORK", "delete"):           "¿Eliminar tarea?\n{plan_summary}",
    ("WORK", "update"):           "¿Actualizar tarea?\n{plan_summary}",
    ("WORK", "confirm"):          "¿Confirmas esta acción?\n{plan_summary}",
    # M13: real execution feedback
    ("WORK", "created"):          "✓ Tarea creada: {summary}",
    ("WORK", "deleted"):          "✓ {deleted_count} tarea(s) eliminada(s).",
    ("WORK", "not_found"):        "No se encontraron tareas que coincidan con los criterios.",
    ("WORK", "delete_confirmed"): "✓ Tarea marcada para eliminar: {summary}",
    ("WORK", "update_confirmed"): "✓ Tarea marcada para actualizar: {summary}",
    ("WORK", "partial"):          "Algunas tareas procesadas ({success_count}/{total}).",
    ("WORK", "cancelled"):        "Operación WORK cancelada.",
    ("WORK", "execute"):          "Tarea recibida para ejecución.",

    # CODE domain (M27/M28)
    ("CODE", "needs_context"): "Operación CODE: {operation_label}{files_line}\n\nNecesito el path del repositorio para acceder al archivo.",
    ("CODE", "preview"):       "{operation_label}{files_line}\n\nPlan de cambios:{plan_summary_nl}\n¿Confirmás para planificar?",
    # M28: real Claude responses
    ("CODE", "responded"):     "{analysis}",
    ("CODE", "proposed"):      "Propuesta {operation_label}{files_line}\n\nResumen: {summary}\nRiesgo: {risk_label}\nArchivos: {affected_files_line}\n{caller_risk_block}{patch_block}",
    # Fallback when executor unavailable
    ("CODE", "explain"):       "Explicación solicitada.{files_line}\n\n⚠ Executor no disponible. Pega el código o señalá la sección a explicar.",
    ("CODE", "review"):        "Revisión solicitada.{files_line}\n\n⚠ Executor no disponible. Pega el código para revisar.",
    ("CODE", "query"):         "Solicitud CODE recibida: {raw_text}",
    ("CODE", "queued"):        "Tarea CODE registrada.\n  Op: {operation_label}\n  Repo: {repo_path_display}\n  Branch: {base_branch_display}",
    ("CODE", "cancelled"):     "Operación CODE cancelada.",
    # M29: structured error + index intents
    ("CODE", "file_too_large"):
        "El archivo {file_too_large_name} es demasiado grande para analizar de una vez "
        "({file_size_display} / limite {file_limit_display}).\n\n"
        "{top_symbols_hint}"
        "Opciones:\n"
        "  - Indica una funcion o clase especifica: \"explica {first_symbol} en ...\"\n"
        "  - Especifica un fragmento: \"revisa las lineas 1-100 de ...\"\n"
        "  - Pide un indice del archivo: \"lista las funciones de ...\"",
    ("CODE", "file_not_found"):
        "No se encontro el archivo {missing_file} en el repositorio.\n\n"
        "Verifica que:\n"
        "  - El nombre del archivo sea correcto\n"
        "  - El archivo exista dentro de repo_path\n"
        "  - La ruta sea relativa al root del repo",
    ("CODE", "executor_error"):
        "No se pudo procesar la solicitud CODE.{files_line}\n\n{error_message}",
    # M29: structural index
    ("CODE", "file_index"):
        "Indice de {index_file} ({total_lines} lineas)\n\n{index_content}",

    # Generic fallbacks
    ("*", "query"):            "Consultando {domain_name}...",
    ("*", "add"):              "Agregando a {domain_name}: {summary}",
    ("*", "confirm"):          "¿Confirmas?\n{plan_summary}",
    ("*", "passthrough"):      "{raw_text}",
    # M12/M13: generic action intents
    ("*", "cancelled"):        "Acción cancelada.",
    ("*", "execute_requested"):"Solicitud de ejecución recibida.",
    ("*", "error"):            "Error: {error_message}",
    # M14: dedup + partial failure
    ("*", "already_executed"): "Esta acción ya fue procesada recientemente.",
    ("FIN", "partial"):        "⚠ Registro parcial: {committed_summary}",
    ("WORK", "partial"):       "⚠ Creación parcial: {committed_summary}",
    ("*", "partial"):          "⚠ Ejecución parcial: {count} completado(s).",
}


# ---------------------------------------------------------------------------
# Template Helpers
# ---------------------------------------------------------------------------

def _get_template(domain: str, intent: str) -> str:
    """Get template for domain+intent, falling back to wildcards."""
    # Try exact match
    key = (domain, intent)
    if key in INTENT_TEMPLATES:
        return INTENT_TEMPLATES[key]
    
    # Try wildcard domain
    wildcard_key = ("*", intent)
    if wildcard_key in INTENT_TEMPLATES:
        return INTENT_TEMPLATES[wildcard_key]
    
    # Fallback
    return "Procesando solicitud en {domain_name}..."


def _format_plan_summary(plan: list[dict[str, Any]]) -> str:
    """Format plan items as bullet list."""
    if not plan:
        return "(sin items)"
    
    lines = []
    for item in plan:
        # Handle FinItem-like objects
        if "monto" in item:
            monto = item.get("monto", 0)
            moneda = item.get("moneda", "USD")
            desc = item.get("descripcion") or item.get("categoria") or "gasto"
            symbol = "$" if moneda == "USD" else "B/."
            responsable = item.get("responsable") or ""
            fecha = item.get("fecha") or ""
            categoria = item.get("categoria") or ""
            metodo = item.get("metodo_pago") or ""
            itbms_val = item.get("itbms", False)
            itbms_str = "Sí" if (itbms_val is True or str(itbms_val).lower() in ("true", "si", "sí", "yes", "1")) else "No"
            # Main line
            lines.append(f"  - {symbol}{monto:.2f} {desc}")
            # Detail line — show all populated fields
            detail_parts = []
            if responsable:
                detail_parts.append(f"Responsable: {responsable}")
            if fecha:
                detail_parts.append(f"Fecha: {fecha}")
            if categoria:
                detail_parts.append(f"Cat: {categoria}")
            detail_parts.append(f"ITBMS: {itbms_str}")
            if metodo:
                detail_parts.append(f"Pago: {metodo}")
            lines.append(f"    {' | '.join(detail_parts)}")
        # Handle WORK items
        elif "title" in item:
            title = item.get("title", "")
            status = item.get("status", "")
            lines.append(f"  - {title}" + (f" [{status}]" if status else ""))
        # Handle CODE plan steps (M23)
        elif "step" in item and "description" in item:
            step = item.get("step", "")
            desc = item.get("description", "")
            lines.append(f"  {step}. {desc}")
        # Generic fallback
        else:
            lines.append(f"  - {item}")
    
    return "\n".join(lines)


def _format_items_summary(plan: list[dict[str, Any]]) -> str:
    """Format items for query results (more compact)."""
    if not plan:
        return "(ninguno)"
    
    lines = []
    for i, item in enumerate(plan[:10], 1):  # Limit to 10
        if "title" in item:
            title = item.get("title", "")
            lines.append(f"{i}. {title}")
        elif "nombre" in item:
            lines.append(f"{i}. {item['nombre']}")
        else:
            lines.append(f"{i}. {item}")
    
    if len(plan) > 10:
        lines.append(f"   ... y {len(plan) - 10} más")
    
    return "\n".join(lines)


def _format_committed_summary(
    plan: list[dict[str, Any]],
    audit: dict[str, Any],
) -> str:
    """
    Human-readable summary for executed (committed) responses.

    Shows per-item result for FIN, or task title for WORK.
    """
    if not plan:
        return "operación completada"

    lines = []
    for item in plan:
        if "monto" in item:
            moneda = item.get("moneda", "USD")
            symbol = "$" if moneda == "USD" else "B/."
            desc   = item.get("descripcion") or item.get("categoria") or "gasto"
            row    = item.get("row_number")
            row_str = f" (fila {row})" if row else ""
            lines.append(f"{symbol}{float(item['monto']):.2f} {desc}{row_str}")
        elif "title" in item:
            lines.append(item["title"])
        else:
            lines.append(str(item))

    if len(lines) == 1:
        return lines[0]

    return f"{len(lines)} item(s) registrados:\n" + "\n".join(f"  - {l}" for l in lines)


def _format_missing_fields(fields: list[str]) -> str:
    """Format missing fields as readable list."""
    field_names = {
        "monto": "monto",
        "categoria": "categoría",
        "responsable": "responsable",
        "fecha": "fecha",
        "descripcion": "descripción",
    }
    return ", ".join(field_names.get(f, f) for f in fields)


# ---------------------------------------------------------------------------
# CODE-specific format helpers (M27)
# ---------------------------------------------------------------------------

_CODE_OP_LABELS: dict[str, str] = {
    "CODE_FIX":    "Corregir código",
    "CODE_CREATE": "Implementar nuevo código",
    "CODE_REVIEW": "Revisar código",
    "CODE_EXPLAIN":"Explicar código",
}


def _format_code_operation_label(operation: str) -> str:
    return _CODE_OP_LABELS.get(operation, operation or "Operación CODE")


def _format_files_line(files: list[str]) -> str:
    """Return ' — file1.py, file2.ts' or empty string when no files detected."""
    if not files:
        return ""
    return " — " + ", ".join(files)


def _format_code_plan_steps(plan: list[dict[str, Any]]) -> str:
    """Format CODE step items as a numbered inline list."""
    if not plan:
        return ""
    lines = []
    for item in plan:
        if "step" in item and "description" in item:
            lines.append(f"\n  {item['step']}. {item['description']}")
        else:
            lines.append(f"\n  - {item}")
    return "".join(lines)


_RISK_LABELS: dict[str, str] = {
    "low":    "Bajo",
    "medium": "Medio",
    "high":   "Alto",
}


def _format_risk_label(risk: str) -> str:
    return _RISK_LABELS.get(str(risk).lower(), risk or "Medio")


def _format_bytes(n: int) -> str:
    """Human-readable byte count: '45,678 bytes' or '44.6 KB'."""
    if n <= 0:
        return "?"
    if n < 1024:
        return f"{n:,} bytes"
    return f"{n / 1024:.1f} KB"


def _format_symbol_index(symbols: list[dict]) -> str:
    """Format a list of {kind, name, line} dicts as a readable index."""
    if not symbols:
        return "(no se encontraron simbolos en el archivo)"
    lines = []
    current_kind = None
    for s in symbols:
        kind = s.get("kind", "symbol")
        name = s.get("name", "?")
        line = s.get("line", 0)
        if kind != current_kind:
            header = {
                "class":      "Clases:",
                "function":   "Funciones:",
                "method":     "Metodos:",
                "const/arrow":"Constantes/Arrow functions:",
            }.get(kind, f"{kind.title()}:")
            lines.append(f"\n{header}")
            current_kind = kind
        lines.append(f"  {name}  (linea {line})")
    return "\n".join(lines).strip()


def _format_top_symbols_hint(symbols: list[str]) -> str:
    """Format top symbol names as a hint line for file_too_large responses."""
    if not symbols:
        return ""
    quoted = ", ".join(f"`{s}`" for s in symbols[:5])
    return f"Simbolos encontrados: {quoted}\n\n"


def _format_patch_block(patch: str) -> str:
    """Wrap a non-empty patch preview in a diff code fence for the UI."""
    if not patch or patch.strip() in ("(preview not available)", ""):
        return ""
    lines = patch.strip().split("\n")
    snippet = "\n".join(lines[:30])
    tail = f"\n... (+{len(lines) - 30} líneas más)" if len(lines) > 30 else ""
    return f"\n```diff\n{snippet}{tail}\n```"


def _format_caller_risk_block(
    caller_risk: str,
    caller_risk_notes: str,
    contract_assumptions: str,
) -> str:
    """
    M30: Format contract / caller-risk section for CODE proposed responses.

    Returns empty string when caller_risk is "safe" and there is nothing
    notable to surface.  For review_required and breaking, returns a labelled
    block so the developer can make an informed decision before applying.
    """
    risk = (caller_risk or "").lower().strip()
    if risk == "safe" and not contract_assumptions:
        return ""

    lines: list[str] = []

    if contract_assumptions:
        lines.append(f"Contrato actual: {contract_assumptions}")

    if risk == "breaking":
        lines.append("Compatibilidad: ROMPE callers — revisar obligatoriamente antes de aplicar")
    elif risk == "review_required":
        lines.append("Compatibilidad: Requiere revision de callers antes de aplicar")
    # "safe" with a contract_assumptions note is already covered above

    if caller_risk_notes and risk in ("breaking", "review_required"):
        lines.append(f"Detalle: {caller_risk_notes}")

    return "\n".join(lines) + "\n" if lines else ""


# ---------------------------------------------------------------------------
# Main Renderer
# ---------------------------------------------------------------------------

def render_chat_response(core: ChatCoreResponse) -> RenderedResponse:
    """
    Layer 2: Transform structured ChatCoreResponse into user-facing message.
    
    This function is purely transformational. It does not:
    - Modify any numbers, dates, IDs, or options
    - Make logical decisions
    - Call external services
    
    Args:
        core: Layer 1 structured response
    
    Returns:
        RenderedResponse with message text, ui_actions, and context_id
    """
    domain = core["domain"]
    intent = core["intent"]
    plan = core.get("plan", [])
    session = core.get("session", {})
    audit = core.get("audit", {})
    missing = core.get("missing_fields", [])
    
    # Get template
    template = _get_template(domain, intent)
    
    # Build substitution context
    context = {
        "domain": domain,
        "domain_name": DOMAIN_NAMES.get(domain, domain),
        "intent": intent,
        "count": len(plan),
        "plan_summary": _format_plan_summary(plan),
        "items_summary": _format_items_summary(plan),
        "missing": _format_missing_fields(missing),
        "summary": audit.get("summary", ""),
        "error_message": audit.get("error_message") or audit.get("error", "Error desconocido"),
        "raw_text": audit.get("raw_text", audit.get("task_preview", "")),
        # M13: execution result summary for committed/created intents
        "committed_summary": _format_committed_summary(plan, audit),
        # M23: CODE domain operation label
        "operation": audit.get("operation", ""),
        # M26-B: delete/create execution counts
        "deleted_count": audit.get("deleted_count", 0),
        "success_count": audit.get("success_count", 0),
        "total": audit.get("success_count", 0) + audit.get("error_count", 0),
        # M27: CODE-specific context vars
        "operation_label": _format_code_operation_label(audit.get("operation", "")),
        "files_line": _format_files_line(audit.get("files", [])),
        "plan_summary_nl": _format_code_plan_steps(plan),
        "repo_path_display": audit.get("repo_path") or "(no especificado)",
        "base_branch_display": audit.get("base_branch") or "main",
        # M28: real Claude response vars
        "analysis": audit.get("analysis", ""),
        "summary": audit.get("summary", ""),
        "affected_files_line": ", ".join(audit.get("affected_files", [])) or "(por determinar)",
        "risk_label": _format_risk_label(audit.get("risk_level", "")),
        "patch_block": _format_patch_block(audit.get("patch_preview", "")),
        # M30: contract / caller-risk vars
        "caller_risk_block": _format_caller_risk_block(
            audit.get("caller_risk", ""),
            audit.get("caller_risk_notes", ""),
            audit.get("contract_assumptions", ""),
        ),
        # M29 hardening: error intent vars
        "file_too_large_name": audit.get("file_too_large_name", "archivo"),
        "file_size_display": _format_bytes(audit.get("file_too_large_size", 0)),
        "file_limit_display": _format_bytes(audit.get("file_too_large_limit", 0)),
        "missing_file": audit.get("missing_file", "archivo"),
        # M29: file_too_large symbol hints
        "top_symbols_hint": _format_top_symbols_hint(audit.get("top_symbols", [])),
        "first_symbol": (audit.get("top_symbols") or ["_function_name"])[0],
        # M29: file_index vars
        "index_file": audit.get("index_file", "archivo"),
        "total_lines": str(audit.get("total_lines", "?")),
        "index_content": _format_symbol_index(audit.get("index_symbols", [])),
    }

    # Single item summary
    if plan and len(plan) == 1:
        item = plan[0]
        if "monto" in item:
            moneda = item.get("moneda", "USD")
            symbol = "$" if moneda == "USD" else "B/."
            desc = item.get("descripcion") or item.get("categoria") or "gasto"
            context["summary"] = f"{symbol}{item['monto']:.2f} - {desc}"
        elif "title" in item:
            context["summary"] = item.get("title", "")
    
    # Format message
    try:
        message = template.format(**context)
    except KeyError:
        # Fallback if template vars missing
        message = f"[{domain}] {intent}: {len(plan)} item(s)"
    
    # Pass through ui_actions and context_id unchanged
    ui_actions = core.get("ui_actions", [])
    context_id = session.get("context_id", "")
    
    return RenderedResponse(
        message=message,
        ui_actions=ui_actions,
        context_id=context_id,
    )


# ---------------------------------------------------------------------------
# Convenience exports
# ---------------------------------------------------------------------------

__all__ = [
    "RenderedResponse",
    "render_chat_response",
    "DOMAIN_NAMES",
    "INTENT_TEMPLATES",
]
