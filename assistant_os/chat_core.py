"""
Chat Core - Layer 1: Deterministic routing and structured response generation.

This module produces ChatCoreResponse objects without any natural language.
It handles:
- pending_flow routing (no re-classification)
- Domain-specific intent routing
- Plan generation from chaperon/classifier output

No LLM calls, no message generation - purely deterministic logic.
"""
import hashlib
import logging
import re
import time
from typing import Any, Optional

_log = logging.getLogger(__name__)

from .contracts import (
    ChatCoreResponse,
    ChatSession,
    ChatAction,
    UIAction,
    make_chat_core_response,
    new_context_id,
    # CODE domain operation constants (M23)
    OP_CODE_EXPLAIN, OP_CODE_REVIEW, OP_CODE_FIX, OP_CODE_CREATE,
    # WORK domain operation constants (M26-B)
    OP_WORK_CREATE, OP_WORK_UPDATE, OP_WORK_DELETE,
)

# Operations that are mutations — must NOT be intercepted by is_work_query (M26-B)
_WORK_MUTATION_OPS: frozenset[str] = frozenset({
    OP_WORK_CREATE, OP_WORK_UPDATE, OP_WORK_DELETE,
})
from .classifier import classify_text as classify_text_impl, is_work_query, is_doc_request
from .chaperon import run_chaperon, ActionPlan, SessionContext


# ---------------------------------------------------------------------------
# Structured Action Contract (M12)
# ---------------------------------------------------------------------------

# Action types the backend handles explicitly.
# All others fall back to text-based processing.
STRUCTURED_ACTION_TYPES: frozenset[str] = frozenset({
    "confirm",
    "cancel",
    "select",
    "form_submit",
    "plan_item_execute",
})


# ---------------------------------------------------------------------------
# Execution Deduplication (M14)
# ---------------------------------------------------------------------------

_EXEC_DEDUP: dict[str, float] = {}  # key → monotonic timestamp
_DEDUP_TTL: int = 30  # seconds — window to consider a duplicate


def _dedup_key(
    context_id: str,
    action_type: str,
    action_id: Optional[str],
    payload: dict,
) -> str:
    """Generate a stable 16-char dedup key for an execution request."""
    try:
        payload_repr = repr(sorted(payload.items()))
    except Exception:
        payload_repr = repr(payload)
    raw = f"{context_id}|{action_type}|{action_id}|{payload_repr}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _check_and_mark_execution(key: str) -> bool:
    """
    Return True if this key was already executed within the dedup TTL.
    Otherwise mark the key as executed and return False.
    Cleans up expired entries on each call.
    """
    now = time.monotonic()
    # Prune expired entries
    expired = [k for k, ts in _EXEC_DEDUP.items() if now - ts > _DEDUP_TTL]
    for k in expired:
        del _EXEC_DEDUP[k]

    if key in _EXEC_DEDUP:
        return True  # duplicate — already executed

    _EXEC_DEDUP[key] = now
    return False


def parse_action(raw: Any) -> tuple[Optional[dict], Optional[str]]:
    """
    Validate and normalise a raw action dict from the frontend.

    Returns (parsed_dict, error_message).
    - On success: (dict, None)
    - On malformed input: (None, error_string)
    - On absent input (None): (None, None)  ← not an error

    Callers check error_message first; if it is set, the action is invalid
    and the request should be rejected or degraded gracefully.
    """
    if raw is None:
        return None, None  # Absent action — not an error, falls to text flow

    if not isinstance(raw, dict):
        return None, "action must be a JSON object"

    action_type = raw.get("type")
    if not isinstance(action_type, str) or not action_type.strip():
        return None, "action.type must be a non-empty string"

    payload = raw.get("payload")
    return {
        "type": action_type.strip().lower(),
        "target": raw.get("target"),   # Optional trace_id for correlation
        "id": raw.get("id"),            # Optional item id (plan_item_execute)
        "payload": payload if isinstance(payload, dict) else {},
    }, None


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
    """
    Resolve FIN confirmation flow.

    M13: On confirmation, executes the actual Sheets write for every pending
    item.  Returns intent='committed' on success, intent='error' on failure.
    Backward-compatible: text-based 'sí/confirmar' still works as before.
    """
    text_lower = text.lower().strip()
    context_id = session.get("context_id", new_context_id())
    items: list[dict] = list(pending_data.get("items", []))

    if text_lower in ("si", "sí", "yes", "ok", "confirmo", "confirmar", "dale"):
        if not items:
            return make_chat_core_response(
                domain="FIN",
                intent="error",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id),
                audit={"error_message": "No hay gastos pendientes para registrar"},
            )

        # Confirmation resolves the conversational decision.
        # The actual Sheets write is a downstream side-effect — infrastructure
        # availability must not corrupt the semantic intent of the confirmation.
        return make_chat_core_response(
            domain="FIN",
            intent="execute",
            mode="action",
            needs_confirmation=False,
            plan=items,
            session=ChatSession(
                pending_flow=None,
                context_id=context_id,
                last_domain="FIN",
            ),
            audit={
                "resolution": "confirmed",
                "via": "text_confirm",
            },
        )

    if text_lower in ("no", "cancelar", "cancel", "anular"):
        return make_chat_core_response(
            domain="FIN",
            intent="cancelled",
            mode="chat",
            needs_confirmation=False,
            session=ChatSession(
                pending_flow=None,
                context_id=context_id,
                last_domain="FIN",
            ),
            audit={"resolution": "cancelled"},
        )

    # Unclear response — ask again
    return make_chat_core_response(
        domain="FIN",
        intent="confirm",
        mode="chat",
        needs_confirmation=True,
        plan=items,
        ui_actions=[UIAction(type="confirm", label="Confirmar")],
        session=ChatSession(
            pending_flow="fin_confirm",
            context_id=context_id,
            pending_data={"items": items},
        ),
        audit={"resolution": "unclear", "raw_text": text},
    )


@register_pending_flow_resolver("clarification")
def _resolve_clarification(
    text: str,
    session: ChatSession,
    pending_data: dict[str, Any],
) -> ChatCoreResponse:
    """
    Resolve clarification flow (missing fields).

    M13: Merges structured form_payload (from form_submit action) into plan
    items so the values are actually applied before moving to fin_confirm.
    Also handles text-based single-field answers for backward compat.
    """
    field = pending_data.get("field", "")
    original_plan: list[dict] = [dict(i) for i in pending_data.get("plan", [])]
    form_payload: dict = pending_data.get("form_payload", {})
    context_id = session.get("context_id", new_context_id())

    # --- M13: Apply structured form values to plan items ---
    if form_payload and original_plan:
        for item in original_plan:
            for k, v in form_payload.items():
                if v is None or v == "":
                    continue
                # Coerce monto to float
                if k == "monto":
                    try:
                        item[k] = float(v)
                    except (ValueError, TypeError):
                        pass
                # Coerce itbms to bool (M27: form sends "sí"/"no"/"true"/"false")
                elif k == "itbms":
                    item[k] = str(v).lower() in ("true", "si", "sí", "yes", "1")
                else:
                    item[k] = v
    elif text and field and original_plan:
        # Text-based single-field answer (backward compat)
        for item in original_plan:
            if field == "monto":
                try:
                    item[field] = float(text.strip())
                except (ValueError, TypeError):
                    item[field] = text.strip()
            else:
                item[field] = text.strip()

    domain = pending_data.get("domain", "FIN")
    next_flow = "work_confirm" if domain == "WORK" else "fin_confirm"
    confirm_label = "Crear tarea" if domain == "WORK" else "Confirmar"
    intent = "confirm" if len(original_plan) == 1 else "multi_add"

    return make_chat_core_response(
        domain=domain,
        intent=intent,
        mode="chat",
        needs_confirmation=True,
        plan=original_plan,
        ui_actions=[UIAction(type="confirm", label=confirm_label)],
        session=ChatSession(
            pending_flow=next_flow,
            context_id=context_id,
            last_domain=domain,
            pending_data={"items": original_plan},
        ),
        audit={
            "clarification_response": text,
            "field": field,
            "form_payload": form_payload,
            "merged": bool(form_payload or (text and field)),
        },
    )


