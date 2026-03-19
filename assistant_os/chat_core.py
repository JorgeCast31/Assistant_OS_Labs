"""
Chat Core - Layer 1: Deterministic routing and structured response generation.

This module produces ChatCoreResponse objects without any natural language.
It handles:
- pending_flow routing (no re-classification)
- Domain-specific intent routing
- Plan generation from chaperon/classifier output

No LLM calls, no message generation - purely deterministic logic.
"""
from typing import Any, Optional

from .contracts import (
    ChatCoreResponse,
    ChatSession,
    UIAction,
    make_chat_core_response,
    new_context_id,
)
from .classifier import classify_text as classify_text_impl, is_work_query, is_doc_request
from .chaperon import run_chaperon, ActionPlan, SessionContext


# ---------------------------------------------------------------------------
# Pending Flow Registry
# ---------------------------------------------------------------------------

# Maps pending_flow type to resolver function
PENDING_FLOW_RESOLVERS: dict[str, callable] = {}


def register_pending_flow_resolver(flow_type: str):
    """Decorator to register a pending flow resolver."""
    def decorator(fn):
        PENDING_FLOW_RESOLVERS[flow_type] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Default Pending Flow Resolvers
# ---------------------------------------------------------------------------

@register_pending_flow_resolver("fin_confirm")
def _resolve_fin_confirm(
    text: str,
    session: ChatSession,
    pending_data: dict[str, Any],
) -> ChatCoreResponse:
    """Resolve FIN confirmation flow."""
    text_lower = text.lower().strip()
    
    # Check for confirmation keywords
    if text_lower in ("si", "sí", "yes", "ok", "confirmo", "confirmar", "dale"):
        # Confirmed - return execute intent
        return make_chat_core_response(
            domain="FIN",
            intent="execute",
            mode="action",
            needs_confirmation=False,
            plan=pending_data.get("items", []),
            session=ChatSession(
                pending_flow=None,  # Clear pending
                context_id=session.get("context_id", new_context_id()),
            ),
            audit={"resolution": "confirmed"},
        )
    
    if text_lower in ("no", "cancelar", "cancel", "anular"):
        # Cancelled
        return make_chat_core_response(
            domain="FIN",
            intent="cancelled",
            mode="chat",
            needs_confirmation=False,
            session=ChatSession(
                pending_flow=None,  # Clear pending
                context_id=session.get("context_id", new_context_id()),
            ),
            audit={"resolution": "cancelled"},
        )
    
    # Unclear response - ask again
    return make_chat_core_response(
        domain="FIN",
        intent="confirm",
        mode="chat",
        needs_confirmation=True,
        plan=pending_data.get("items", []),
        ui_actions=[UIAction(type="confirm", label="Confirmar")],
        session=ChatSession(
            pending_flow="fin_confirm",
            context_id=session.get("context_id", new_context_id()),
        ),
        audit={"resolution": "unclear", "raw_text": text},
    )


@register_pending_flow_resolver("clarification")
def _resolve_clarification(
    text: str,
    session: ChatSession,
    pending_data: dict[str, Any],
) -> ChatCoreResponse:
    """Resolve clarification flow (missing fields)."""
    field = pending_data.get("field", "")
    original_plan = pending_data.get("plan", [])
    
    # This is a simplified resolver - real implementation would parse
    # the answer and update the plan
    
    # For now, pass through with the new info
    return make_chat_core_response(
        domain=pending_data.get("domain", "FIN"),
        intent="add",
        mode="action",
        needs_confirmation=True,
        plan=original_plan,
        ui_actions=[UIAction(type="confirm", label="Confirmar")],
        session=ChatSession(
            pending_flow="fin_confirm",
            context_id=session.get("context_id", new_context_id()),
        ),
        audit={"clarification_response": text, "field": field},
    )


# ---------------------------------------------------------------------------
# Core Routing Logic
# ---------------------------------------------------------------------------

