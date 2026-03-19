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
    ("FIN", "add"): "Registrando gasto: {summary}",
    ("FIN", "confirm"): "¿Confirmas este gasto?\n{plan_summary}",
    ("FIN", "multi_add"): "Detecté {count} gastos:\n{plan_summary}\n¿Confirmo todos?",
    ("FIN", "missing_fields"): "Faltan datos: {missing}. Por favor completa.",
    ("FIN", "query"): "Consultando gastos...",
    ("FIN", "committed"): "Gasto registrado.",
    
    # WORK domain
    ("WORK", "query"): "Tengo {count} tarea(s):\n{items_summary}",
    ("WORK", "query_error"): "No pude consultar las tareas: {error_message}",
    ("WORK", "query_result"): "Encontré {count} tarea(s):\n{items_summary}",
    ("WORK", "add"): "Creando tarea: {summary}",
    ("WORK", "confirm"): "¿Confirmas esta acción?\n{plan_summary}",
    
    # Generic fallbacks
    ("*", "query"): "Consultando {domain_name}...",
    ("*", "add"): "Agregando a {domain_name}: {summary}",
    ("*", "confirm"): "¿Confirmas?\n{plan_summary}",
    ("*", "passthrough"): "{raw_text}",
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
            lines.append(f"  - {symbol}{monto:.2f} - {desc}")
        # Handle WORK items
        elif "title" in item:
            title = item.get("title", "")
            status = item.get("status", "")
            lines.append(f"  - {title}" + (f" [{status}]" if status else ""))
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
        "raw_text": audit.get("raw_text", ""),
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