@register_pending_flow_resolver("work_confirm")
def _resolve_work_confirm(
    text: str,
    session: ChatSession,
    pending_data: dict[str, Any],
) -> ChatCoreResponse:
    """
    Resolve WORK confirmation flow (M13 / M26-B).

    Routes by pending_data["operation"] so create/delete/update each get the
    right execution path.  Handles text keywords + UI button fallback.
    """
    text_lower = text.lower().strip()
    context_id = session.get("context_id", new_context_id())
    items: list[dict] = list(pending_data.get("items", []))
    operation = pending_data.get("operation", "create")  # default: create

    # ── Cancel ────────────────────────────────────────────────────────────
    if text_lower in ("no", "cancelar", "cancel", "anular"):
        return make_chat_core_response(
            domain="WORK",
            intent="cancelled",
            mode="chat",
            session=ChatSession(
                pending_flow=None,
                context_id=context_id,
                last_domain="WORK",
            ),
            audit={"resolution": "cancelled"},
        )

    # ── Confirm ───────────────────────────────────────────────────────────
    if text_lower in ("si", "sí", "yes", "ok", "confirmo", "confirmar", "dale"):
        if not items:
            return make_chat_core_response(
                domain="WORK",
                intent="error",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id),
                audit={"error_message": "No hay tareas pendientes"},
            )

        # DELETE — execute immediately via Notion archive
        if operation == "delete":
            keywords = pending_data.get("keywords", [])
            delete_all = pending_data.get("delete_all", False)
            ok, message, meta = _execute_work_delete(keywords, delete_all)
            deleted = meta.get("deleted_count", 0)
            intent = "deleted" if (ok and deleted > 0) else ("not_found" if ok else "error")
            return make_chat_core_response(
                domain="WORK",
                intent=intent,
                mode="action",
                needs_confirmation=False,
                plan=items,
                session=ChatSession(
                    pending_flow=None,
                    context_id=context_id,
                    last_domain="WORK",
                ),
                audit={
                    "resolution": "confirmed",
                    "operation": "delete",
                    "message": message,
                    **meta,
                    "via": "text_confirm",
                },
            )

        # UPDATE — still deferred; pipeline handles it
        if operation == "update":
            return make_chat_core_response(
                domain="WORK",
                intent="update_confirmed",
                mode="action",
                needs_confirmation=False,
                plan=items,
                session=ChatSession(
                    pending_flow=None,
                    context_id=context_id,
                    last_domain="WORK",
                ),
                audit={
                    "resolution": "confirmed",
                    "operation": "update",
                    "items": items,
                    "via": "text_confirm",
                },
            )

        # CREATE — execute immediately
        succeeded: list[dict] = []
        failed: list[dict] = []
        for item in items:
            ok, message, meta = _execute_work_item(item)
            if ok:
                succeeded.append({**item, **meta})
            else:
                failed.append({"item": item, "error": message})

        if failed and not succeeded:
            return make_chat_core_response(
                domain="WORK",
                intent="error",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id),
                audit={
                    "resolution": "confirmed",
                    "execution_result": "error",
                    "error_message": failed[0]["error"],
                    "error_count": len(failed),
                    "items_failed": failed,
                    "via": "text_confirm",
                },
            )

        return make_chat_core_response(
            domain="WORK",
            intent="created" if not failed else "partial",
            mode="action",
            needs_confirmation=False,
            plan=succeeded,
            session=ChatSession(
                pending_flow=None,
                context_id=context_id,
                last_domain="WORK",
            ),
            audit={
                "resolution": "confirmed",
                "execution_result": "success" if not failed else "partial",
                "success_count": len(succeeded),
                "error_count": len(failed),
                "items_succeeded": succeeded,
                "items_failed": failed,
                "via": "text_confirm",
            },
        )

    # ── Unclear — ask again ────────────────────────────────────────────────
    confirm_label = {"delete": "Eliminar tarea", "update": "Actualizar tarea"}.get(operation, "Crear tarea")
    return make_chat_core_response(
        domain="WORK",
        intent="confirm",
        mode="chat",
        needs_confirmation=True,
        plan=items,
        ui_actions=[UIAction(type="confirm", label=confirm_label)],
        session=ChatSession(
            pending_flow="work_confirm",
            context_id=context_id,
            last_domain="WORK",
            pending_data=pending_data,  # preserve full pending_data including operation
        ),
        audit={"resolution": "unclear", "raw_text": text},
    )


# ---------------------------------------------------------------------------
# Execution Helpers (M13)
# ---------------------------------------------------------------------------

def _coerce_itbms(value: Any) -> bool:
    """Normalize itbms to bool — handles string values from form submission."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "si", "sí", "yes", "1")
    return bool(value)


def _execute_fin_item(
    item: dict[str, Any],
    trace_id: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    """
    Write a single FIN expense item to Google Sheets.

    Returns (ok, message, metadata).
    - ok=True  → item written; metadata has row_number
    - ok=False → write failed; message explains why

    Applies canonicalization (responsable, categoria, moneda defaults)
    before calling append_expense_row so callers don't need to pre-normalise.
    """
    from datetime import date as _date
    from .integrations.sheets import append_expense_row, check_sheets_available

    if not check_sheets_available():
        return False, "Google Sheets no disponible en este momento", {}

    # Validate required fields
    try:
        monto = float(item.get("monto", 0))
    except (ValueError, TypeError):
        return False, f"Monto inválido: {item.get('monto')!r}", {}
    if monto <= 0:
        return False, "El monto debe ser mayor que cero", {}

    # Apply defaults for optional fields
    from .config import FIN_RESPONSIBLES
    default_responsable = FIN_RESPONSIBLES[0] if FIN_RESPONSIBLES else "Jorge"

    expense_data = {
        "monto":        monto,
        "moneda":       item.get("moneda") or "USD",
        "categoria":    item.get("categoria") or "Otros",
        "responsable":  item.get("responsable") or default_responsable,
        "descripcion":  item.get("descripcion") or item.get("categoria") or "Gasto",
        "fecha":        item.get("fecha") or _date.today().isoformat(),
        "itbms":        _coerce_itbms(item.get("itbms", False)),
        "metodo_pago":  item.get("metodo_pago") or "",
        "notas":        item.get("notas") or "",
    }

    # Canonicalize (responsable lookup, categoria normalisation, etc.)
    from .pipelines.fin_normalization import canonicalize_commit_expense
    parsed = canonicalize_commit_expense(expense_data)

    try:
        result = append_expense_row(
            fecha=parsed["fecha"],
            descripcion=parsed["descripcion"],
            factura="",
            responsable=parsed["responsable"],
            monto=parsed["monto"],
            moneda=parsed["moneda"],
            itbms=bool(parsed.get("itbms", False)),
            categoria=parsed["categoria"],
            metodo_pago=parsed.get("metodo_pago") or "",
            notas=parsed.get("notas") or "",
            fuente="chat",
            link_archivo="",
            expense_id=trace_id,
        )
    except Exception as exc:
        return False, f"Error al escribir en Sheets: {exc}", {}

    if result.get("ok"):
        row = result.get("row_number", 0)
        return True, f"Gasto registrado en fila {row}", {"row_number": row}

    err = result.get("error") or "Error desconocido"
    return False, f"No se pudo registrar: {err}", {}


# ---------------------------------------------------------------------------
# WORK Parsing Helpers (M26-B recovery sprint)
# ---------------------------------------------------------------------------

# Matches "crear tarea(s):", "nueva(s) tarea(s):", etc. as a prefix to strip
_WORK_CREATE_VERB_PREFIX = re.compile(
    r"^(?:crea[r]?\s+|a[nñ]ade[r]?\s+|agrega[r]?\s+|inserta[r]?\s+|"
    r"registra[r]?\s+|mete[r]?\s+|haz\s+)?"
    r"(?:una?\s+)?tareas?\s*(?:de\s+|para\s+|:\s*)?",
    re.IGNORECASE,
)


def _parse_bulk_work_items(text: str) -> list[str]:
    """
    Parse task title(s) from natural language create input.

    Single: "crear tarea preparar propuesta ACME" → ["preparar propuesta ACME"]
    Bulk:   "crear tareas: revisar X, actualizar Y" → ["revisar X", "actualizar Y"]
    Bulk:   "crear tareas revisar X, actualizar Y" → ["revisar X", "actualizar Y"]
    """
    # Bulk if "tareas" (plural) with explicit colon OR comma in text
    is_bulk = bool(
        re.search(r"\btareas\b\s*:", text, re.IGNORECASE)
    ) or (
        re.search(r",", text)
        and re.search(r"\btareas\b", text, re.IGNORECASE)
    )

    stripped = _WORK_CREATE_VERB_PREFIX.sub("", text.strip())
    if not stripped:
        return [text.strip()]

    if is_bulk:
        parts = re.split(r"[,;\n]+", stripped)
        titles = [re.sub(r"^[-\u2022*\s]+", "", p).strip() for p in parts]
        return [t for t in titles if t]

    return [stripped]


def _execute_work_delete(
    keywords: list[str],
    delete_all: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Delete (archive) Notion work items that match keywords.

    Queries all active tasks, filters by keyword(s) in-memory, then archives.
    Returns (ok, message, metadata).
    """
    from .integrations.notion import query_work_db, archive_pages, check_notion_available

    if not check_notion_available():
        return False, "Notion no disponible en este momento", {}

    if not keywords and not delete_all:
        return False, "No se especificaron criterios de eliminación", {}

    result = query_work_db(filters={}, limit=100)
    if not result.get("ok"):
        return False, f"Error al consultar Notion: {result.get('error', 'desconocido')}", {}

    items: list[dict] = result.get("items", [])

    # Apply keyword filter (OR semantics — any keyword matches)
    if not delete_all and keywords:
        kws = [k.lower() for k in keywords]
        items = [
            it for it in items
            if any(kw in (it.get("title") or "").lower() for kw in kws)
        ]

    if not items:
        return True, "No se encontraron tareas que coincidan", {"deleted_count": 0, "total_matched": 0}

    page_ids = [it["notion_page_id"] for it in items if it.get("notion_page_id")]

    if not page_ids:
        return False, "Las tareas encontradas no tienen ID de Notion válido", {}

    archived = archive_pages(page_ids)
    total = len(page_ids)
    ok = archived > 0
    return ok, f"Eliminadas {archived}/{total} tarea(s)", {"deleted_count": archived, "total_matched": total}