def process_chat_input(
    text: str,
    session: Optional[ChatSession] = None,
    domain_hint: Optional[str] = None,
) -> ChatCoreResponse:
    """
    Layer 1: Process user input and produce structured response.
    
    If session.pending_flow exists, routes directly to resolver (no re-classify).
    Otherwise classifies and routes normally.
    
    Args:
        text: User input text
        session: Optional session state from previous turn
        domain_hint: Optional domain hint (e.g., from endpoint)
    
    Returns:
        ChatCoreResponse - structured response for Layer 2
    """
    session = session or ChatSession(context_id=new_context_id())
    text = text.strip()
    
    if not text:
        return make_chat_core_response(
            domain="*",
            intent="empty",
            mode="chat",
            session=session,
            audit={"error": "empty_input"},
        )
    
    # --- PENDING FLOW ROUTING (skip re-classification) ---
    pending_flow = session.get("pending_flow")
    if pending_flow:
        resolver = PENDING_FLOW_RESOLVERS.get(pending_flow)
        if resolver:
            pending_data = session.get("pending_data", {})
            return resolver(text, session, pending_data)
        # Unknown pending flow - clear it and continue
        session = ChatSession(
            context_id=session.get("context_id", new_context_id()),
            pending_flow=None,
        )
    
    # --- CLASSIFICATION ---
    # Use classifier to determine domain and intent
    try:
        from .contracts import ClassifyRequest
        classify_request = ClassifyRequest(text=text)
        classify_result = classify_text_impl(classify_request)
        domain = classify_result.get("domain", "UNKNOWN")
        confidence = classify_result.get("confidence", 0.0)
        needs_confirm = classify_result.get("needs_confirmation", False)
    except Exception as e:
        return make_chat_core_response(
            domain="*",
            intent="error",
            mode="chat",
            session=session,
            audit={"error_message": str(e)},
        )
    
    # Override with domain hint if provided
    if domain_hint and domain_hint != "auto":
        domain = domain_hint
    
    # --- INTENT-BASED ROUTING (priority over domain) ---
    
    # WORK_QUERY takes priority: detect task questions regardless of domain
    if is_work_query(text, domain):
        return _process_work_query(text, session, classify_result)
    
    # --- DOMAIN-SPECIFIC ROUTING ---
    
    if domain == "FIN":
        return _process_fin_input(text, session, classify_result)
    
    if domain == "WORK":
        return _process_work_input(text, session, classify_result)
    
    # Generic passthrough for other domains
    return make_chat_core_response(
        domain=domain,
        intent="passthrough",
        mode="chat",
        session=ChatSession(
            context_id=session.get("context_id", new_context_id()),
            last_domain=domain,
        ),
        audit={"raw_text": text, "confidence": confidence},
    )


# ---------------------------------------------------------------------------
# Domain-Specific Processors
# ---------------------------------------------------------------------------

def _process_fin_input(
    text: str,
    session: ChatSession,
    classify_result: dict[str, Any],
) -> ChatCoreResponse:
    """Process FIN domain input through Chaperon."""
    # Build session context for chaperon
    session_context = SessionContext(
        last_domain=session.get("last_domain"),
        last_moneda=None,
        last_fecha=None,
    )
    
    # Run chaperon to parse multi-expense
    try:
        chaperon_response = run_chaperon(text, "FIN", session_context)
        action_plan: ActionPlan = chaperon_response["action_plan"]
    except Exception as e:
        return make_chat_core_response(
            domain="FIN",
            intent="error",
            mode="chat",
            session=session,
            audit={"error_message": str(e)},
        )
    
    items = action_plan.get("items", [])
    requires_confirm = action_plan.get("requires_confirmation", True)
    clarifications = action_plan.get("clarification_questions", [])
    plan_type = action_plan.get("type", "single_fin")
    
    # Convert FinItems to plan dicts
    plan = [dict(item) for item in items]
    
    # Check for missing fields / clarifications
    if clarifications:
        missing_fields = [q["field"] for q in clarifications]
        return make_chat_core_response(
            domain="FIN",
            intent="missing_fields",
            mode="chat",
            needs_confirmation=False,
            missing_fields=missing_fields,
            plan=plan,
            ui_actions=[UIAction(type="form", label="Completar", fields=missing_fields)],
            session=ChatSession(
                pending_flow="clarification",
                context_id=session.get("context_id", new_context_id()),
                pending_data={"domain": "FIN", "plan": plan, "field": missing_fields[0]},
            ),
            audit={"clarifications": clarifications},
        )
    
    # Determine intent based on plan type and item count
    if plan_type == "multi_fin":
        intent = "multi_add"
    elif plan_type == "continuation":
        intent = "add"
    else:
        intent = "add"
    
    # All FIN adds require confirmation (Plan Always)
    if requires_confirm or plan:
        return make_chat_core_response(
            domain="FIN",
            intent="confirm" if len(plan) == 1 else "multi_add",
            mode="chat",
            needs_confirmation=True,
            plan=plan,
            ui_actions=[UIAction(type="confirm", label="Confirmar")],
            session=ChatSession(
                pending_flow="fin_confirm",
                context_id=session.get("context_id", new_context_id()),
                last_domain="FIN",
                pending_data={"items": plan},
            ),
            audit={"summary": action_plan.get("summary_text", "")},
        )
    
    # Passthrough if no items detected
    return make_chat_core_response(
        domain="FIN",
        intent="passthrough",
        mode="chat",
        session=ChatSession(
            context_id=session.get("context_id", new_context_id()),
            last_domain="FIN",
        ),
        audit={"raw_text": text},
    )