def _execute_work_item(
    item: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    """
    Create a work item in Notion from a plan dict.

    Returns (ok, message, metadata).
    - ok=True  → item created; metadata has page_id and url
    - ok=False → creation failed; message explains why
    """
    from .integrations.notion import create_work_item, check_notion_available, WorkCreateRequest

    if not check_notion_available():
        return False, "Notion no disponible en este momento", {}

    title = (item.get("title") or "").strip()
    if not title:
        return False, "Falta el título de la tarea", {}

    req = WorkCreateRequest(
        title=title,
        status=item.get("status") or "INBOX",
        project=item.get("project") or item.get("proyecto") or None,
        load=item.get("load") or item.get("carga") or None,
        due=item.get("due") or item.get("fecha") or None,
        notes=item.get("notes") or item.get("notas") or None,
    )

    try:
        result = create_work_item(req)
    except Exception as exc:
        return False, f"Error al crear la tarea: {exc}", {}

    if result.get("ok"):
        return True, f"Tarea creada: {title}", {
            "page_id": result.get("page_id", ""),
            "url":     result.get("url", ""),
        }

    err = result.get("error") or "Error desconocido"
    return False, f"No se pudo crear la tarea: {err}", {}


# ---------------------------------------------------------------------------
# Structured Action Handlers (M12)
# ---------------------------------------------------------------------------

def _process_structured_action(
    action: dict,
    session: ChatSession,
    text: str,
) -> ChatCoreResponse:
    """
    Dispatch a validated structured ChatAction to the appropriate handler.

    Called only when action.type is in STRUCTURED_ACTION_TYPES.
    Each handler is responsible for returning a complete ChatCoreResponse.
    """
    action_type = action["type"]

    if action_type in ("confirm", "cancel"):
        return _handle_action_confirm_cancel(action_type, action, session, text)

    if action_type == "select":
        return _handle_action_select(action, session, text)

    if action_type == "form_submit":
        return _handle_action_form_submit(action, session, text)

    if action_type == "plan_item_execute":
        return _handle_action_plan_item_execute(action, session, text)

    # Should not reach here given STRUCTURED_ACTION_TYPES guard, but be safe
    return make_chat_core_response(
        domain="*",
        intent="passthrough",
        mode="chat",
        session=ChatSession(context_id=session.get("context_id", new_context_id())),
        audit={
            "action_type": action_type,
            "warning": f"Unhandled structured action type: {action_type}",
        },
    )


def _handle_action_confirm_cancel(
    action_type: str,
    action: dict,
    session: ChatSession,
    text: str,
) -> ChatCoreResponse:
    """
    Handle 'confirm' or 'cancel' structured actions.

    Resolves the active pending_flow directly without keyword matching.
    Supported flows: fin_confirm, work_confirm.

    M13: On confirm, executes the actual write (Sheets / Notion) rather than
    just returning an 'execute' intent.
    """
    context_id = session.get("context_id", new_context_id())
    pending_flow = session.get("pending_flow")
    pending_data = session.get("pending_data", {})
    action_target = action.get("target")

    # ── FIN confirm flow ──────────────────────────────────────────────────
    if pending_flow == "fin_confirm":
        if action_type == "cancel":
            return make_chat_core_response(
                domain="FIN",
                intent="cancelled",
                mode="chat",
                session=ChatSession(
                    pending_flow=None, context_id=context_id, last_domain="FIN"
                ),
                audit={
                    "resolution": "cancelled",
                    "action_type": "cancel",
                    "action_target": action_target,
                    "via": "structured_action",
                },
            )

        # confirm — dedup guard
        items: list[dict] = list(pending_data.get("items", []))
        fin_dedup_key = _dedup_key(context_id, "fin_confirm", action_target, {"items_count": len(items)})
        if _check_and_mark_execution(fin_dedup_key):
            return make_chat_core_response(
                domain="FIN",
                intent="already_executed",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id, last_domain="FIN"),
                audit={
                    "execution_result": "skipped",
                    "action_type": "confirm",
                    "action_target": action_target,
                    "via": "structured_action",
                },
            )

        if not items:
            return make_chat_core_response(
                domain="FIN",
                intent="error",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id),
                audit={"error_message": "No hay gastos pendientes para registrar"},
            )

        fin_succeeded: list[dict] = []
        fin_errors: list[str] = []
        for item in items:
            ok, msg, meta = _execute_fin_item(item, trace_id=context_id)
            if ok:
                fin_succeeded.append({**item, **meta})
            else:
                fin_errors.append(msg)

        fin_items_failed = [{"error": e} for e in fin_errors]

        if fin_errors and not fin_succeeded:
            return make_chat_core_response(
                domain="FIN",
                intent="error",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id),
                audit={
                    "resolution": "confirmed",
                    "execution_result": "error",
                    "error_message": fin_errors[0],
                    "error_count": len(fin_errors),
                    "items_failed": fin_items_failed,
                    "action_type": "confirm",
                    "action_target": action_target,
                    "via": "structured_action",
                },
            )

        return make_chat_core_response(
            domain="FIN",
            intent="committed" if not fin_errors else "partial",
            mode="action",
            needs_confirmation=False,
            plan=fin_succeeded,
            session=ChatSession(
                pending_flow=None, context_id=context_id, last_domain="FIN"
            ),
            audit={
                "resolution": "confirmed",
                "execution_result": "success" if not fin_errors else "partial",
                "success_count": len(fin_succeeded),
                "error_count": len(fin_errors),
                "items_succeeded": fin_succeeded,
                "items_failed": fin_items_failed,
                "action_type": "confirm",
                "action_target": action_target,
                "via": "structured_action",
            },
        )

    # ── WORK confirm flow ─────────────────────────────────────────────────
    if pending_flow == "work_confirm":
        if action_type == "cancel":
            return make_chat_core_response(
                domain="WORK",
                intent="cancelled",
                mode="chat",
                session=ChatSession(
                    pending_flow=None, context_id=context_id, last_domain="WORK"
                ),
                audit={
                    "resolution": "cancelled",
                    "action_type": "cancel",
                    "action_target": action_target,
                    "via": "structured_action",
                },
            )

        # confirm — dedup guard
        w_items: list[dict] = list(pending_data.get("items", []))
        w_operation = pending_data.get("operation", "create")
        work_dedup_key = _dedup_key(context_id, "work_confirm", action_target, {"items_count": len(w_items)})
        if _check_and_mark_execution(work_dedup_key):
            return make_chat_core_response(
                domain="WORK",
                intent="already_executed",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id, last_domain="WORK"),
                audit={
                    "execution_result": "skipped",
                    "action_type": "confirm",
                    "action_target": action_target,
                    "via": "structured_action",
                },
            )

        if not w_items:
            return make_chat_core_response(
                domain="WORK",
                intent="error",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id),
                audit={"error_message": "No hay tareas pendientes"},
            )

        # DELETE — execute immediately
        if w_operation == "delete":
            w_keywords = pending_data.get("keywords", [])
            w_delete_all = pending_data.get("delete_all", False)
            w_ok, w_msg, w_meta = _execute_work_delete(w_keywords, w_delete_all)
            w_deleted = w_meta.get("deleted_count", 0)
            w_intent = "deleted" if (w_ok and w_deleted > 0) else ("not_found" if w_ok else "error")
            return make_chat_core_response(
                domain="WORK",
                intent=w_intent,
                mode="action",
                needs_confirmation=False,
                plan=w_items,
                session=ChatSession(pending_flow=None, context_id=context_id, last_domain="WORK"),
                audit={
                    "resolution": "confirmed",
                    "operation": "delete",
                    "message": w_msg,
                    **w_meta,
                    "action_type": "confirm",
                    "action_target": action_target,
                    "via": "structured_action",
                },
            )

        # UPDATE — still deferred; pipeline handles execution
        if w_operation == "update":
            return make_chat_core_response(
                domain="WORK",
                intent="update_confirmed",
                mode="action",
                needs_confirmation=False,
                plan=w_items,
                session=ChatSession(pending_flow=None, context_id=context_id, last_domain="WORK"),
                audit={
                    "resolution": "confirmed",
                    "operation": "update",
                    "items": w_items,
                    "action_type": "confirm",
                    "action_target": action_target,
                    "via": "structured_action",
                },
            )

        # CREATE — execute immediately
        w_succeeded: list[dict] = []
        w_failed: list[dict] = []
        for item in w_items:
            ok, message, meta = _execute_work_item(item)
            if ok:
                w_succeeded.append({**item, **meta})
            else:
                w_failed.append({"item": item, "error": message})

        if w_failed and not w_succeeded:
            return make_chat_core_response(
                domain="WORK",
                intent="error",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id),
                audit={
                    "resolution": "confirmed",
                    "execution_result": "error",
                    "error_message": w_failed[0]["error"],
                    "error_count": len(w_failed),
                    "items_failed": w_failed,
                    "action_type": "confirm",
                    "action_target": action_target,
                    "via": "structured_action",
                },
            )

        return make_chat_core_response(
            domain="WORK",
            intent="created" if not w_failed else "partial",
            mode="action",
            needs_confirmation=False,
            plan=w_succeeded,
            session=ChatSession(
                pending_flow=None, context_id=context_id, last_domain="WORK"
            ),
            audit={
                "resolution": "confirmed",
                "execution_result": "success" if not w_failed else "partial",
                "success_count": len(w_succeeded),
                "error_count": len(w_failed),
                "items_succeeded": w_succeeded,
                "items_failed": w_failed,
                "action_type": "confirm",
                "action_target": action_target,
                "via": "structured_action",
            },
        )

    # ── Generic fallback: use registered resolver for any other pending_flow ──
    # (covers code_preview, code_context, and any future flows)
    if pending_flow and pending_flow in PENDING_FLOW_RESOLVERS:
        hint = "cancelar" if action_type == "cancel" else "confirmar"
        return PENDING_FLOW_RESOLVERS[pending_flow](hint, session, pending_data)

    # ── No recognised pending_flow ─────────────────────────────────────────
    return make_chat_core_response(
        domain="*",
        intent="passthrough",
        mode="chat",
        session=ChatSession(context_id=context_id),
        audit={
            "action_type": action_type,
            "action_target": action_target,
            "warning": f"confirm/cancel received but no active pending_flow "
                       f"(had: {pending_flow!r})",
        },
    )


def _handle_action_select(
    action: dict,
    session: ChatSession,
    text: str,
) -> ChatCoreResponse:
    """
    Handle 'select' structured action.

    Extracts the chosen value from payload.choice and routes it through the
    active pending_flow resolver (or falls back to a fresh text classification
    if there is no pending flow).
    """
    payload = action.get("payload", {})
    # payload.choice is the authoritative value; text is the backward-compat fallback
    choice = payload.get("choice") or text
    context_id = session.get("context_id", new_context_id())
    pending_flow = session.get("pending_flow")

    if pending_flow:
        resolver = PENDING_FLOW_RESOLVERS.get(pending_flow)
        if resolver:
            # Inject structured audit so the resolver knows we came via action
            return resolver(choice, session, session.get("pending_data", {}))

    # No pending flow — treat choice as new plain-text input (no action recursion)
    return process_chat_input(
        choice,
        session,
        action=None,  # explicit: skip structured path
    )


def _handle_action_form_submit(
    action: dict,
    session: ChatSession,
    text: str,
) -> ChatCoreResponse:
    """
    Handle 'form_submit' structured action.

    payload contains field key-values (e.g. {monto: "50", categoria: "Comida"}).
    Routes through the active pending_flow resolver (typically 'clarification').
    Falls back to text classification if no pending flow.
    """
    payload = action.get("payload", {})
    context_id = session.get("context_id", new_context_id())
    pending_flow = session.get("pending_flow")

    if pending_flow:
        resolver = PENDING_FLOW_RESOLVERS.get(pending_flow)
        if resolver:
            # Build a readable text representation for resolvers that still
            # inspect text (backward compat with existing resolver signatures)
            text_repr = text or ", ".join(
                f"{k}: {v}" for k, v in payload.items() if v
            )
            pending_data = dict(session.get("pending_data", {}))
            # Merge structured form values into pending_data so future resolvers
            # can access them without re-parsing text
            pending_data["form_payload"] = payload
            return resolver(text_repr, session, pending_data)

    # No pending flow — classify the text representation
    text_repr = text or ", ".join(f"{k}: {v}" for k, v in payload.items() if v)
    return process_chat_input(text_repr, session, action=None)


def _handle_action_plan_item_execute(
    action: dict,
    session: ChatSession,
    text: str,
) -> ChatCoreResponse:
    """
    Handle 'plan_item_execute' structured action.

    M13: Executes the real write operation for the target item.
    - FIN payload (has 'monto') → append_expense_row via _execute_fin_item
    - WORK payload (has 'title') → create_work_item via _execute_work_item
    - Unknown shape → safe acknowledge with execute_requested intent
    """
    payload = action.get("payload", {})
    item_id = action.get("id")
    target = action.get("target")
    context_id = session.get("context_id", new_context_id())

    base_audit: dict[str, Any] = {
        "action_type": "plan_item_execute",
        "action_id": item_id,
        "action_target": target,
        "via": "structured_action",
    }

    # ── Dedup guard ────────────────────────────────────────────────────────
    exe_dedup_key = _dedup_key(context_id, "plan_item_execute", item_id, payload)
    if _check_and_mark_execution(exe_dedup_key):
        return make_chat_core_response(
            domain="*",
            intent="already_executed",
            mode="chat",
            session=ChatSession(context_id=context_id),
            audit={**base_audit, "execution_result": "skipped"},
        )

    # ── FIN item ──────────────────────────────────────────────────────────
    if "monto" in payload:
        ok, message, meta = _execute_fin_item(payload, trace_id=target or context_id)

        if ok:
            return make_chat_core_response(
                domain="FIN",
                intent="committed",
                mode="action",
                needs_confirmation=False,
                plan=[{**payload, **meta}],
                session=ChatSession(
                    pending_flow=None,
                    context_id=context_id,
                    last_domain="FIN",
                ),
                audit={**base_audit, "execution_result": "success", **meta},
            )
        else:
            return make_chat_core_response(
                domain="FIN",
                intent="error",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id),
                audit={
                    **base_audit,
                    "execution_result": "error",
                    "error_message": message,
                },
            )

    # ── WORK item ─────────────────────────────────────────────────────────
    if "title" in payload:
        ok, message, meta = _execute_work_item(payload)

        if ok:
            return make_chat_core_response(
                domain="WORK",
                intent="created",
                mode="action",
                needs_confirmation=False,
                plan=[{**payload, **meta}],
                session=ChatSession(
                    pending_flow=None,
                    context_id=context_id,
                    last_domain="WORK",
                ),
                audit={**base_audit, "execution_result": "success", **meta},
            )
        else:
            return make_chat_core_response(
                domain="WORK",
                intent="error",
                mode="chat",
                session=ChatSession(pending_flow=None, context_id=context_id),
                audit={
                    **base_audit,
                    "execution_result": "error",
                    "error_message": message,
                },
            )

    # ── Unknown payload shape — safe acknowledge ──────────────────────────
    return make_chat_core_response(
        domain="*",
        intent="execute_requested",
        mode="action",
        plan=[payload] if payload else [],
        session=ChatSession(context_id=context_id),
        audit={**base_audit, "warning": "Unknown payload shape, no write performed"},
    )


# ---------------------------------------------------------------------------
# CODE domain handler (M27)
# ---------------------------------------------------------------------------

# Regex for extracting file mentions (e.g. "webhook_server.py", "chat_core.py")
_CODE_FILE_RE = re.compile(
    r"\b(\w[\w.\-]*\.(?:py|ts|tsx|js|jsx|go|rs|yaml|yml|json|toml))\b",
    re.IGNORECASE,
)

# Regex for extracting inline repo path from text like "explica X en C:\Dev\..."
# Matches "en <path>" / "de <path>" with Windows absolute paths or Unix absolute paths
_REPO_PATH_RE = re.compile(
    r"(?:en|de)\s+([A-Za-z]:[\\\/][^\s,;]+|\/[^\s,;]+)",
    re.IGNORECASE,
)

# Directories to skip when searching workspace for a file by name
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".next", ".cache",
})


def _extract_code_files(text: str) -> list[str]:
    """Return unique file names/paths found in text (preserves first-seen order)."""
    return list(dict.fromkeys(_CODE_FILE_RE.findall(text)))


def _extract_repo_path(text: str) -> str:
    """
    Extract inline repo path from text.

    Handles patterns like:
      "explica chat_core.py en C:\\Dev\\Assistant_OS_Labs"
      "revisa webhook_server.py de /home/user/project"

    Returns the path string (trailing path separators stripped), or "" if none found.
    """
    import os as _os
    m = _REPO_PATH_RE.search(text)
    if not m:
        return ""
    raw = m.group(1).rstrip("/\\.,;")
    # Only return if it looks like a real absolute path that exists on disk
    if _os.path.isdir(raw):
        return raw
    return raw  # Return even if not verified — executor will handle missing workspace


def _resolve_file_in_workspace(workspace: str, filename: str) -> str:
    """
    Resolve a bare filename to its relative path within workspace.

    If the filename already contains a path separator it is returned as-is.
    Otherwise walks the workspace tree (skipping common non-source dirs) to
    find the first match.  Returns the original filename if not found — the
    executor will report "file not found" cleanly.

    Security: only returns paths that are children of workspace (path traversal
    is prevented by the executor's own guard in _read_target_file).
    """
    import os as _os
    if not workspace or not filename:
        return filename
    # Already a relative or absolute path — don't recurse
    if _os.sep in filename or "/" in filename:
        return filename
    for root, dirs, files in _os.walk(workspace):
        # Prune irrelevant dirs in-place
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        if filename in files:
            rel = _os.path.relpath(_os.path.join(root, filename), workspace)
            return rel
    return filename  # Not found — executor returns a clean "file not found" message


# ---------------------------------------------------------------------------
# M28: Executor helpers — call real Claude via code_pipeline registry
# ---------------------------------------------------------------------------