def _process_work_query(
    text: str,
    session: ChatSession,
    classify_result: dict[str, Any],
    trace_id: str = "",
) -> ChatCoreResponse:
    """
    Process WORK_QUERY intent - query tasks from Notion.
    
    This is called when is_work_query() returns True, regardless of domain.
    Routes to Notion query with default filters.
    """
    from .integrations.notion import query_work_db, check_notion_available
    from .classifier import parse_work_query_filters
    
    # Parse filters from natural language
    filters = parse_work_query_filters(text)
    
    # Add default status filter if not specified
    if not filters.get("status"):
        filters["status"] = ["INBOX", "NEXT", "WAITING", "SCHEDULED"]
    
    # Check Notion availability
    if not check_notion_available():
        return make_chat_core_response(
            domain="WORK",
            intent="query_error",
            mode="answer",
            session=ChatSession(
                context_id=session.get("context_id", new_context_id()),
                last_domain="WORK",
            ),
            audit={
                "raw_text": text,
                "routing_reason": "is_work_query=True, notion_unavailable",
                "error": "Notion not available",
            },
        )
    
    # Query Notion
    try:
        result = query_work_db(filters=filters, limit=10)
        
        if not result.get("ok", False):
            return make_chat_core_response(
                domain="WORK",
                intent="query_error",
                mode="answer",
                session=ChatSession(
                    context_id=session.get("context_id", new_context_id()),
                    last_domain="WORK",
                ),
                audit={
                    "raw_text": text,
                    "routing_reason": "is_work_query=True, query_failed",
                    "error": result.get("error", "Query failed"),
                    "filters": filters,
                },
            )
        
        items = result.get("items", [])
        
        return make_chat_core_response(
            domain="WORK",
            intent="query",
            mode="answer",
            plan=items,
            session=ChatSession(
                context_id=session.get("context_id", new_context_id()),
                last_domain="WORK",
            ),
            audit={
                "raw_text": text,
                "routing_reason": "is_work_query=True",
                "filters": filters,
                "count": len(items),
            },
        )
    except Exception as e:
        return make_chat_core_response(
            domain="WORK",
            intent="query_error",
            mode="answer",
            session=ChatSession(
                context_id=session.get("context_id", new_context_id()),
                last_domain="WORK",
            ),
            audit={
                "raw_text": text,
                "routing_reason": "is_work_query=True, exception",
                "error": str(e),
            },
        )


def _process_work_input(
    text: str,
    session: ChatSession,
    classify_result: dict[str, Any],
) -> ChatCoreResponse:
    """Process WORK domain input."""
    # Determine if this is a query or add
    text_lower = text.lower()
    
    # Query patterns
    query_patterns = [
        "qué tengo", "que tengo",
        "tareas", "pendientes",
        "mostrar", "listar",
        "cuántas", "cuantas",
        "estado de",
    ]
    
    is_query = any(p in text_lower for p in query_patterns)
    
    if is_query:
        return make_chat_core_response(
            domain="WORK",
            intent="query",
            mode="action",
            session=ChatSession(
                context_id=session.get("context_id", new_context_id()),
                last_domain="WORK",
            ),
            audit={"raw_text": text},
        )
    
    # Default to add/create intent
    return make_chat_core_response(
        domain="WORK",
        intent="add",
        mode="chat",
        needs_confirmation=True,
        plan=[{"title": text, "status": "pending"}],
        ui_actions=[UIAction(type="confirm", label="Crear tarea")],
        session=ChatSession(
            pending_flow="work_confirm",
            context_id=session.get("context_id", new_context_id()),
            last_domain="WORK",
        ),
        audit={"raw_text": text},
    )


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "process_chat_input",
    "register_pending_flow_resolver",
    "PENDING_FLOW_RESOLVERS",
]