def _call_review_executor(
    operation: str,
    text: str,
    files: list[str],
    repo_path: str = "",
    symbol_name: str = "",
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
) -> dict:
    """
    Call the registered CODE review executor for EXPLAIN / REVIEW.

    M29: Supports optional targeted extraction via symbol_name or line_start/line_end.
    When either is provided, the executor reads the full file locally and extracts
    only the relevant section before calling Claude.

    Always safe to call — no writes, no git ops, no side effects.
    """
    try:
        from .pipelines import code_pipeline  # lazy: reads current module state
        executor = code_pipeline._review_executor
        if executor is None:
            return {
                "ok": False,
                "error": "Executor de análisis no disponible. ¿Está ANTHROPIC_API_KEY configurada?",
            }
        return executor({
            "action": operation,
            "target_file": files[0] if files else "",
            "workspace": repo_path or "",
            "context": text,
            "symbol_name": symbol_name,
            "line_start": line_start,
            "line_end": line_end,
        })
    except Exception as exc:
        _log.error("review_executor call failed: %s", exc)
        return {"ok": False, "error": f"Error llamando al executor: {exc}"}


def _call_propose_executor(
    operation: str,
    task: str,
    files: list[str],
    repo_path: str = "",
) -> dict:
    """
    Call the registered CODE propose executor for FIX / CREATE preview.

    PREVIEW-ONLY: no file writes, no git operations, no patch application.
    Returns a structured proposal (summary, affected_files, patch_preview, risk_level).
    Uses code_pipeline._propose_executor registered at server startup.
    """
    try:
        from .pipelines import code_pipeline  # lazy: reads current module state
        executor = code_pipeline._propose_executor
        if executor is None:
            return {
                "ok": False,
                "error": "Executor de propuesta no disponible. ¿Está ANTHROPIC_API_KEY configurada?",
            }
        target_file = files[0] if files else ""
        # Pass up to 2 resolved files so Claude knows the full write scope (M28.5)
        scope = [f for f in files[:2] if f] if len(files) > 1 else ([target_file] if target_file else [])
        return executor({
            "action": operation,
            "target_file": target_file,
            "workspace": repo_path or "",
            "context": task,
            "allowed_write_scope": scope,
        })
    except Exception as exc:
        _log.error("propose_executor call failed: %s", exc)
        return {"ok": False, "error": f"Error llamando al executor: {exc}"}


# ---------------------------------------------------------------------------
# Executor error classification (M29 hardening)
# ---------------------------------------------------------------------------

import re as _re

_TOO_LARGE_RE = _re.compile(
    r"File too large[^:]*:\s*'([^']+)'\s*\(([0-9,]+)\s*bytes;\s*limit is ([0-9,]+)\s*bytes\)",
    _re.IGNORECASE,
)
_NOT_FOUND_RE = _re.compile(r"File not found:\s*'([^']+)'", _re.IGNORECASE)
_TRAVERSAL_RE = _re.compile(r"Path traversal", _re.IGNORECASE)
_AUTH_RE      = _re.compile(r"API authentication", _re.IGNORECASE)
_RATE_RE      = _re.compile(r"rate limit", _re.IGNORECASE)
_NO_EXEC_RE   = _re.compile(r"Executor de (análisis|propuesta) no disponible", _re.IGNORECASE)


def _classify_executor_error(error: str) -> dict:
    """
    Parse the raw executor error string into a structured kind dict.

    Returns:
        {"kind": "too_large",     "file": str, "size": int, "limit": int}
        {"kind": "not_found",     "file": str}
        {"kind": "security",      "msg": str}
        {"kind": "not_configured","msg": str}
        {"kind": "api_auth",      "msg": str}
        {"kind": "rate_limit",    "msg": str}
        {"kind": "generic",       "msg": str}
    """
    if m := _TOO_LARGE_RE.search(error):
        return {
            "kind": "too_large",
            "file": m.group(1),
            "size": int(m.group(2).replace(",", "")),
            "limit": int(m.group(3).replace(",", "")),
        }
    if m := _NOT_FOUND_RE.search(error):
        return {"kind": "not_found", "file": m.group(1)}
    if _TRAVERSAL_RE.search(error):
        return {"kind": "security", "msg": "Ruta fuera del repositorio"}
    if _AUTH_RE.search(error):
        return {"kind": "api_auth", "msg": "Fallo de autenticación con la API de Claude. Verifica ANTHROPIC_API_KEY."}
    if _RATE_RE.search(error):
        return {"kind": "rate_limit", "msg": "Límite de requests a Claude alcanzado. Intenta en unos segundos."}
    if _NO_EXEC_RE.search(error):
        return {"kind": "not_configured", "msg": error}
    return {"kind": "generic", "msg": error}


# ---------------------------------------------------------------------------
# M29: Prompt targeting parsers — symbol, line range, index detection
# ---------------------------------------------------------------------------

# Code-symbol identifiers: underscore-prefixed, PascalCase (2+ words), snake_case
_SYMBOL_BARE_RE = _re.compile(
    r'\b('
    r'_[a-zA-Z]\w+'                            # _private_or_protected
    r'|[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+'        # PascalCase: ChatRenderer, ProcessInput
    r'|[A-Z]{2,}[a-z]+(?:[A-Z][a-z0-9]+)+'   # All-caps prefix: UIAction, LLMResult
    r'|[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}'     # snake_case: handle_action, parse_result
    r'|[a-z][a-z0-9]+(?:[A-Z][a-z0-9]+)+'    # camelCase: processInput, renderChat
    r')\b'
)

# Line range: "líneas 100-180", "líneas 100 a 180", "lines 100-180", "lines 100 to 180"
_LINE_RANGE_RE = _re.compile(
    r'\b(?:l[ií]neas?|lines?)\s+(\d+)\s*(?:[-\u2013]|al?\s+|to\s+)\s*(\d+)',
    _re.IGNORECASE,
)

# Index request: "lista funciones", "índice de", "qué clases tiene", etc.
_INDEX_RE = _re.compile(
    r'\b(?:'
    r'lista(?:r)?\s+(?:las?\s+)?(?:funciones?|clases?|m[eé]todos?|s[íi]mbolos?|symbols?)'
    r'|[íi]ndice\s+(?:de|del?)'
    r'|qu[eé]\s+(?:funciones?|clases?|m[eé]todos?)\s+tiene'
    r'|show\s+(?:functions?|classes?|index|symbols?)'
    r'|list\s+(?:functions?|classes?|symbols?)'
    r')\b',
    _re.IGNORECASE,
)


def _extract_symbol_from_prompt(text: str) -> Optional[str]:
    """
    Find a code symbol (function/class name) in the user's prompt.

    Looks for identifiers that match code-naming conventions (underscore-prefixed,
    PascalCase, snake_case with multiple parts).  File stems are excluded.
    Returns None when no code symbol is confidently identified.
    """
    # Exclude filename stems so "chat_core" in "chat_core.py" doesn't match
    file_stems = {f.rsplit(".", 1)[0] for f in _extract_code_files(text)}

    for m in _SYMBOL_BARE_RE.finditer(text):
        sym = m.group(1)
        if sym in file_stems:
            continue
        # Skip if immediately followed by "." or "/" or "\" — filename, attribute, or
        # path component (e.g. "assistant_os" in "assistant_os/chat_db.py")
        end_pos = m.end()
        if end_pos < len(text) and text[end_pos] in "./\\":
            continue
        # Skip if immediately preceded by "/" or "\" — trailing path component
        start_pos = m.start()
        if start_pos > 0 and text[start_pos - 1] in "/\\":
            continue
        return sym
    return None


def _extract_line_range_from_prompt(text: str) -> Optional[tuple[int, int]]:
    """Return (start, end) line numbers if the prompt contains a range, else None."""
    m = _LINE_RANGE_RE.search(text)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if start <= end and start >= 1:
            return start, end
    return None


def _is_index_request(text: str) -> bool:
    """Return True if the prompt is asking for a file/symbol index listing."""
    return bool(_INDEX_RE.search(text))


def _quick_index_for_suggestion(repo_path: str, resolved_file: str) -> list[str]:
    """
    Read a file locally and return up to 8 top-level function/class names.
    Used to build concrete suggestions in file_too_large responses.
    """
    if not resolved_file or not repo_path:
        return []
    import os as _os_local
    abs_path = _os_local.path.normpath(_os_local.path.join(repo_path, resolved_file))
    repo_norm = _os_local.path.normpath(repo_path)
    if not abs_path.startswith(repo_norm + _os_local.sep):
        return []
    if not _os_local.path.isfile(abs_path):
        return []
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read(524_288)  # 512 KB cap for local indexing
    except OSError:
        return []
    try:
        from .executors.code_extractor import extract_index, detect_lang
        lang = detect_lang(resolved_file)
        symbols = extract_index(content, lang)
        top_level = [s for s in symbols if s.get("kind") not in ("method",)]
        return [s["name"] for s in top_level[:8]]
    except Exception:
        return []


def _handle_file_index_request(
    resolved_files: list[str],
    repo_path: str,
    context_id: str,
    operation: str,
    text: str,
) -> Optional["ChatCoreResponse"]:
    """
    Build a structural index of the target file without calling Claude.
    Returns a ChatCoreResponse with intent='file_index', or None if the file
    cannot be indexed (caller should fall through to normal executor flow).
    """
    if not resolved_files or not repo_path:
        return None

    import os as _os_local
    target_file = resolved_files[0]
    abs_path = _os_local.path.normpath(_os_local.path.join(repo_path, target_file))
    repo_norm = _os_local.path.normpath(repo_path)
    if not abs_path.startswith(repo_norm + _os_local.sep):
        return None
    if not _os_local.path.isfile(abs_path):
        return None

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read(524_288)
        total_lines = content.count("\n") + 1
    except OSError as exc:
        _log.warning("file_index: cannot read %r: %s", target_file, exc)
        return None

    try:
        from .executors.code_extractor import extract_index, detect_lang
        lang = detect_lang(target_file)
        symbols = extract_index(content, lang)
    except Exception as exc:
        _log.warning("file_index: extraction failed for %r: %s", target_file, exc)
        return None

    _log.debug("file_index: %r  symbols=%d  lines=%d", target_file, len(symbols), total_lines)
    return make_chat_core_response(
        domain="CODE",
        intent="file_index",
        mode="chat",
        needs_confirmation=False,
        session=ChatSession(context_id=context_id, pending_flow=None, last_domain="CODE"),
        audit={
            "operation": operation,
            "files": resolved_files,
            "repo_path": repo_path,
            "index_symbols": symbols,
            "index_file": target_file,
            "total_lines": total_lines,
        },
    )


def _build_code_plan(verb: str, text: str, files: list[str]) -> list[dict]:
    """Build a CODE preview plan with file context when available."""
    file_ctx = f" ({', '.join(files)})" if files else ""
    return [
        {"step": 1, "action": "analyze",  "description": f"{verb}: {text[:80]}"},
        {"step": 2, "action": "propose",  "description": f"Generar diff y preview de cambios{file_ctx}"},
        {"step": 3, "action": "apply",    "description": "Aplicar cambios (confirmación requerida)"},
    ]


def _call_review_and_respond(
    operation: str,
    text: str,
    resolved_files: list[str],
    repo_path: str,
    context_id: str,
) -> "ChatCoreResponse":
    """
    Call review executor and wrap result as ChatCoreResponse.

    Shared by the inline-path branch of _process_code_input and the
    code_review_context resolver (M28.5).  Detects symbol/range/index targeting
    in the user's text (M29) and passes them through to the executor.
    """
    # ── M29: detect targeting mode ────────────────────────────────────────
    if _is_index_request(text) and resolved_files and repo_path:
        result = _handle_file_index_request(resolved_files, repo_path, context_id, operation, text)
        if result is not None:
            return result
        # Fall through if index extraction failed (e.g. file missing)

    symbol  = _extract_symbol_from_prompt(text)
    lr      = _extract_line_range_from_prompt(text)
    line_start, line_end = (lr[0], lr[1]) if lr else (None, None)

    exec_result = _call_review_executor(
        operation, text, resolved_files, repo_path=repo_path,
        symbol_name=symbol or "",
        line_start=line_start,
        line_end=line_end,
    )
    if exec_result.get("ok"):
        return make_chat_core_response(
            domain="CODE",
            intent="responded",
            mode="chat",
            needs_confirmation=False,
            session=ChatSession(
                context_id=context_id,
                pending_flow=None,
                last_domain="CODE",
            ),
            audit={
                "operation": operation,
                "raw_text": text,
                "files": resolved_files,
                "repo_path": repo_path,
                "analysis": exec_result["analysis"],
            },
        )

    raw_error = exec_result.get("error", "Error desconocido")
    err = _classify_executor_error(raw_error)
    _log.warning(
        "code_review error: kind=%s  op=%s  symbol=%r  files=%d  error=%s",
        err["kind"], operation, symbol, len(resolved_files), raw_error[:80],
    )

    # ── File too large: include symbol suggestions from quick local index ─
    if err["kind"] == "too_large":
        suggestions = _quick_index_for_suggestion(
            repo_path, resolved_files[0] if resolved_files else ""
        )
        return make_chat_core_response(
            domain="CODE",
            intent="file_too_large",
            mode="chat",
            needs_confirmation=False,
            session=ChatSession(context_id=context_id, pending_flow=None, last_domain="CODE"),
            audit={
                "operation": operation,
                "raw_text": text,
                "files": resolved_files,
                "file_too_large_name": err["file"],
                "file_too_large_size": err["size"],
                "file_too_large_limit": err["limit"],
                "top_symbols": suggestions,  # M29: concrete suggestions
            },
        )

    # ── File not found ────────────────────────────────────────────────────
    if err["kind"] == "not_found":
        return make_chat_core_response(
            domain="CODE",
            intent="file_not_found",
            mode="chat",
            needs_confirmation=False,
            session=ChatSession(context_id=context_id, pending_flow=None, last_domain="CODE"),
            audit={
                "operation": operation,
                "files": resolved_files,
                "missing_file": err["file"],
            },
        )

    # ── All other errors: structured executor_error ───────────────────────
    human_msg = {
        "security":      "Ruta fuera del repositorio. Verifica que el archivo esté dentro de repo_path.",
        "api_auth":      "Fallo de autenticación con la API de Claude. Verifica ANTHROPIC_API_KEY.",
        "rate_limit":    "Límite de requests alcanzado. Intenta de nuevo en unos segundos.",
        "not_configured":"El executor no está disponible. Asegúrate de que ANTHROPIC_API_KEY esté configurada.",
        "generic":       "No se pudo analizar el archivo. Verifica la ruta o intenta con otro archivo.",
    }.get(err["kind"], "Error inesperado al analizar el archivo.")
    return make_chat_core_response(
        domain="CODE",
        intent="executor_error",
        mode="chat",
        needs_confirmation=False,
        session=ChatSession(context_id=context_id, pending_flow=None, last_domain="CODE"),
        audit={
            "operation": operation,
            "files": resolved_files,
            "error_message": human_msg,
        },
    )


def _process_code_input(
    text: str,
    session: ChatSession,
    classify_result: dict,
) -> "ChatCoreResponse":
    """
    Route CODE domain inputs.

    Read-only (CODE_EXPLAIN / CODE_REVIEW):
        Acknowledges the request with file context when detected.

    Mutating (CODE_FIX / CODE_CREATE):
        M27: First captures repo_path (required) and base_branch (optional)
        via a form, then shows a richer preview plan before confirming.

    All other operations fall through to a generic CODE query response.
    """
    operation  = classify_result.get("operation", "")
    context_id = session.get("context_id", new_context_id())
    files      = _extract_code_files(text)

    # ── Mutating: need repo_path before preview ──────────────────────────────
    if operation in (OP_CODE_FIX, OP_CODE_CREATE):
        # Pre-fill form with inline repo_path if the user included it (M28.5)
        inline_repo = _extract_repo_path(text)
        form_values: dict = {"base_branch": "main"}
        if inline_repo:
            form_values["repo_path"] = inline_repo
        # M29 hardening: if no file detected, ask for target_file explicitly
        # so the propose executor has something concrete to work with
        if not files:
            form_fields = ["target_file", "repo_path", "base_branch"]
            form_label = "¿En qué archivo trabajamos? Necesito repo_path para continuar."
        else:
            form_fields = ["repo_path", "base_branch"]
            form_label = "Contexto del repositorio requerido"
        return make_chat_core_response(
            domain="CODE",
            intent="needs_context",
            mode="chat",
            needs_confirmation=True,
            plan=[],
            ui_actions=[UIAction(
                type="form",
                label=form_label,
                fields=form_fields,
                values=form_values,
            )],
            session=ChatSession(
                context_id=context_id,
                pending_flow="code_context",
                pending_data={"operation": operation, "task": text, "files": files},
                last_domain="CODE",
            ),
            audit={"operation": operation, "task_preview": text[:120], "files": files},
        )

    # ── Read-only: explain or review ─────────────────────────────────────────
    if operation in (OP_CODE_EXPLAIN, OP_CODE_REVIEW):
        repo_path = _extract_repo_path(text)

        # File(s) mentioned but no repo_path available: ask for it via form
        # so the executor can load real content (M28.5)
        if files and not repo_path:
            return make_chat_core_response(
                domain="CODE",
                intent="needs_context",
                mode="chat",
                needs_confirmation=True,
                plan=[],
                ui_actions=[UIAction(
                    type="form",
                    label="Repo path necesario para cargar el archivo",
                    fields=["repo_path"],
                    values={},
                )],
                session=ChatSession(
                    context_id=context_id,
                    pending_flow="code_review_context",
                    pending_data={"operation": operation, "task": text, "files": files},
                    last_domain="CODE",
                ),
                audit={"operation": operation, "task_preview": text[:120], "files": files},
            )

        # repo_path available inline (or no file to resolve) — call executor now
        resolved_files = (
            [_resolve_file_in_workspace(repo_path, f) for f in files[:2]]
            if repo_path and files
            else files
        )
        return _call_review_and_respond(
            operation, text, resolved_files, repo_path, context_id,
        )

    # Generic CODE query fallback
    return make_chat_core_response(
        domain="CODE",
        intent="query",
        mode="chat",
        needs_confirmation=False,
        session=ChatSession(
            context_id=context_id,
            pending_flow=None,
            last_domain="CODE",
        ),
        audit={"operation": operation, "raw_text": text, "files": files},
    )


@register_pending_flow_resolver("code_context")
def _resolve_code_context(
    text: str,
    session: ChatSession,
    pending_data: dict[str, Any],
) -> "ChatCoreResponse":
    """
    M27: Capture repo_path + base_branch from form submission, then show
    the full CODE preview with a confirm button.

    Called via _handle_action_form_submit → PENDING_FLOW_RESOLVERS["code_context"].
    pending_data["form_payload"] is set by _handle_action_form_submit.
    """
    context_id  = session.get("context_id", new_context_id())
    operation   = pending_data.get("operation", "CODE_FIX")
    task        = pending_data.get("task", "")
    files       = pending_data.get("files", [])
    form_payload: dict = pending_data.get("form_payload", {})

    is_cancel = text.strip().lower() in ("cancelar", "cancel", "no")
    if is_cancel:
        return make_chat_core_response(
            domain="CODE",
            intent="cancelled",
            mode="chat",
            session=ChatSession(pending_flow=None, context_id=context_id, last_domain="CODE"),
            audit={"operation": operation, "resolution": "cancelled"},
        )

    # Extract from structured form payload first, fall back to text parsing
    repo_path   = (form_payload.get("repo_path") or "").strip()
    base_branch = (form_payload.get("base_branch") or "main").strip() or "main"

    # M29: if target_file was explicitly requested in the form (ambiguous prompt),
    # prepend it to files so it's available for resolution and proposal
    form_target = (form_payload.get("target_file") or "").strip()
    if form_target and form_target not in files:
        files = [form_target] + list(files)
        _log.debug("code_propose: target_file from form: %r", form_target)

    if not repo_path and text:
        # Parse "repo_path: /path, base_branch: main" from human-readable text
        for part in text.split(","):
            k, _, v = part.strip().partition(":")
            k, v = k.strip(), v.strip()
            if k == "repo_path":
                repo_path = v
            elif k == "base_branch" and v:
                base_branch = v

    if not repo_path:
        # Still missing — ask again with error hint
        return make_chat_core_response(
            domain="CODE",
            intent="needs_context",
            mode="chat",
            needs_confirmation=True,
            plan=[],
            ui_actions=[UIAction(
                type="form",
                label="repo_path es requerido para preparar la ejecución",
                fields=["repo_path", "base_branch"],
                values={"base_branch": base_branch},
            )],
            session=ChatSession(
                context_id=context_id,
                pending_flow="code_context",
                pending_data={**pending_data, "form_payload": {}},
                last_domain="CODE",
            ),
            audit={"operation": operation, "error": "missing_repo_path"},
        )

    # Have repo_path → resolve filenames to workspace-relative paths (M28.5)
    resolved_files = (
        [_resolve_file_in_workspace(repo_path, f) for f in files[:2]]
        if files else []
    )
    verb = "Corregir" if operation == OP_CODE_FIX else "Implementar"
    plan = _build_code_plan(verb, task, resolved_files or files)
    return make_chat_core_response(
        domain="CODE",
        intent="preview",
        mode="plan",
        needs_confirmation=True,
        plan=plan,
        ui_actions=[UIAction(type="confirm", label="Confirmar y planificar")],
        session=ChatSession(
            context_id=context_id,
            pending_flow="code_preview",
            pending_data={
                "operation": operation,
                "task": task,
                "repo_path": repo_path,
                "base_branch": base_branch,
                "files": files,
                "resolved_files": resolved_files,  # M28.5: pre-resolved for propose executor
            },
            last_domain="CODE",
        ),
        audit={
            "operation": operation,
            "task_preview": task[:120],
            "repo_path": repo_path,
            "base_branch": base_branch,
            "files": resolved_files or files,
        },
    )


@register_pending_flow_resolver("code_review_context")
def _resolve_code_review_context(
    text: str,
    session: ChatSession,
    pending_data: dict[str, Any],
) -> "ChatCoreResponse":
    """
    M28.5: Capture repo_path for a pending EXPLAIN/REVIEW request, then call
    the review executor with resolved file content.

    Called via _handle_action_form_submit or button press when the user submits
    the single-field form asking for repo_path.
    """
    context_id  = session.get("context_id", new_context_id())
    operation   = pending_data.get("operation", OP_CODE_EXPLAIN)
    task        = pending_data.get("task", "")
    files       = pending_data.get("files", [])
    form_payload: dict = pending_data.get("form_payload", {})

    is_cancel = text.strip().lower() in ("cancelar", "cancel", "no")
    if is_cancel:
        return make_chat_core_response(
            domain="CODE",
            intent="cancelled",
            mode="chat",
            session=ChatSession(pending_flow=None, context_id=context_id, last_domain="CODE"),
            audit={"operation": operation, "resolution": "cancelled"},
        )

    # Extract repo_path: form payload → _REPO_PATH_RE on text → raw text as path
    repo_path = (form_payload.get("repo_path") or "").strip()
    if not repo_path and text:
        m = _REPO_PATH_RE.search(text)
        if m:
            repo_path = m.group(1).rstrip("/\\.,;")
        else:
            # User may have typed the path directly without a keyword prefix
            candidate = text.strip().rstrip("/\\.,;")
            import os as _os
            if candidate and (_os.sep in candidate or "/" in candidate):
                repo_path = candidate

    if not repo_path:
        return make_chat_core_response(
            domain="CODE",
            intent="needs_context",
            mode="chat",
            needs_confirmation=True,
            plan=[],
            ui_actions=[UIAction(
                type="form",
                label="repo_path es requerido para cargar el archivo",
                fields=["repo_path"],
                values={},
            )],
            session=ChatSession(
                context_id=context_id,
                pending_flow="code_review_context",
                pending_data={**pending_data, "form_payload": {}},
                last_domain="CODE",
            ),
            audit={"operation": operation, "error": "missing_repo_path"},
        )

    # Resolve filenames and call review executor
    resolved_files = [_resolve_file_in_workspace(repo_path, f) for f in files[:2]]
    return _call_review_and_respond(operation, task, resolved_files, repo_path, context_id)


@register_pending_flow_resolver("code_preview")
def _resolve_code_preview(
    text: str,
    session: ChatSession,
    pending_data: dict[str, Any],
) -> "ChatCoreResponse":
    """
    Handle confirm / cancel for a pending CODE preview.

    On confirm: calls the propose executor with repo_path + resolved files
    (M28.5: uses resolved_files from pending_data when available).

    On cancel: clears the pending flow.
    """
    context_id  = session.get("context_id", new_context_id())
    operation   = pending_data.get("operation", "CODE_FIX")
    task        = pending_data.get("task", "")
    repo_path   = pending_data.get("repo_path", "")
    base_branch = pending_data.get("base_branch", "main")
    files       = pending_data.get("files", [])
    # M28.5: prefer pre-resolved paths (set by _resolve_code_context)
    resolved_files = pending_data.get("resolved_files") or files

    is_cancel = text.strip().lower() in ("cancelar", "cancel", "no")

    if is_cancel:
        return make_chat_core_response(
            domain="CODE",
            intent="cancelled",
            mode="chat",
            session=ChatSession(pending_flow=None, context_id=context_id, last_domain="CODE"),
            audit={"operation": operation, "resolution": "cancelled"},
        )

    # Confirmed: M28 — call real Claude propose executor with resolved files (M28.5)
    exec_result = _call_propose_executor(operation, task, resolved_files, repo_path)
    if exec_result.get("ok"):
        return make_chat_core_response(
            domain="CODE",
            intent="proposed",
            mode="chat",
            needs_confirmation=False,
            session=ChatSession(pending_flow=None, context_id=context_id, last_domain="CODE"),
            audit={
                "operation": operation,
                "task_preview": task[:120],
                "repo_path": repo_path,
                "base_branch": base_branch,
                "files": resolved_files,
                "resolution": "confirmed",
                # Claude proposal data
                "summary": exec_result.get("summary", ""),
                "affected_files": exec_result.get("affected_files", []),
                "patch_preview": exec_result.get("patch_preview", ""),
                "risk_level": exec_result.get("risk_level", "medium"),
                "write_intent_summary": exec_result.get("write_intent_summary", ""),
            },
        )
    # Executor ran but returned an error — surface as executor_error, not queued
    _log.warning("propose_executor failed: %s", exec_result.get("error"))
    return make_chat_core_response(
        domain="CODE",
        intent="executor_error",
        mode="chat",
        needs_confirmation=False,
        session=ChatSession(pending_flow=None, context_id=context_id, last_domain="CODE"),
        audit={
            "operation": operation,
            "task_preview": task[:120],
            "repo_path": repo_path,
            "base_branch": base_branch,
            "files": resolved_files,
            "resolution": "confirmed",
            # error_message used by renderer template; propose_error preserved for audit
            "error_message": exec_result.get("error") or "El executor no detectó cambios aplicables.",
            "propose_error": exec_result.get("error"),
            "human_msg": "El executor corrió pero no pudo generar cambios aplicables.",
        },
    )


# ---------------------------------------------------------------------------
# Core Routing Logic
# ---------------------------------------------------------------------------

def process_chat_input(
    text: str,
    session: Optional[ChatSession] = None,
    domain_hint: Optional[str] = None,
    action: Optional[dict] = None,
) -> ChatCoreResponse:
    """
    Layer 1: Process user input and produce structured response.

    Priority order (M12):
    1. Structured action routing  — if ``action`` is provided and valid, the
       backend uses it as the primary intent signal.  ``text`` is kept as
       context / backward-compat fallback but is NOT used for keyword matching
       when an explicit action type is available.
    2. Pending flow routing       — if session.pending_flow exists, route
       directly to its resolver without re-classification.
    3. Classification + domain routing — normal text-based path.

    Args:
        text:        User input text (may be empty when action is provided)
        session:     Optional session state from previous turn
        domain_hint: Optional domain hint (e.g., from endpoint)
        action:      Optional structured action dict from the frontend (M12)

    Returns:
        ChatCoreResponse — structured response for Layer 2
    """
    session = session or ChatSession(context_id=new_context_id())
    text = (text or "").strip()

    # --- PRIORITY 1: STRUCTURED ACTION ROUTING (M12) ---------------------
    if action is not None:
        parsed, err = parse_action(action)
        if err:
            _log.warning("process_chat_input: malformed action: %s", err)
            return make_chat_core_response(
                domain="*",
                intent="error",
                mode="chat",
                session=session,
                audit={"error_message": f"Malformed action: {err}"},
            )
        if parsed and parsed["type"] in STRUCTURED_ACTION_TYPES:
            _log.debug(
                "structured_action=%s pending_flow=%s",
                parsed["type"], session.get("pending_flow") or "None",
            )
            return _process_structured_action(parsed, session, text)
        # Unknown / unsupported type (e.g. "chip") — fall through to text flow
        _log.debug("action type %r not structured, falling through to text", action.get("type"))

    # Require at least some text for the text-based path
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

    _op = classify_result.get("operation")

    # If the operation detector found a WORK mutation, force domain=WORK so
    # the text reaches _process_work_input even when the domain classifier
    # guesses a different domain (e.g. ENERGY) at low confidence (M26-B).
    if _op in _WORK_MUTATION_OPS:
        domain = "WORK"

    # WORK_QUERY takes priority UNLESS the classifier has already determined
    # this is a CODE operation (M23) OR a WORK mutation (M26-B).
    # WORK_CREATE/UPDATE/DELETE must reach _process_work_input — is_work_query
    # matches "tarea" broadly and would swallow all mutation prompts otherwise.
    if is_work_query(text, domain) and domain != "CODE" and _op not in _WORK_MUTATION_OPS:
        return _process_work_query(text, session, classify_result)

    # --- DOMAIN-SPECIFIC ROUTING ---

    if domain == "FIN":
        return _process_fin_input(text, session, classify_result)

    if domain == "WORK":
        return _process_work_input(text, session, classify_result)

    if domain == "CODE":
        return _process_code_input(text, session, classify_result)

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
    clarifications = action_plan.get("clarification_questions", [])
    plan_type = action_plan.get("type", "single_fin")

    # Convert FinItems to plan dicts
    plan = [dict(item) for item in items]

    # --- Always show editable form before commit (M27) ---
    # Whether chaperon found all fields or is missing some, always present the
    # user with a pre-filled editable form so they can review/correct every
    # field before the final confirm.  This replaces the old read-only confirm
    # and the separate missing_fields path with a single unified surface.
    if plan:
        from datetime import date as _date
        from .config import FIN_RESPONSIBLES
        _default_resp = FIN_RESPONSIBLES[0] if FIN_RESPONSIBLES else "Jorge"

        # For single gasto show all editable fields; for multi show only the
        # global fields (responsable, fecha, moneda, itbms, metodo_pago) so
        # individual per-item monto/descripcion/categoria are not overwritten.
        is_multi = len(plan) > 1
        if is_multi:
            edit_fields = ["responsable", "fecha", "moneda", "itbms", "metodo_pago"]
        else:
            edit_fields = ["monto", "descripcion", "categoria", "responsable",
                           "fecha", "moneda", "itbms", "metodo_pago"]

        # Build pre-filled values from first item (shared context for multi)
        ref = plan[0]
        pre_values: dict[str, str] = {
            "monto":       str(ref.get("monto", "")) if ref.get("monto") else "",
            "descripcion": str(ref.get("descripcion") or ref.get("raw_segment") or ""),
            "categoria":   str(ref.get("categoria") or ""),
            "responsable": str(ref.get("responsable") or _default_resp),
            "fecha":       str(ref.get("fecha") or _date.today().isoformat()),
            "moneda":      str(ref.get("moneda") or "USD"),
            "itbms":       "sí" if ref.get("itbms") else "no",
            "metodo_pago": str(ref.get("metodo_pago") or ""),
        }
        # Only keep fields that are in edit_fields
        form_values = {k: pre_values[k] for k in edit_fields if k in pre_values}

        intent = "confirm" if not is_multi else "multi_add"
        ctx_id = session.get("context_id", new_context_id())
        return make_chat_core_response(
            domain="FIN",
            intent=intent,
            mode="chat",
            needs_confirmation=True,
            plan=plan,
            ui_actions=[
                UIAction(
                    type="form",
                    label="Revisa y edita antes de confirmar" if not is_multi
                          else f"Revisión global — {len(plan)} gastos detectados",
                    fields=edit_fields,
                    values=form_values,
                ),
                UIAction(type="confirm", label="Confirmar"),
            ],
            session=ChatSession(
                pending_flow="fin_confirm",
                context_id=ctx_id,
                last_domain="FIN",
                pending_data={"items": plan},
            ),
            audit={
                "summary": action_plan.get("summary_text", ""),
                "clarifications": [q["field"] for q in clarifications],
                "multi": is_multi,
            },
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
    """Process WORK domain input. Routes by classifier operation (M26-B)."""
    operation = classify_result.get("operation")
    ctx_id = session.get("context_id", new_context_id())

    # --- DELETE ---
    if operation == OP_WORK_DELETE:
        from .parsers.work_delete_parser import parse_work_delete_intent
        delete_parse = parse_work_delete_intent(text)
        dq = delete_parse.get("query") or {}
        keywords: list[str] = dq.get("keywords", [])
        delete_all: bool = dq.get("delete_all", False)

        # Fallback: extract after "tarea" if parser returned nothing
        if not keywords and not delete_all:
            m = re.search(r"\btareas?\s+(.+)", text, re.IGNORECASE)
            if m:
                raw = m.group(1).strip().rstrip(".,;:")
                if raw:
                    keywords = [raw]

        display_items = (
            [{"title": kw, "operation": "delete"} for kw in keywords]
            if keywords
            else [{"title": "todas las tareas" if delete_all else text, "operation": "delete"}]
        )
        label = "Eliminar tarea" + ("s" if len(display_items) > 1 or delete_all else "")
        return make_chat_core_response(
            domain="WORK",
            intent="delete",
            mode="chat",
            needs_confirmation=True,
            plan=display_items,
            ui_actions=[UIAction(type="confirm", label=label)],
            session=ChatSession(
                pending_flow="work_confirm",
                context_id=ctx_id,
                last_domain="WORK",
                pending_data={
                    "items": display_items,
                    "operation": "delete",
                    "keywords": keywords,
                    "delete_all": delete_all,
                },
            ),
            audit={"raw_text": text, "operation": operation, "keywords": keywords, "delete_all": delete_all},
        )

    # --- UPDATE ---
    if operation == OP_WORK_UPDATE:
        parsed = classify_result.get("parsed", {}) or {}
        target = parsed.get("title") or parsed.get("target") or text
        work_item = {"title": target, "operation": "update", "parsed": parsed}
        return make_chat_core_response(
            domain="WORK",
            intent="update",
            mode="chat",
            needs_confirmation=True,
            plan=[work_item],
            ui_actions=[UIAction(type="confirm", label="Actualizar tarea")],
            session=ChatSession(
                pending_flow="work_confirm",
                context_id=ctx_id,
                last_domain="WORK",
                pending_data={"items": [work_item], "operation": "update"},
            ),
            audit={"raw_text": text, "operation": operation},
        )

    # --- CREATE (explicit or default) ---
    # Also handles WORK_QUERY that slipped through without is_work_query catching it
    if operation == "WORK_QUERY":
        return make_chat_core_response(
            domain="WORK",
            intent="query",
            mode="action",
            session=ChatSession(context_id=ctx_id, last_domain="WORK"),
            audit={"raw_text": text},
        )

    # --- CREATE (explicit or default) ---
    # Parse single title or comma-separated bulk list
    titles = _parse_bulk_work_items(text)
    work_items = [{"title": t, "status": "INBOX"} for t in titles]
    is_bulk = len(work_items) > 1
    label = f"Crear {len(work_items)} tareas" if is_bulk else "Crear tarea"
    return make_chat_core_response(
        domain="WORK",
        intent="add",
        mode="chat",
        needs_confirmation=True,
        plan=work_items,
        ui_actions=[UIAction(type="confirm", label=label)],
        session=ChatSession(
            pending_flow="work_confirm",
            context_id=ctx_id,
            last_domain="WORK",
            pending_data={"items": work_items},
        ),
        audit={"raw_text": text, "operation": operation, "bulk": is_bulk, "count": len(work_items)},
    )


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "process_chat_input",
    "parse_action",
    "register_pending_flow_resolver",
    "PENDING_FLOW_RESOLVERS",
    "STRUCTURED_ACTION_TYPES",
]
