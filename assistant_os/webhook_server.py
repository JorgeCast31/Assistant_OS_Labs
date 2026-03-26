"""
Webhook Server - HTTP endpoint para Assistant OS.
Usa solo stdlib: http.server, json.
"""
from .type_aliases import Headers, HttpResponse, JsonResponse, JsonErrorResponse, ReadBodyResult, AuthErrorResponse
# Shared utilities (re-imported here so existing @patch paths remain valid)
from .webhook_utils import _make_json_error, _log_webhook_event, _log_fin_expense_event
import json
import logging
import re
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Optional

from .config import (
    WEBHOOK_TOKEN,
    WEBHOOK_HOST,
    WEBHOOK_PORT,
    WEBHOOK_MAX_BYTES,
    WEBHOOK_MAX_BYTES_RECEIPT,
    WEBHOOK_INCLUDE_RAW_DEFAULT,
    ASSISTANT_API_TOKEN,
    LOG_FILE,
    MEMORY_DIR,
    SHEETS_TAB_NAME,
    NOTION_WORK_DB_ID,
    NOTION_TOKEN,
    WORKSPACE_ROOT,
    CODEOPS_MAX_BYTES,
    CODEOPS_LIVE_MODE,
    is_repo_allowed,
    is_path_in_workspace,
)
from .router import parse_command_to_request, route_request
from .contracts import Response, new_context_id, now_iso, ClassifyRequest, ClassifyResponse, ChatSession, ChatCoreResponse
from .contracts import (
    Plan, make_plan, should_auto_execute,
    ACTION_WORK_QUERY, ACTION_WORK_CREATE, ACTION_WORK_UPDATE, ACTION_WORK_UPDATE_BULK,
    ACTION_FIN_EXPENSE, ACTION_COMMAND, ACTION_UNKNOWN,
    ACTION_WORK_CREATE_TEST, ACTION_WORK_TEST_RESET, ACTION_WORK_DELETE, ACTION_WORK_DELETE_TEST,
    TARGET_DB_WORK, TARGET_DB_WORK_TEST, TARGET_DB_WORK_TRASH,
    DELETE_MODE_TRASH, DELETE_MODE_ARCHIVE,
    RISK_LOW, RISK_MEDIUM, RISK_HIGH,
    # PolicyDecision v1
    build_policy_decision, EXECUTION_MODE_AUTO,
    # DomainResult v1
    DomainResult, make_domain_result,
    RESULT_TYPE_WORK_QUERY, RESULT_TYPE_WORK_CREATE, RESULT_TYPE_WORK_UPDATE,
    RESULT_TYPE_WORK_UPDATE_PREVIEW, RESULT_TYPE_WORK_UPDATE_BULK, RESULT_TYPE_WORK_DELETE,
    RESULT_TYPE_FIN_EXPENSE, RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED, RESULT_TYPE_PLAN_GENERATED,
    # CanonicalRequest v1
    normalize_request,
)
from .summary import summarize
from .context_store import store_pending_plan, get_pending_plan, remove_pending_plan
from .chat_ui import generate_chat_html
from .chat_core import process_chat_input
from .chat_renderer import render_chat_response
from . import chat_db
from .classifier import (
    classify_text,
    parse_work_query_filters,
    is_work_query,
)
from .contracts import OP_WORK_QUERY, OP_WORK_CREATE, OP_WORK_UPDATE, OP_WORK_DELETE, OP_FIN_EXPENSE, OP_COMMAND
from .fin_expense import parse_expense, ExpenseRequest, ExpenseResponse
from .chaperon import (
    run_chaperon,
    confirm_action_plan,
    update_session_context,
    SessionContext,
    ActionPlan,
    FinItem,
)
from .fin_plan import (
    generate_fin_plan,
    add_to_plan,
    FinPlanResponse,
    FinCommitRequest,
    FinCommitResponse,
    DraftExpense,
    PlanItem,
)
from .integrations.sheets import (
    append_expense_row,
    check_sheets_available,
    get_sheets_status,
    get_sheets_last_error,
)
from .integrations.notion import (
    query_work_db,
    format_work_query_response,
    check_notion_available,
    get_notion_status,
    get_database_schema,
    WorkQueryFilters,
    create_work_item,
    WorkCreateRequest,
    WorkCreateResult,
    get_work_item_by_id,
    search_work_items_by_title,
    search_work_items_with_filters,
    get_editable_field_options,
    update_work_item,
    WorkUpdateResult,
)
from .integrations.schema_ops import (
    generate_schema_plan,
    commit_schema_changes,
    SchemaPlanRequest,
)
from .codeops import (
    CodeOpsHandler,
    TaskSpec,
    PlanResponse,
    PRResponse,
    validate_task_spec,
)
from .parsers.work_delete_parser import (
    has_delete_intent,
    parse_work_delete_intent,
    generate_delete_preview,
)
from .parsers.work_update_parser import (
    parse_work_update_intent,
    has_update_intent,
    generate_update_preview,
    UpdateParseResult,
    ProposedChange,
)

# Module-level variables for patching in tests
NOTION_WORK_TRASH_DB_ID: str | None = None  # Set via environment or config later
NOTION_WORK_TEST_DB_ID: str | None = None   # Test database ID for mocking

_log = logging.getLogger(__name__)


def create_work_item_in_db(db_id: str, request: WorkCreateRequest) -> WorkCreateResult:
    """
    Wrapper for creating work items in Notion.
    Exists as a separate function for mocking in tests.
    
    Args:
        db_id: Target database ID
        request: WorkCreateRequest
    
    Returns:
        WorkCreateResult
    """
    # Use the imported create_work_item from integrations.notion
    return create_work_item(request)


# ---------------------------------------------------------------------------
# Test Intent Detection
# ---------------------------------------------------------------------------

# Test indicators in text
_TEST_INTENT_PATTERNS = [
    re.compile(r"\bui\s*test\b", re.IGNORECASE),
    re.compile(r"\btarea\s+de\s+prueba\b", re.IGNORECASE),
    re.compile(r"\bsmoke\s*test\b", re.IGNORECASE),
    re.compile(r"\btest\s+task\b", re.IGNORECASE),
]

# Title prefixes that indicate test tasks
_TEST_TITLE_PREFIXES = ["UI ", "Test ", "TEST_"]

# Reset intent patterns  
_TEST_RESET_PATTERNS = [
    re.compile(r"\b(?:reset(?:ear)?|wipe|limpiar|borrar|eliminar)\s+(?:tests?|pruebas?|tareas?\s+de\s+prueba)\b", re.IGNORECASE),
    re.compile(r"\b(?:tests?|pruebas?)\s+(?:reset(?:ear)?|wipe|limpiar|borrar|eliminar)\b", re.IGNORECASE),
]


def _has_test_intent(text: str, parsed_fields: dict | None = None) -> bool:
    """
    Detect if text indicates a TEST task (should go to work_test DB).
    
    Checks:
    1. Keywords in text: 'ui test', 'tarea de prueba', 'smoke test'
    2. Title prefixes in parsed_fields: 'UI ', 'Test ', 'TEST_'
    
    Args:
        text: Raw input text
        parsed_fields: Optional dict with parsed title field
    
    Returns:
        True if test intent detected
    """
    # Check patterns in text
    for pattern in _TEST_INTENT_PATTERNS:
        if pattern.search(text):
            return True
    
    # Check title prefix if parsed_fields provided
    if parsed_fields:
        title = parsed_fields.get("title", "")
        if title:
            for prefix in _TEST_TITLE_PREFIXES:
                if title.startswith(prefix):
                    return True
    
    return False


def _has_test_reset_intent(text: str) -> bool:
    """
    Detect if text indicates a TEST RESET/WIPE intent.
    
    Patterns:
    - 'resetear tests', 'reset tests', 'wipe tests'
    - 'limpiar pruebas', 'borrar tests', 'eliminar tareas de prueba'
    
    Args:
        text: Raw input text
    
    Returns:
        True if reset intent detected
    """
    for pattern in _TEST_RESET_PATTERNS:
        if pattern.search(text):
            return True
    return False


# Invalid title patterns - titles that are just keywords or punctuation
_INVALID_TITLE_PATTERNS = [
    re.compile(r"^(prueba|test|tarea|task)[:.\s]*$", re.IGNORECASE),
    re.compile(r"^[:.\s]+$"),  # Just punctuation
    re.compile(r"^(de\s+)?(prueba|test)[:.\s]*$", re.IGNORECASE),
]


def _is_invalid_title(title: str) -> bool:
    """
    Check if a title is invalid (just keywords/punctuation, not real content).
    
    Examples of invalid titles:
    - "prueba:"
    - "test"
    - ":"
    - "de prueba:"
    
    Args:
        title: Title string to validate
    
    Returns:
        True if title is invalid
    """
    title = title.strip()
    if not title:
        return True
    
    for pattern in _INVALID_TITLE_PATTERNS:
        if pattern.match(title):
            return True
    
    return False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# _log_webhook_event is imported from webhook_utils above.


def _log_classify_event(
    remote: str,
    ok: bool,
    text_len: int = 0,
    domain: str = "",
    confidence: float = 0.0,
    needs_confirmation: bool = False,
    conversation_id: str = "",
    text_preview: str = "",
) -> None:
    """Log a classify event (type=classify)."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    event: dict = {
        "ts": now_iso(),
        "type": "classify",
        "remote": remote,
        "ok": ok,
        "text_len": text_len,
    }
    
    if ok:
        event["domain"] = domain
        event["confidence"] = confidence
        event["needs_confirmation"] = needs_confirmation
    
    if conversation_id:
        event["conversation_id"] = conversation_id
    
    # Include text preview (max 120 chars, never full text)
    if text_preview:
        event["text_preview"] = text_preview[:120] if len(text_preview) > 120 else text_preview
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# _log_fin_expense_event is imported from webhook_utils above.


def _log_chat_message(
    remote: str,
    conversation_id: str,
    text: str,
    context_id: str = "",
) -> None:
    """Log a user chat message (type=chat_message, role=user)."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    # Limit text preview to 120 chars
    text_preview = text[:120] if len(text) > 120 else text
    
    event: dict = {
        "ts": now_iso(),
        "type": "chat_message",
        "conversation_id": conversation_id,
        "role": "user",
        "remote": remote,
        "text_len": len(text),
        "text_preview": text_preview,
        "context_id": context_id,
    }
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _log_chat_response(
    remote: str,
    conversation_id: str,
    ok: bool,
    agent: str,
    title: str,
    summary: str,
    context_id: str,
    error_type: str = "",
    error_message: str = "",
) -> None:
    """Log an assistant chat response (type=chat_response, role=assistant)."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    # Limit summary preview to 200 chars
    summary_preview = summary[:200] if len(summary) > 200 else summary
    
    event: dict = {
        "ts": now_iso(),
        "type": "chat_response",
        "conversation_id": conversation_id,
        "role": "assistant",
        "remote": remote,
        "ok": ok,
        "agent": agent,
        "title": title,
        "summary_preview": summary_preview,
        "context_id": context_id,
    }
    
    # Include error info only if not ok
    if not ok and error_type:
        event["error_type"] = error_type
        event["error_message"] = error_message[:200] if len(error_message) > 200 else error_message
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _log_codeops_event(
    remote: str,
    endpoint: str,
    ok: bool,
    repo: str = "",
    goal: str = "",
    context_id: str = "",
    warnings: list[str] | None = None,
    pr_url: str = "",
    error_message: str = "",
) -> None:
    """Log a CodeOps event (type=codeops)."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    # Limit goal preview to 100 chars
    goal_preview = goal[:100] if len(goal) > 100 else goal
    
    event: dict = {
        "ts": now_iso(),
        "type": "codeops",
        "remote": remote,
        "endpoint": endpoint,
        "ok": ok,
        "repo": repo,
        "goal_preview": goal_preview,
    }
    
    if context_id:
        event["context_id"] = context_id
    
    if warnings:
        event["warnings"] = warnings[:5]  # Max 5 warnings in log
    
    if pr_url:
        event["pr_url"] = pr_url
    
    if error_message:
        event["error"] = error_message[:200] if len(error_message) > 200 else error_message
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _read_chat_history(conversation_id: str, limit: int = 50) -> list[dict]:
    """
    Read chat history for a conversation from log.ndjson.
    
    Args:
        conversation_id: The conversation to filter by
        limit: Max number of items to return (capped at 200)
    
    Returns:
        List of chat items in chronological order (oldest first)
    """
    if limit > 200:
        limit = 200
    
    if not LOG_FILE.exists():
        return []
    
    items: list[dict] = []
    
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Filter by conversation_id and relevant types
                if event.get("conversation_id") != conversation_id:
                    continue
                
                event_type = event.get("type", "")
                
                if event_type == "chat_message" and event.get("role") == "user":
                    items.append({
                        "ts": event.get("ts", ""),
                        "role": "user",
                        "text": event.get("text_preview", ""),
                        "context_id": event.get("context_id", ""),
                    })
                elif event_type == "chat_response" and event.get("role") == "assistant":
                    items.append({
                        "ts": event.get("ts", ""),
                        "role": "assistant",
                        "title": event.get("title", ""),
                        "summary": event.get("summary_preview", ""),
                        "details": None,  # Not stored in logs
                        "context_id": event.get("context_id", ""),
                    })
    except Exception:
        return []
    
    # Return last N items in chronological order
    return items[-limit:]


# ---------------------------------------------------------------------------
# Response Helpers
# ---------------------------------------------------------------------------

# _make_json_error is imported from webhook_utils above; re-exposed here for
# backward compatibility with any direct references inside this module.



def _wrap_work_result(dr: "DomainResult", context_id: str) -> dict:
    """
    Wrap a DomainResult into the current Response transport format for WORK domain.

    DomainResult v1 transport adapter — sits between the domain pipeline and the
    HTTP Response until the full ExecutionResult migration happens.

    Output structure:
    - Canonical DomainResult fields: ok, result_type, domain, message, data
    - Backward-compat: all data keys promoted to top level (summary.py reads these)
    - Backward-compat: "type" at top level (summary.py branches on output.get("type"))
    - Transport fields: context_id, agent, status, error, ts

    Invariants preserved:
    - status="ok"    when dr["ok"] is True
    - status="error" when dr["ok"] is False
    - top-level error matches dr["error"]
    """
    data = dr.get("data") or {}
    output: dict = {
        # Backward-compat: promote all data fields to top level.
        # summary.py reads output.get("items"), output.get("total"), etc.
        **data,
        # DomainResult v1 canonical fields (may overwrite data keys of same name).
        "ok": dr["ok"],
        "result_type": dr["result_type"],
        "domain": dr["domain"],
        "message": dr["message"],
        "data": data,
        # "type" stays at top level for summary.py and chat_ui.py backward compat.
        # It mirrors the legacy type string stored in data["type"] when present,
        # otherwise falls back to result_type (for handlers that didn't set a
        # legacy type separately from result_type).
        "type": data.get("type") or dr["result_type"],
    }
    if dr.get("warnings"):
        output["warnings"] = dr["warnings"]
    return {
        "context_id": context_id,
        "agent": "work",
        "status": "ok" if dr["ok"] else "error",
        "output": output,
        "error": dr.get("error"),
        "ts": now_iso(),
    }


def _adapt_result_to_response(dr: "DomainResult", context_id: str) -> dict:
    """
    Convert a DomainResult from orchestrator.handle_request into the legacy Response shape.

    This is the sole transport adapter between the kernel and the HTTP layer.
    Dispatches by domain first, then by result_type for non-domain cases.
    """
    domain = dr.get("domain", "UNKNOWN")
    result_type = dr.get("result_type", "")

    if domain == "WORK":
        return _wrap_work_result(dr, context_id)

    if domain == "FIN":
        data = dr.get("data", {})
        return {
            "context_id": context_id,
            "agent": "fin",
            "status": "ok" if dr["ok"] else "error",
            "output": data,
            "error": dr.get("error"),
            "ts": now_iso(),
        }

    if result_type == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED:
        return {
            "context_id": context_id,
            "agent": "interpreter",
            "status": "pending",
            "output": dr.get("data", {}),
            "error": None,
            "ts": now_iso(),
        }

    if result_type == RESULT_TYPE_PLAN_GENERATED:
        return {
            "context_id": context_id,
            "agent": "classifier",
            "status": "ok",
            "output": dr.get("data", {}),
            "error": None,
            "ts": now_iso(),
        }

    # Fallback: unknown domain/result_type
    return {
        "context_id": context_id,
        "agent": "kernel",
        "status": "ok" if dr["ok"] else "error",
        "output": dr.get("data", {}),
        "error": dr.get("error"),
        "ts": now_iso(),
    }


# ---------------------------------------------------------------------------
# Standalone domain execution functions (return DomainResult)
#
# These contain the pure domain logic extracted from WebhookHandler methods.
# The handler methods below are thin wrappers that call these + _wrap_work_result.
# The orchestrator (core/orchestrator.py) calls these directly, bypassing the
# HTTP handler layer entirely.
# ---------------------------------------------------------------------------

def _work_query_execute(plan: "Plan", context_id: str) -> "DomainResult":
    """Execute a WORK query and return DomainResult (no transport wrapping)."""
    filters = plan.get("filters", {})

    if not check_notion_available():
        notion_status = get_notion_status()
        error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_QUERY,
            domain="WORK",
            message="Notion no está disponible.",
            data={"plan": dict(plan)},
            error={"type": "NotionUnavailable", "message": error_msg},
        )

    result = query_work_db(filters=filters, limit=20)
    formatted = format_work_query_response(result)
    total = result.get("total", 0)

    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_WORK_QUERY,
        domain="WORK",
        message=f"Se encontraron {total} tarea(s)." if total > 0 else "No se encontraron tareas.",
        data={
            "type": "work_query",
            "items": result.get("items", []),
            "total": total,
            "formatted": formatted,
            "filters": filters,
            "plan": dict(plan),
        },
        trace_id=plan.get("trace_id"),
        plan_id=plan.get("plan_id"),
    )



def _work_update_preview_execute(plan: "Plan", context_id: str, text: str) -> "DomainResult":
    """
    Execute WORK_UPDATE Phase 1 and return DomainResult (no transport wrapping).

    Resolves the target item using project-first resolution, reads current values,
    and returns a proposal DomainResult with valid options.

    Resolution priority:
    1. explicit title/keywords
    2. project (primary anchor)
    3. status
    4. domain (context, not primary identifier)
    """
    filters = plan.get("filters", {})
    changes = filters.get("changes", [])
    keywords = filters.get("keywords", [])

    hint_project = filters.get("hint_project")
    hint_domain = filters.get("hint_domain")
    hint_status = filters.get("hint_status")

    # Check Notion availability
    if not check_notion_available():
        notion_status = get_notion_status()
        error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message="Notion no está disponible.",
            data={"plan": dict(plan)},
            error={"type": "NotionUnavailable", "message": error_msg},
        )

    # Get editable field options first (for validation and response)
    options_result = get_editable_field_options()
    editable_options = options_result if options_result.get("ok") else {"options": {"domain": [], "project": [], "status": []}}
    real_options = editable_options.get("options", {})

    # Validate hint_project against real Notion options
    valid_projects = [p.lower() for p in real_options.get("project", [])]
    if hint_project and hint_project.lower() not in valid_projects:
        hint_project_lower = hint_project.lower()
        matched_project = None
        for p in real_options.get("project", []):
            if hint_project_lower in p.lower() or p.lower() in hint_project_lower:
                matched_project = p
                break
        hint_project = matched_project

    # Validate hint_domain against real Notion options
    valid_domains = [d.lower() for d in real_options.get("domain", [])]
    if hint_domain and hint_domain.lower() not in valid_domains:
        hint_domain = None

    # Validate hint_status against real Notion options
    valid_statuses = [s.lower() for s in real_options.get("status", [])]
    if hint_status and hint_status.lower() not in valid_statuses:
        hint_status = None

    # FIX 1: Project-first resolution
    search_keywords = keywords if keywords else None
    if search_keywords and hint_project:
        keywords_lower = [kw.lower() for kw in search_keywords]
        if hint_project.lower() in keywords_lower:
            search_keywords = None

    # Try search with all available hints (most specific)
    search_result = search_work_items_with_filters(
        keywords=search_keywords,
        project=hint_project,
        domain=hint_domain,
        status=hint_status,
        limit=5,
    )

    if not search_result.get("ok"):
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message="Error buscando tareas en Notion.",
            data={"plan": dict(plan)},
            error={"type": "SearchError", "message": search_result.get("error", "Error buscando ítems")},
        )

    matches = search_result.get("items", [])

    # Progressively looser searches on no-match
    if len(matches) == 0 and hint_project:
        search_result = search_work_items_with_filters(
            keywords=search_keywords,
            project=hint_project,
            limit=5,
        )
        if search_result.get("ok"):
            matches = search_result.get("items", [])

    if len(matches) == 0 and search_keywords:
        search_result = search_work_items_by_title(search_keywords, limit=5)
        if search_result.get("ok"):
            matches = search_result.get("items", [])

    if len(matches) == 0:
        synced_plan = dict(plan)
        synced_plan["requires_confirmation"] = False
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message="No se encontró ninguna tarea que coincida con la búsqueda.",
            data={
                "type": "work_update_proposal",
                "context_id": context_id,
                "resolved": False,
                "reason": "no_match",
                "match_count": 0,
                "matches": [],
                "search_context": {
                    "keywords": keywords,
                    "hint_project": hint_project,
                    "hint_domain": hint_domain,
                    "hint_status": hint_status,
                },
                "editable_fields": ["domain", "project", "status"],
                "options": editable_options,
                "requires_confirmation": False,
                "plan": synced_plan,
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    elif len(matches) == 1:
        item = matches[0]
        page_id = item.get("notion_page_id")
        full_item_result = None
        if page_id is not None:
            full_item_result = get_work_item_by_id(page_id)

        if not full_item_result.get("ok"):
            return make_domain_result(
                ok=False,
                result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
                domain="WORK",
                message="Error leyendo los detalles de la tarea.",
                data={"plan": dict(plan)},
                error={"type": "ItemReadError", "message": full_item_result.get("error", "Error leyendo ítem")},
            )

        full_item = full_item_result.get("item", {})
        preview_text = ""
        if full_item and isinstance(full_item, dict):
            preview_text = generate_update_preview(changes, full_item.get("title", ""))

        current_values = {}
        if full_item and isinstance(full_item, dict):
            current_values = {
                "domain": full_item.get("domain"),
                "project": full_item.get("project"),
                "status": full_item.get("status"),
            }

        synced_plan = dict(plan)
        synced_plan["requires_confirmation"] = True
        synced_plan["filters"] = {
            "notion_page_id": page_id,
            "current_values": current_values,
            "proposed_changes": changes,
            "title": "",
        }
        if full_item and isinstance(full_item, dict):
            synced_plan["filters"]["title"] = full_item.get("title", "")

        proposal_output = {
            "type": "work_update_proposal",
            "context_id": context_id,
            "resolved": True,
            "risk_level": "RISK_LOW",
            "match_count": 1,
            "notion_page_id": page_id,
            "title": "",
            "current_values": current_values,
            "proposed_changes": changes,
            "preview": preview_text,
            "editable_fields": ["domain", "project", "status"],
            "options": editable_options,
            "requires_confirmation": True,
            "plan": synced_plan,
        }
        if full_item and isinstance(full_item, dict):
            proposal_output["title"] = full_item.get("title", "")

        store_pending_plan(
            context_id=context_id,
            plan=synced_plan,
            operation=OP_WORK_UPDATE,
            raw_text=text,
        )

        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message=proposal_output.get("preview") or "Tarea encontrada y lista para actualizar.",
            data=proposal_output,
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    else:
        # BULK: Multiple matches - return explicit bulk proposal
        enriched_matches = [
            {
                "notion_page_id": m.get("notion_page_id"),
                "title": m.get("title"),
                "domain": m.get("domain"),
                "project": m.get("project"),
                "status": m.get("status"),
            }
            for m in matches
        ]
        candidate_objs = [
            {"title": m.get("title"), "status": m.get("status")}
            for m in matches
        ]
        preview_text = generate_update_preview(changes, "") if changes else f"Actualizar {len(matches)} tareas"

        synced_plan = dict(plan)
        synced_plan["action"] = ACTION_WORK_UPDATE_BULK
        synced_plan["requires_confirmation"] = True
        synced_plan["matches"] = enriched_matches
        synced_plan["selected_notion_page_ids"] = []
        synced_plan["applied_changes"] = {}
        if "filters" in synced_plan:
            synced_plan["filters"] = dict(synced_plan["filters"])
            synced_plan["filters"]["ambiguous"] = True

        store_pending_plan(
            context_id=context_id,
            plan=synced_plan,
            operation=OP_WORK_UPDATE,
            raw_text=text,
        )

        bulk_proposal_data = {
            "type": "work_update_bulk_proposal",
            "context_id": context_id,
            "resolved": False,
            "total": len(matches),
            "match_count": len(matches),
            "preview": preview_text,
            "candidates": candidate_objs,
            "matches": enriched_matches,
            "message": f"Se encontraron {len(matches)} tareas. Selecciona cuáles quieres actualizar.",
            "editable_fields": ["domain", "project", "status"],
            "options": editable_options,
            "requires_confirmation": True,
            "plan": synced_plan,
        }
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message=f"Se encontraron {len(matches)} tareas. Selecciona cuáles quieres actualizar.",
            data=bulk_proposal_data,
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )


def _safe_parse_json(body: bytes) -> tuple[Optional[JsonResponse], Optional[JsonErrorResponse]]:
    """
    Parse JSON from bytes with robust UTF-8 handling.
    
    Returns:
        (parsed_dict, None) on success
        (None, (status_code, error_response)) on failure
    """
    # Try UTF-8 decoding first
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as e:
        # Provide safe snippet of body for debugging
        snippet = body[:50].decode("utf-8", errors="replace")
        message = f"UTF-8 decode error: {e}. Body snippet: {snippet!r}"
        return None, _make_json_error(400, message, "EncodingError")
    
    # Parse JSON
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None, _make_json_error(400, "Request body must be a JSON object", "BadRequest")
        return data, None
    except json.JSONDecodeError as e:
        # Provide snippet for context
        snippet = text[:100] if len(text) > 100 else text
        message = f"Invalid JSON at line {e.lineno} col {e.colno}: {e.msg}. Snippet: {snippet!r}"
        return None, _make_json_error(400, message, "InvalidJSON")


# Regex para detectar prefijo válido (CODE:, DOC:, JOBS:, BIZ:)
import re
_COMMAND_PREFIX_PATTERN = re.compile(r"^\s*(CODE|DOC|JOBS|BIZ)\s*:", re.IGNORECASE)
# Regex para detectar cualquier patrón que parezca prefijo (WORD:)
_ANY_PREFIX_PATTERN = re.compile(r"^\s*[A-Z]+\s*:", re.IGNORECASE)


def _has_command_prefix(text: str) -> bool:
    """Check if text starts with a valid command prefix (CODE:, DOC:, JOBS:, BIZ:)."""
    return bool(_COMMAND_PREFIX_PATTERN.match(text.strip()))


def _has_invalid_prefix(text: str) -> bool:
    """Check if text looks like it has a prefix (WORD:) but it's not a valid one."""
    text = text.strip()
    # Looks like a prefix pattern but isn't a valid one
    return bool(_ANY_PREFIX_PATTERN.match(text)) and not bool(_COMMAND_PREFIX_PATTERN.match(text))


# ---------------------------------------------------------------------------
# Deterministic Routing Override Table
# ---------------------------------------------------------------------------

# Pattern for WORK_CREATE intent (creation verbs + tarea)
# This has HIGHER priority than WORK_QUERY patterns
_WORK_CREATE_INTENT_PATTERN = re.compile(
    r"\b(crea|crear|añade|añadir|agrega|agregar|insertar?|registrar?|mete|meter|nueva?)\b"
    r".*\btareas?\b",
    re.IGNORECASE
)

# Alternative: tarea + creation verb (reversed order)
_WORK_CREATE_INTENT_REVERSED_PATTERN = re.compile(
    r"\btareas?\b.*\b(crea|crear|añade|añadir|agrega|agregar|insertar?|registrar?|mete|meter|nueva?)\b",
    re.IGNORECASE
)


def _has_create_intent(text: str) -> bool:
    """
    Detect if text expresses intent to CREATE a task (vs query tasks).
    
    Creation verbs: crea, crear, añade, agrega, insertar, registrar, mete, nueva
    Must be combined with "tarea(s)".
    
    Examples that match:
    - "Crea una tarea para llamar al banco"
    - "Añade tarea de revisar informe"
    - "Nueva tarea: reunión con cliente"
    
    Examples that DON'T match:
    - "tareas de consultoria?"
    - "estado sobre tareas"
    - "muéstrame las tareas pendientes"
    
    Returns:
        True if creation intent detected
    """
    return bool(
        _WORK_CREATE_INTENT_PATTERN.search(text) or
        _WORK_CREATE_INTENT_REVERSED_PATTERN.search(text)
    )


# Patterns for WORK_QUERY override (these always route to WORK_QUERY regardless of domain)
_WORK_QUERY_OVERRIDE_PATTERNS = [
    re.compile(r"\btareas?\b", re.IGNORECASE),
    re.compile(r"\bestado\s+(sobre\s+)?tareas?\b", re.IGNORECASE),
    re.compile(r"\bqu[eé]\s+hay\s+pendiente\b", re.IGNORECASE),
    re.compile(r"\bqu[eé]\s+tengo\s+pendiente\b", re.IGNORECASE),
    re.compile(r"\bpendientes?\b", re.IGNORECASE),
    re.compile(r"\bpr[oó]xim[ao]s?\s+tareas?\b", re.IGNORECASE),
]


def _apply_routing_overrides(text: str, intent: dict) -> tuple[str, str]:
    """
    Apply deterministic routing overrides BEFORE classification-based routing.
    
    Override table rules (highest priority wins):
    0. Reset intent → ACTION_WORK_TEST_RESET (highest priority)
    1. Delete intent → ACTION_WORK_DELETE / ACTION_WORK_DELETE_TEST
    2. Test create intent → ACTION_WORK_CREATE_TEST
    3. Normal create intent → ACTION_WORK_CREATE
    4. Query patterns → ACTION_WORK_QUERY
    
    Returns:
        (action_override, override_reason) or ("", "") if no override
    """
    # Rule 0 (HIGHEST PRIORITY): Reset intent → WORK_TEST_RESET
    if _has_test_reset_intent(text):
        return (ACTION_WORK_TEST_RESET, "Override: reset intent detected")
    
    # Rule 1: Delete intent → WORK_DELETE / WORK_DELETE_TEST
    if has_delete_intent(text):
        # Check if targeting test DB
        delete_result = parse_work_delete_intent(text)
        query = delete_result.get("query")
        if query and isinstance(query, dict) and query.get("target_db") == "work_test":
            return (ACTION_WORK_DELETE_TEST, "Override: delete test intent detected")
        else:
            return (ACTION_WORK_DELETE, "Override: delete intent detected")
    
    # Rule 2: Test creation intent → WORK_CREATE_TEST
    if _has_create_intent(text) and _has_test_intent(text):
        return (ACTION_WORK_CREATE_TEST, "Override: test creation intent detected")
    
    # Rule 3: Normal creation intent → WORK_CREATE
    if _has_create_intent(text):
        return (ACTION_WORK_CREATE, "Override: creation intent detected (crea/añade/agrega + tarea)")
    
    # Rule 4: "tareas" or "estado sobre tareas" → WORK_QUERY override
    # BUT NOT if intent already determined this is an UPDATE operation
    # (classifier has priority for WORK_UPDATE since it uses more precise patterns)
    operation = intent.get("operation", "")
    if operation == OP_WORK_UPDATE:
        # Classifier detected update - don't override to query
        return ("", "")
    
    for pattern in _WORK_QUERY_OVERRIDE_PATTERNS:
        if pattern.search(text):
            return (ACTION_WORK_QUERY, f"Override: pattern '{pattern.pattern}' matched")
    
    return ("", "")


# ---------------------------------------------------------------------------
# Parse Work Create Fields
# ---------------------------------------------------------------------------

def parse_work_create_fields(text: str) -> dict:
    """
    Parse semi-structured text to extract task creation fields.
    
    Supports formats:
    - Single line with periods: "Título: X. Proyecto: Y. Status: Z."
    - Multi-line: "Título: X\\nProyecto: Y"
    - "Crea una tarea: <title>" → title from first line
    - "Título: X" or "Title: X" → title field
    - "Proyecto: X" or "Project: X" → project field
    - "Status: X" or "Estado: X" → status field
    - "Prioridad: X" or "Priority: X" → priority field (mapped to load)
    - "Carga cognitiva: X" or "Carga: X" or "Load: X" → load field (Alta/Media/Baja)
    - "Due: X" or "Entrega: X" or "Fecha: X" → due date
    - "Notas: X" or "Notes: X" → notes field
    
    Returns:
        dict with extracted fields: title, project, status, load, due, notes
        All fields are optional except title which is required.
    """
    fields: dict = {
        "title": "",
        "project": None,
        "status": None,
        "load": None,
        "priority": None,  # Prioridad field (P1/P2/P3)
        "due": None,
        "notes": None,
    }
    
    text = text.strip()
    
    # Pattern matchers for structured fields (key: value) with non-greedy capture
    # Stop at next field marker (". Campo:") or end of string
    # These are checked FIRST before fallback to creation pattern
    field_patterns = [
        # Title: stop at ". <next_field_name>:" pattern
        (r"(?:t[ií]tulo|title)\s*:\s*(.+?)(?=\.\s+(?:proyecto|project|status|estado|prioridad|priority|carga(?:\s+cognitiva)?|load|due|entrega|fecha|notas?|notes?)\s*:|\.\s*$|$)", "title"),
        # Project: stop at next field or period+end
        (r"(?:proyecto|project)\s*:\s*(.+?)(?=\.\s+(?:status|estado|prioridad|priority|carga(?:\s+cognitiva)?|load|due|entrega|fecha|notas?|notes?)\s*:|\.\s*$|$)", "project"),
        # Status: stop at next field or period+end
        (r"(?:status|estado)\s*:\s*(.+?)(?=\.\s+(?:prioridad|priority|carga(?:\s+cognitiva)?|load|due|entrega|fecha|notas?|notes?)\s*:|\.\s*$|$)", "status"),
        # Priority: stop at next field (including "Carga cognitiva:")
        (r"(?:prioridad|priority)\s*:\s*(.+?)(?=\.\s+(?:carga(?:\s+cognitiva)?|load|due|entrega|fecha|notas?|notes?)\s*:|\.\s*$|$)", "priority"),
        # Carga cognitiva or Carga: stop at next field or period+end
        (r"(?:carga(?:\s+cognitiva)?|load)\s*:\s*(.+?)(?=\.\s+(?:due|entrega|fecha|notas?|notes?)\s*:|\.\s*$|$)", "load"),
        # Due: stop at next field or period+end
        (r"(?:due|entrega|fecha)\s*:\s*(.+?)(?=\.\s+(?:notas?|notes?)\s*:|\.\s*$|$)", "due"),
        # Notes: everything remaining
        (r"(?:notas?|notes?)\s*:\s*(.+?)$", "notes"),
    ]
    
    # FIRST: Parse explicit field patterns (Título:, Proyecto:, etc.)
    # These have highest priority because they're explicit field markers
    for pattern, field_name in field_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1).strip()
            # Remove trailing period if present
            value = value.rstrip('.')
            # Handle "null", "none", "sin fecha" as None
            if value.lower() in ("null", "none", "sin fecha", "n/a", "-"):
                fields[field_name] = None
            else:
                fields[field_name] = value
    
    # FALLBACK: If no explicit Título: field, try to extract from creation pattern
    # "Crea una tarea: <title>" or "Añade tarea de <title>"
    if not fields["title"]:
        title_match = re.search(
            r"(?:crea|crear|añade|añadir|agrega|agregar|nueva?)\s+"
            r"(?:una?\s+)?tarea[s]?\s*(?:de|para|:)?\s*(.+?)(?:\n|$)",
            text, re.IGNORECASE
        )
        if title_match:
            extracted_title = title_match.group(1).strip()
            # Don't use if it looks like prefix to explicit fields
            if not re.search(r"(?:t[ií]tulo|title|proyecto|project)\s*:", extracted_title, re.IGNORECASE):
                # Clean up any "en WORK:" prefix
                cleaned = re.sub(r"^en\s+\w+\s*:\s*", "", extracted_title, flags=re.IGNORECASE)
                if cleaned:
                    fields["title"] = cleaned
    
    # Map priority values to load if load not already set
    if fields.get("priority") and not fields.get("load"):
        priority_val = fields["priority"].upper()
        priority_to_load = {
            "P1": "Alta", "P2": "Media", "P3": "Baja",
            "ALTA": "Alta", "MEDIA": "Media", "BAJA": "Baja",
        }
        fields["load"] = priority_to_load.get(priority_val, "Media")
    
    # Normalize load values
    if fields.get("load"):
        load_val = fields["load"].lower()
        load_map = {
            "alta": "Alta", "high": "Alta", "urgente": "Alta",
            "media": "Media", "medium": "Media", "normal": "Media",
            "baja": "Baja", "low": "Baja",
        }
        fields["load"] = load_map.get(load_val, fields["load"])
    
    # Map common status values
    if fields.get("status"):
        status_val = fields["status"].lower().strip()
        status_map = {
            "inbox": "INBOX", "pendiente": "INBOX", "nuevo": "INBOX",
            "next": "NEXT", "siguiente": "NEXT",
            "scheduled": "SCHEDULED", "programada": "SCHEDULED",
            "waiting": "WAITING", "esperando": "WAITING",
            "done": "DONE", "terminada": "DONE", "completada": "DONE",
        }
        fields["status"] = status_map.get(status_val, fields["status"].upper())
    
    # Default status to INBOX if not specified
    if not fields.get("status"):
        fields["status"] = "INBOX"
    
    return fields


def _create_plan_from_intent(text: str, intent: dict) -> Plan:
    """
    Create a Plan from classified intent (Interpreter layer).
    
    This function translates the classified intent into a structured Plan
    without performing any execution (side effects).
    
    Args:
        text: Original user input
        intent: Classified intent from classify_text()
    
    Returns:
        Plan ready for confirmation or execution
    """
    domain = intent.get("domain", "UNKNOWN")
    operation = intent.get("operation", OP_COMMAND)
    confidence = intent.get("confidence", 0.0)
    alternatives = intent.get("alternatives", [])
    
    # Apply override rules first
    action_override, override_reason = _apply_routing_overrides(text, intent)
    
    if action_override:
        action = action_override
        reason = override_reason
    else:
        # Map operation to action (classifier-based routing)
        if operation == OP_WORK_QUERY:
            action = ACTION_WORK_QUERY
            reason = f"Classifier: operation={operation}"
        elif operation == OP_WORK_CREATE:
            action = ACTION_WORK_CREATE
            reason = f"Classifier: operation={operation}"
        elif operation == OP_WORK_UPDATE:
            action = ACTION_WORK_UPDATE
            reason = f"Classifier: operation={operation}"
        elif operation == OP_WORK_DELETE:
            action = ACTION_WORK_DELETE
            reason = f"Classifier: operation={operation}"
        elif operation == OP_FIN_EXPENSE:
            action = ACTION_FIN_EXPENSE
            reason = f"Classifier: operation={operation}"
        elif is_work_query(text, domain):
            action = ACTION_WORK_QUERY
            reason = f"Fallback: is_work_query=True for domain={domain}"
        else:
            action = ACTION_COMMAND
            reason = f"Classifier: domain={domain}, operation={operation}"
    
    # Determine risk level and target_db
    target_db = None
    validation_error = None
    
    if action == ACTION_WORK_QUERY:
        risk_level = RISK_LOW  # Read-only
        requires_confirmation = False
        target_db = TARGET_DB_WORK
    elif action == ACTION_WORK_CREATE:
        risk_level = RISK_MEDIUM  # Creates data in Notion
        requires_confirmation = True  # ALWAYS require confirmation for writes
        target_db = TARGET_DB_WORK
    elif action == ACTION_WORK_CREATE_TEST:
        risk_level = RISK_MEDIUM  # Creates data in test DB
        requires_confirmation = True
        target_db = TARGET_DB_WORK_TEST
    elif action == ACTION_WORK_TEST_RESET:
        risk_level = RISK_HIGH  # Destructive operation
        requires_confirmation = True
        target_db = TARGET_DB_WORK_TEST
    elif action == ACTION_WORK_DELETE:
        # Risk level determined AFTER parsing filters (see below)
        risk_level = RISK_MEDIUM  # Default, may be upgraded to HIGH for delete_all
        requires_confirmation = True
        target_db = TARGET_DB_WORK_TRASH
    elif action == ACTION_WORK_DELETE_TEST:
        # Risk level determined AFTER parsing filters (see below)
        risk_level = RISK_MEDIUM  # Default, may be upgraded to HIGH for delete_all
        requires_confirmation = True
        target_db = TARGET_DB_WORK_TEST
    elif action == ACTION_WORK_UPDATE:
        # WORK_UPDATE Phase 1: Preview only, no execution
        risk_level = RISK_LOW  # Phase 1 is read-only (preview only)
        requires_confirmation = False  # Returns preview directly
        target_db = TARGET_DB_WORK
    elif action == ACTION_FIN_EXPENSE:
        risk_level = RISK_MEDIUM  # Creates data
        requires_confirmation = False  # Single expense auto-executes
    else:
        risk_level = RISK_MEDIUM
        requires_confirmation = False
    
    # Parse filters based on action type
    filters = {}
    if action == ACTION_WORK_QUERY:
        filters = parse_work_query_filters(text)
    elif action == ACTION_WORK_CREATE:
        # For WORK_CREATE, filters contains the task fields
        filters = parse_work_create_fields(text)
        # Validate title is present and meaningful
        title = filters.get("title", "").strip()
        if not title or _is_invalid_title(title):
            validation_error = "Missing or invalid title: Debes especificar un título para la tarea"
    elif action == ACTION_WORK_CREATE_TEST:
        # For WORK_CREATE_TEST, filters contains the task fields
        filters = parse_work_create_fields(text)
        # Validate title is present and meaningful
        title = filters.get("title", "").strip()
        if not title or _is_invalid_title(title):
            validation_error = "Missing or invalid title: Debes especificar un título para la tarea de prueba"
    elif action in (ACTION_WORK_DELETE, ACTION_WORK_DELETE_TEST):
        # Parse delete intent for filters.
        # Bulk-delete pattern ("elimina todas las tareas done de consultoria") also
        # provides structured project/status filter criteria via the mutation parser.
        from .parsers.work_mutation_parser import is_bulk_delete, parse_mutation_intent as _parse_mutation
        delete_result = parse_work_delete_intent(text)
        query = delete_result.get("query", {})
        filters = {}
        if query and isinstance(query, dict):
            filters = {
                "keywords": query.get("keywords", []),
                "op": query.get("op", "OR"),
                "delete_all": query.get("delete_all", False),
                "include_next": query.get("include_next", False),
                "delete_mode": DELETE_MODE_ARCHIVE if action == ACTION_WORK_DELETE_TEST else DELETE_MODE_TRASH,
            }
        if is_bulk_delete(text):
            mutation = _parse_mutation(text)
            filters["filter_project"] = mutation.get("filter_project")
            filters["filter_status"] = mutation.get("filter_status")
        validation_error = delete_result.get("validation_error")
        # Upgrade risk level if delete_all is true
        if filters.get("delete_all"):
            risk_level = RISK_HIGH  # delete_all is HIGH risk
    elif action == ACTION_WORK_TEST_RESET:
        # Reset doesn't need detailed filters, but mark requires all
        filters = {"delete_all": True, "delete_mode": DELETE_MODE_ARCHIVE}
    elif action == ACTION_WORK_UPDATE:
        # Bulk intent ("marca todas las tareas de X como Y") → mutation parser.
        # Single-task intent ("pon la tarea de X en Y") → update parser.
        from .parsers.work_mutation_parser import is_bulk_update, parse_mutation_intent as _parse_mutation
        if is_bulk_update(text):
            filters = _parse_mutation(text)
            validation_error = None if filters.get("changes") else "No se detectó qué cambio aplicar."
        else:
            update_result = parse_work_update_intent(text)
            target = update_result.get("target", {})
            changes = update_result.get("changes", [])
            resolution_hints = update_result.get("resolution_hints", {})
            filters = {
                "keywords": target.get("keywords", []),
                "context_ref": target.get("context_ref"),
                "notion_page_id": target.get("notion_page_id"),
                "changes": [dict(c) for c in changes],
                "ambiguous": target.get("ambiguous", False),
                # Resolution hints for project-first resolution
                "hint_project": resolution_hints.get("project"),
                "hint_domain": resolution_hints.get("domain"),
                "hint_status": resolution_hints.get("status"),
            }
            validation_error = update_result.get("validation_error")
    
    # Build preview
    if action == ACTION_WORK_QUERY:
        filter_desc = []
        if filters.get("project"):
            filter_desc.append(f"proyecto={filters['project']}")
        if filters.get("status"):
            filter_desc.append(f"status={filters['status']}")
        preview = f"Consultar tareas" + (f" ({', '.join(filter_desc)})" if filter_desc else "")
    elif action == ACTION_WORK_CREATE:
        # Build confirmation preview with parsed fields
        title = filters.get("title", "(sin título)")
        project = filters.get("project", "(sin proyecto)")
        status = filters.get("status", "INBOX")
        preview_parts = [f"Crear tarea: \"{title}\""]
        if filters.get("project"):
            preview_parts.append(f"Proyecto: {project}")
        preview_parts.append(f"Status: {status}")
        if filters.get("load"):
            preview_parts.append(f"Carga: {filters['load']}")
        if filters.get("due"):
            preview_parts.append(f"Entrega: {filters['due']}")
        preview = " | ".join(preview_parts)
    elif action == ACTION_WORK_CREATE_TEST:
        # Similar to WORK_CREATE but for test DB
        title = filters.get("title", "(sin título)")
        preview = f"[TEST] Crear tarea: \"{title}\""
    elif action == ACTION_WORK_TEST_RESET:
        preview = "⚠️ Resetear TODAS las tareas de prueba (TEST DB)"
    elif action in (ACTION_WORK_DELETE, ACTION_WORK_DELETE_TEST):
        # Use the delete preview generator
        from .parsers.work_delete_parser import DeleteQuery
        query = DeleteQuery(
            keywords=filters.get("keywords", []),
            op=filters.get("op", "OR"),
            delete_all=filters.get("delete_all", False),
            target_db="work_test" if action == ACTION_WORK_DELETE_TEST else "work",
            include_next=filters.get("include_next", False)
        )
        preview = generate_delete_preview(query)
    elif action == ACTION_WORK_UPDATE:
        # Use the update preview generator
        changes = filters.get("changes", [])
        preview = generate_update_preview(changes, "")
    elif action == ACTION_FIN_EXPENSE:
        preview = f"Registrar gasto: {text[:50]}..."
    else:
        preview = f"Dominio {domain}: {intent.get('next_action', text[:50])}"
    
    return make_plan(
        domain=domain,
        action=action,
        target=text[:100],
        requires_confirmation=requires_confirmation,
        risk_level=risk_level,
        preview=preview,
        filters=filters,
        raw_text=text,
        confidence=confidence,
        alternatives=alternatives,
        target_db=target_db,
        validation_error=validation_error,
    )


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for /command endpoint."""

    # Server instance with shutdown flag
    server: "WebhookHTTPServer"

    _CORS_ORIGINS = {"http://localhost:3100", "http://127.0.0.1:3100"}

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default logging to stderr."""
        pass

    def _cors_origin(self) -> str:
        origin = self.headers.get("Origin", "")
        return origin if origin in self._CORS_ORIGINS else ""

    def do_OPTIONS(self) -> None:  # noqa: N802
        origin = self._cors_origin()
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Assistant-Token")
            self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json_response(self, status_code: int, data: JsonResponse) -> None:
        """Send JSON response with proper headers."""
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(body)
    
    def _get_remote_addr(self) -> str:
        """Get client address as string."""
        return f"{self.client_address[0]}:{self.client_address[1]}"
    
    def _check_auth(self) -> AuthErrorResponse:
        """Check authentication headers. Returns error response if invalid.
        
        Accepts either:
        - X-Assistant-Token: standard UI token (WEBHOOK_TOKEN)
        - X-Assistant-Admin-Token: admin API token (ASSISTANT_API_TOKEN, localhost only)
        """
        # Check standard UI token first
        token = self.headers.get("X-Assistant-Token", "")
        if token and token == WEBHOOK_TOKEN:
            return None
        
        # Check admin API token (localhost only)
        admin_token = self.headers.get("X-Assistant-Admin-Token", "")
        if admin_token:
            # Only allow admin token from localhost
            client_ip = self.client_address[0]
            if client_ip in ("127.0.0.1", "::1", "localhost"):
                if admin_token == ASSISTANT_API_TOKEN:
                    return None
                else:
                    return _make_json_error(401, "Invalid admin token", "Unauthorized")
            else:
                return _make_json_error(403, "Admin token only allowed from localhost", "Forbidden")
        
        # No valid token provided
        if not token:
            return _make_json_error(401, "Missing authentication header", "Unauthorized")
        return _make_json_error(401, "Invalid token", "Unauthorized")
    
    def _read_body(self, max_bytes: int = WEBHOOK_MAX_BYTES) -> ReadBodyResult:
        """Read request body. Returns (body, None) or (b'', error_response)."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > max_bytes:
            return b"", _make_json_error(413, f"Body too large (max {max_bytes} bytes)", "PayloadTooLarge")
        if content_length == 0:
            return b"", None
        body = self.rfile.read(content_length)
        return body, None
    
    def _parse_query_params(self) -> Headers:
        """Parse query parameters from path."""
        params: Headers = {}
        if "?" in self.path:
            query_string = self.path.split("?", 1)[1]
            for param in query_string.split("&"):
                if "=" in param:
                    key, value = param.split("=", 1)
                    params[key] = value
                else:
                    params[param] = "1"
        return params
    
    def _get_path_without_query(self) -> str:
        """Get path without query parameters."""
        return self.path.split("?", 1)[0]
    
    def do_POST(self) -> None:
        """Handle POST requests."""
        remote = self._get_remote_addr()
        path = self._get_path_without_query()
        
        # Route: /command
        if path == "/command":
            self._handle_command(remote)
            return
        
        # Route: /command/summary
        if path == "/command/summary":
            self._handle_command_summary(remote)
            return
        
        # Route: /classify
        if path == "/classify":
            self._handle_classify(remote)
            return
        
        # Route: /chat/process (Backend is King - unified chat processing)
        if path == "/chat/process":
            self._handle_chat_process(remote)
            return

        # M17: POST /chat/sessions  — create a new session
        if path == "/chat/sessions":
            self._handle_post_chat_sessions(remote)
            return

        # Route: /fin/plan (Plan Always - main entry for FIN domain)
        if path == "/fin/plan":
            self._handle_fin_plan(remote)
            return
        
        # Route: /fin/commit (commit single expense from confirmed plan)
        if path == "/fin/commit":
            self._handle_fin_commit(remote)
            return
        
        # Route: /fin/expense (parse expense from text and store if complete)
        if path == "/fin/expense":
            self._handle_fin_expense(remote)
            return
        
        # Route: /fin/chaperon (preprocess text to detect multi-expense or continuation)
        # Also accept /chaperon as alias for backwards compatibility
        if path == "/fin/chaperon" or path == "/chaperon":
            self._handle_fin_chaperon(remote)
            return
        
        # Route: /fin/expense/batch (execute multiple expenses from confirmed action_plan)
        if path == "/fin/expense/batch":
            self._handle_fin_expense_batch(remote)
            return
        
        # Route: /fin/expense/confirm (confirm and append to Sheets)
        if path == "/fin/expense/confirm":
            self._handle_fin_expense_confirm(remote)
            return
        
        # Route: /fin/receipt (stub - receive receipt image)
        if path == "/fin/receipt":
            self._handle_fin_receipt(remote)
            return
        
        # Route: /shutdown (for tests only)
        if path == "/shutdown":
            self._handle_shutdown(remote)
            return
        
        # Route: /work/query (query WORK tasks from Notion - read-only)
        if path == "/work/query":
            self._handle_work_query(remote)
            return
        
        # Route: /work/create (create WORK task in Notion - requires confirmation)
        if path == "/work/create":
            self._handle_work_create(remote)
            return
        
        # Route: /work/delete (delete/archive WORK tasks from Notion - requires confirmation)
        if path == "/work/delete":
            self._handle_work_delete(remote)
            return
        
        # Route: /work/schema/plan (plan schema changes - admin only)
        if path == "/work/schema/plan":
            self._handle_work_schema_plan(remote)
            return
        
        # Route: /work/schema/commit (apply schema changes - admin only)
        if path == "/work/schema/commit":
            self._handle_work_schema_commit(remote)
            return
        
        # Route: /codeops/plan (plan code task - no execution)
        if path == "/codeops/plan":
            self._handle_codeops_plan(remote)
            return
        
        # Route: /codeops/pr (create PR from task - mock for now)
        if path == "/codeops/pr":
            self._handle_codeops_pr(remote)
            return
        
        # 404 for unknown paths
        status, error = _make_json_error(404, f"Not found: {path}", "NotFound")
        _log_webhook_event(path, remote, ok=False)
        self._send_json_response(status, error)
    
    # M17: PATCH and DELETE for session management ─────────────────────────────

    def do_PATCH(self) -> None:  # noqa: N802
        """Handle PATCH requests (chat session updates)."""
        remote = self._get_remote_addr()
        path   = self._get_path_without_query()
        m = re.match(r"^/chat/sessions/([^/]+)$", path)
        if m:
            self._handle_patch_chat_session(m.group(1), remote)
            return
        status, error = _make_json_error(405, "Method not allowed", "MethodNotAllowed")
        self._send_json_response(status, error)

    def do_DELETE(self) -> None:  # noqa: N802
        """Handle DELETE requests (chat session removal)."""
        path = self._get_path_without_query()
        m = re.match(r"^/chat/sessions/([^/]+)$", path)
        if m:
            self._handle_delete_chat_session(m.group(1))
            return
        status, error = _make_json_error(405, "Method not allowed", "MethodNotAllowed")
        self._send_json_response(status, error)

    def do_GET(self) -> None:
        """Handle GET requests (health, chat UI, chat history, sheets status)."""
        path = self._get_path_without_query()
        
        if path == "/health":
            self._send_json_response(200, {
                "status": "ok",
                "service": "assistant_os",
                "notion_db_id_loaded": NOTION_WORK_DB_ID,
                "notion_token_set": bool(NOTION_TOKEN),
            })
            return
        
        if path == "/auth/check":
            # Validate token without doing anything else
            auth_error = self._check_auth()
            if auth_error:
                status, error = auth_error
                self._send_json_response(status, error)
            else:
                self._send_json_response(200, {
                    "ok": True,
                    "message": "Token is valid"
                })
            return
        
        if path == "/" or path == "/chat":
            self._handle_chat_ui()
            return
        
        if path == "/chat/history":
            self._handle_chat_history()
            return

        # M17: GET /chat/sessions  — list all sessions
        if path == "/chat/sessions":
            self._handle_get_chat_sessions()
            return

        # M17: GET /chat/sessions/{id}  — session detail + messages
        _m17_get = re.match(r"^/chat/sessions/([^/]+)$", path)
        if _m17_get:
            self._handle_get_chat_session(_m17_get.group(1))
            return

        # M21: GET /chat/search?q=...  — full-text search across messages
        if path == "/chat/search":
            self._handle_chat_search()
            return

        if path == "/fin/sheets/status":
            self._handle_fin_sheets_status()
            return
        
        if path == "/work/schema":
            self._handle_work_schema_get()
            return
        
        # 405 for everything else
        status, error = _make_json_error(405, "Method not allowed. Use POST.", "MethodNotAllowed")
        self._send_json_response(status, error)
    
    # ── M21: Message search ───────────────────────────────────────────────────

    def _handle_chat_search(self) -> None:
        """GET /chat/search?q=... — full-text search across all persisted messages."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        from urllib.parse import unquote_plus
        raw_params = self._parse_query_params()
        q = unquote_plus(raw_params.get("q", "")).strip()

        if len(q) < 2:
            self._send_json_response(
                400, {"ok": False, "error": "Query too short (min 2 chars)"}
            )
            return

        results = chat_db.search_messages(q)
        self._send_json_response(200, {"ok": True, "results": results, "count": len(results)})

    # ── M17: Chat session CRUD handlers ──────────────────────────────────────

    def _handle_get_chat_sessions(self) -> None:
        """GET /chat/sessions — list all sessions."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        sessions = chat_db.list_sessions()
        self._send_json_response(200, {"ok": True, "sessions": sessions})

    def _handle_post_chat_sessions(self, remote: str) -> None:
        """POST /chat/sessions — create a session."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        result = self._read_body()
        if result[1] is not None:
            self._send_json_response(*result[1])
            return
        try:
            data = json.loads(result[0].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        import uuid as _uuid
        session_id = str(data.get("id") or _uuid.uuid4())
        title      = str(data.get("title") or "Nuevo chat")
        session    = chat_db.create_session(session_id, title)
        self._send_json_response(201, {"ok": True, "session": session})

    def _handle_get_chat_session(self, session_id: str) -> None:
        """GET /chat/sessions/{id} — session detail with messages."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        session = chat_db.get_session_with_messages(session_id)
        if session is None:
            status, error = _make_json_error(404, f"Session {session_id!r} not found", "NotFound")
            self._send_json_response(status, error)
            return
        self._send_json_response(200, {"ok": True, "session": session})

    def _handle_patch_chat_session(self, session_id: str, remote: str) -> None:
        """PATCH /chat/sessions/{id} — update title / context_id / messages."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        result = self._read_body()
        if result[1] is not None:
            self._send_json_response(*result[1])
            return
        try:
            data = json.loads(result[0].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        kwargs = {}
        if "title"      in data: kwargs["title"]      = data["title"]
        if "context_id" in data: kwargs["context_id"] = data["context_id"]
        if "messages"   in data: kwargs["messages"]   = data["messages"]
        session = chat_db.update_session(session_id, **kwargs)
        if session is None:
            status, error = _make_json_error(404, f"Session {session_id!r} not found", "NotFound")
            self._send_json_response(status, error)
            return
        self._send_json_response(200, {"ok": True, "session": session})

    def _handle_delete_chat_session(self, session_id: str) -> None:
        """DELETE /chat/sessions/{id} — remove session and its messages."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        deleted = chat_db.delete_session(session_id)
        if not deleted:
            status, error = _make_json_error(404, f"Session {session_id!r} not found", "NotFound")
            self._send_json_response(status, error)
            return
        self._send_json_response(200, {"ok": True})

    # ─────────────────────────────────────────────────────────────────────────

    def _handle_chat_ui(self) -> None:
        """Serve the chat UI HTML page."""
        html = generate_chat_html()
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Prevent caching to avoid stale UI/auth issues
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)
    
    def _handle_chat_history(self) -> None:
        """Handle GET /chat/history endpoint - retrieve conversation history."""
        remote = self._get_remote_addr()
        
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        
        # Parse query params
        params = self._parse_query_params()
        
        # Validate conversation_id
        conversation_id = params.get("conversation_id", "")
        if not conversation_id:
            status, error = _make_json_error(400, "Missing required parameter: conversation_id", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Parse limit (default 50, max 200)
        try:
            limit = int(params.get("limit", "50"))
        except ValueError:
            limit = 50
        
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200
        
        # Read history
        items = _read_chat_history(conversation_id, limit)
        
        response = {
            "ok": True,
            "conversation_id": conversation_id,
            "items": items,
        }
        
        self._send_json_response(200, response)
    
    def _handle_command(self, remote: str) -> None:
        """Handle POST /command endpoint."""
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            _log_webhook_event("/command", remote, ok=False)
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            _log_webhook_event("/command", remote, ok=False)
            self._send_json_response(status, error)
            return
        
        # Read body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            _log_webhook_event("/command", remote, ok=False)
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON with robust UTF-8 handling
        data, parse_error = _safe_parse_json(body)
        if parse_error:
            status, error = parse_error
            _log_webhook_event("/command", remote, ok=False)
            self._send_json_response(status, error)
            return
        
        # Check if this is a confirm-only request (no text, has context_id and confirm)
        is_confirm_request = False
        if data and isinstance(data, dict):
            is_confirm_request = (
                data.get("confirm") is True
                and "context_id" in data
                and "text" not in data
            )
        
        if is_confirm_request:
            # The client may supply applied_changes (and selected_notion_page_ids for bulk)
            # in the confirmation body. Merge them into the stored plan before execution.
            ctx_id = data["context_id"]
            if "applied_changes" in data or "selected_notion_page_ids" in data:
                stored = get_pending_plan(ctx_id)
                if stored:
                    plan_action = stored.get("plan", {}).get("action", "")
                    merged = dict(stored["plan"])

                    if plan_action == ACTION_WORK_UPDATE_BULK:
                        # Bulk: merge selected IDs and applied_changes flat dict directly.
                        for k in ("selected_notion_page_ids", "applied_changes"):
                            if k in data:
                                merged[k] = data[k]

                    elif plan_action == ACTION_WORK_UPDATE and "applied_changes" in data:
                        # Singular: convert flat applied_changes dict → proposed_changes list
                        # so _work_update_execute can validate and apply them.
                        ac = data["applied_changes"]
                        new_proposed = [
                            {"field": field, "new_value": value}
                            for field, value in ac.items()
                            if value  # skip empty/null entries
                        ]
                        merged_filters = dict(merged.get("filters", {}))
                        merged_filters["proposed_changes"] = new_proposed
                        merged["filters"] = merged_filters

                    store_pending_plan(ctx_id, merged, OP_WORK_UPDATE, raw_text=stored.get("raw_text", ""))
            response = self._execute_confirmed_plan(ctx_id, remote)
            status_code = 200 if response.get("status") in ("ok", "pending") else 400
            self._send_json_response(status_code, response)
            return
        
        # Validate "text" field for regular requests
        if not data or not isinstance(data, dict) or "text" not in data:
            status, error = _make_json_error(400, 'Missing required field: "text"', "BadRequest")
            _log_webhook_event("/command", remote, ok=False)
            self._send_json_response(status, error)
            return
        
        text = None
        if data and isinstance(data, dict):
            text = data["text"]
        if not isinstance(text, str):
            status, error = _make_json_error(400, '"text" must be a string', "BadRequest")
            _log_webhook_event("/command", remote, ok=False)
            self._send_json_response(status, error)
            return
        
        # Check if text has a command prefix (CODE:, DOC:, JOBS:, BIZ:) or invalid prefix (WORD:)
        if _has_command_prefix(text) or _has_invalid_prefix(text):
            # Has valid prefix or looks like invalid prefix - use existing routing
            req = parse_command_to_request(text)
            response = route_request(req)
        else:
            # No prefix: classify and route based on operation
            response = self._route_text_by_classification(text, remote)
        
        # Determine status code
        if response["status"] == "ok":
            status_code = 200
        elif response["status"] == "pending":
            status_code = 200
        else:
            status_code = 400
        
        # Log success
        _log_webhook_event(
            "/command",
            remote,
            ok=(response["status"] in ("ok", "pending")),
            agent=response["agent"],
            context_id=response["context_id"],
        )
        
        self._send_json_response(status_code, response)
    
    def _handle_command_summary(self, remote: str) -> None:
        """Handle POST /command/summary endpoint - human-friendly summary."""
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            _log_webhook_event("/command/summary", remote, ok=False, event_type="webhook_summary")
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            _log_webhook_event("/command/summary", remote, ok=False, event_type="webhook_summary")
            self._send_json_response(status, error)
            return
        
        # Read body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            _log_webhook_event("/command/summary", remote, ok=False, event_type="webhook_summary")
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON with safe UTF-8 handling
        data, json_err = _safe_parse_json(body)
        if json_err is not None:
            status, error = json_err
            _log_webhook_event("/command/summary", remote, ok=False, event_type="webhook_summary")
            self._send_json_response(status, error)
            return
        
        # Validate "text" field
        if not isinstance(data, dict) or "text" not in data:
            status, error = _make_json_error(400, 'Missing required field: "text"', "BadRequest")
            _log_webhook_event("/command/summary", remote, ok=False, event_type="webhook_summary")
            self._send_json_response(status, error)
            return
        
        text = data["text"]
        if not isinstance(text, str):
            status, error = _make_json_error(400, '"text" must be a string', "BadRequest")
            _log_webhook_event("/command/summary", remote, ok=False, event_type="webhook_summary")
            self._send_json_response(status, error)
            return
        
        # Get conversation_id (optional, defaults to "default")
        conversation_id = data.get("conversation_id", "")
        if not isinstance(conversation_id, str):
            conversation_id = ""
        if not conversation_id:
            conversation_id = "default"
        
        # Get forced operation from UI (prevents re-classification)
        forced_operation = data.get("operation", "")
        if not isinstance(forced_operation, str):
            forced_operation = ""
        
        # Check if text has a command prefix (CODE:, DOC:, JOBS:, BIZ:) or invalid prefix (WORD:)
        if _has_command_prefix(text) or _has_invalid_prefix(text):
            # Has valid prefix or looks like invalid prefix - use existing routing
            req = parse_command_to_request(text)
            response = route_request(req)
        else:
            # No prefix: classify and route based on operation
            response = self._route_text_by_classification(text, remote, forced_operation=forced_operation)
        
        # Store plan in context store if confirmation is required
        output = response.get("output", {})
        output_type = output.get("type", "")
        plan = output.get("plan", {})
        requires_confirmation = output_type == "plan_confirmation_required"
        
        if requires_confirmation and plan:
            context_id = response.get("context_id", "")
            action = plan.get("action", "")
            store_pending_plan(
                context_id=context_id,
                plan=plan,
                operation=action,
                raw_text=text,
            )
            # Pending plan stored — structured log event emitted when response is sent
        
        # Check if raw should be included
        query_params = self._parse_query_params()
        include_raw = query_params.get("raw", "") == "1" or WEBHOOK_INCLUDE_RAW_DEFAULT
        
        # Generate summary
        summary_response = summarize(response, include_raw=include_raw)
        
        # Determine status code
        status_code = 200 if summary_response["ok"] else 400
        
        # Detect if request is from chat UI (via Referer or conversation_id != default)
        referer = self.headers.get("Referer", "")
        is_from_chat = "/chat" in referer or conversation_id != "default"
        
        # Logging
        if is_from_chat:
            # Log user message
            _log_chat_message(
                remote=remote,
                conversation_id=conversation_id,
                text=text,
                context_id=response["context_id"],
            )
            
            # Log assistant response
            error_info = response.get("error") or {}
            _log_chat_response(
                remote=remote,
                conversation_id=conversation_id,
                ok=summary_response["ok"],
                agent=response["agent"],
                title=summary_response.get("title", ""),
                summary=summary_response.get("summary", ""),
                context_id=response["context_id"],
                error_type=error_info.get("type", ""),
                error_message=error_info.get("message", ""),
            )
        else:
            # Regular webhook_summary log
            _log_webhook_event(
                "/command/summary",
                remote,
                ok=summary_response["ok"],
                agent=response["agent"],
                context_id=response["context_id"],
                event_type="webhook_summary",
                conversation_id=conversation_id,
            )
        
        self._send_json_response(status_code, summary_response)
    
    def _route_text_by_classification(self, text: str, remote: str, forced_operation: str = "") -> Response:
        """
        Route text without prefix via the Assistant Kernel orchestrator.

        HTTP-layer adapter:
          1. Normalize raw input → CanonicalRequest
          2. Delegate full pipeline to orchestrator.handle_request → DomainResult
          3. Adapt DomainResult → legacy Response shape via _adapt_result_to_response

        Args:
            text: User input text
            remote: Remote address for logging
            forced_operation: If provided, override classifier operation (from UI routing)

        Returns a Response compatible with prefix-based routing.
        """
        from .core.orchestrator import handle_request

        req = normalize_request(text=text)
        result = handle_request(req, forced_operation=forced_operation)
        return _adapt_result_to_response(result, req["context_id"])
    
    def _execute_work_query_from_plan(self, plan: Plan, context_id: str) -> Response:
        """Execute a WORK query from a Plan and return Response."""
        from .pipelines.work_pipeline import execute as _work_execute
        return _wrap_work_result(_work_execute(plan, context_id), context_id)

    def _execute_work_update_preview(self, plan: Plan, context_id: str, text: str) -> Response:
        """Execute WORK_UPDATE Phase 1: Return preview/proposal (read-only)."""
        from .pipelines.work_pipeline import execute as _work_execute
        plan_with_text = dict(plan)
        plan_with_text["raw_text"] = text
        return _wrap_work_result(_work_execute(plan_with_text, context_id), context_id)

    def _execute_confirmed_plan(self, context_id: str, remote: str) -> Response:
        """
        Execute a previously stored plan after user confirmation.
        
        Args:
            context_id: The context ID of the stored plan
            remote: Remote address for logging
        
        Returns:
            Response with execution result
        """
        # Get stored plan from context store
        stored = get_pending_plan(context_id)
        
        if stored is None:
            _log_webhook_event("/command", remote, ok=False, context_id=context_id, event_type="confirm_not_found")
            return {
                "context_id": context_id,
                "agent": "kernel",
                "status": "error",
                "output": {},
                "error": {
                    "type": "ContextNotFound",
                    "message": f"No pending plan found for context_id={context_id}. It may have expired or already been executed.",
                },
                "ts": now_iso(),
            }
        
        plan = stored["plan"]
        action = plan.get("action", "")

        # Delegate confirmed execution through the domain registry.
        # action_domain() maps action prefix → domain key ("WORK", "FIN", …).
        # get_pipeline() returns the registered execute(plan, context_id) callable.
        # _adapt_result_to_response() converts the DomainResult to the transport
        # Response shape, dispatching by domain — domain-agnostic confirmed execution.
        from .core.routing import get_pipeline, action_domain
        pipeline = get_pipeline(action_domain(action))
        if pipeline:
            result = _adapt_result_to_response(pipeline(plan, context_id), context_id)
        else:
            result = {
                "context_id": context_id,
                "agent": "kernel",
                "status": "error",
                "output": {"plan": dict(plan)},
                "error": {
                    "type": "UnsupportedAction",
                    "message": f"Action '{action}' is not yet supported for confirmed execution.",
                },
                "ts": now_iso(),
            }
        
        # Remove plan from store after execution (success or failure)
        remove_pending_plan(context_id)
        
        # Log execution
        executed = result.get("status") == "ok"
        _log_webhook_event(
            "/command",
            remote,
            ok=executed,
            agent=result.get("agent", "kernel"),
            context_id=context_id,
        )
        
        return result

    def _execute_work_create(self, plan: Plan, context_id: str, test_mode: bool = False) -> Response:
        """Execute WORK_CREATE from a confirmed plan. Delegates to work_pipeline."""
        from .pipelines.work_pipeline import _work_create_execute
        return _wrap_work_result(_work_create_execute(plan, context_id), context_id)

    def _execute_work_delete(
        self,
        plan: Plan,
        context_id: str,
        test_mode: bool = False,
        reset_all: bool = False,
    ) -> Response:
        """Execute WORK_DELETE from a confirmed plan. Delegates to work_pipeline."""
        from .pipelines.work_pipeline import _work_delete_execute
        return _wrap_work_result(_work_delete_execute(plan, context_id), context_id)

    def _execute_work_update_bulk(self, plan: dict, context_id: str) -> dict:
        """
        Execute bulk WORK_UPDATE from a confirmed bulk proposal.

        Args:
            plan: The bulk proposal plan (type=work_update_bulk_proposal)
            context_id: Context ID for the response

        Returns:
            Response dict with updated_count, updated_items, failed_items, skipped_items
        """
        from .pipelines.work_pipeline import _work_update_bulk_execute
        return _wrap_work_result(_work_update_bulk_execute(plan, context_id), context_id)

    def _execute_work_update(self, plan: Plan, context_id: str) -> Response:
        """Execute WORK_UPDATE Phase 2 from a confirmed plan. Delegates to work_pipeline."""
        from .pipelines.work_pipeline import _work_update_execute
        return _wrap_work_result(_work_update_execute(plan, context_id), context_id)

    def _handle_classify(self, remote: str) -> None:
        """Handle POST /classify endpoint - deterministic intent classification."""
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            _log_classify_event(remote, ok=False)
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            _log_classify_event(remote, ok=False)
            self._send_json_response(status, error)
            return
        
        # Read body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            _log_classify_event(remote, ok=False)
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            _log_classify_event(remote, ok=False)
            self._send_json_response(status, error)
            return
        
        # Validate request structure
        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            _log_classify_event(remote, ok=False)
            self._send_json_response(status, error)
            return
        
        # Validate "text" field (required)
        if "text" not in data:
            status, error = _make_json_error(400, 'Missing required field: "text"', "BadRequest")
            _log_classify_event(remote, ok=False)
            self._send_json_response(status, error)
            return
        
        text = data["text"]
        if not isinstance(text, str):
            status, error = _make_json_error(400, '"text" must be a string', "BadRequest")
            _log_classify_event(remote, ok=False)
            self._send_json_response(status, error)
            return
        
        # Get optional fields
        mode = data.get("mode", "auto")
        conversation_id = data.get("conversation_id", "")
        context = data.get("context", {})
        
        # Build ClassifyRequest
        classify_request: ClassifyRequest = {
            "text": text,
            "mode": mode if isinstance(mode, str) else "auto",
            "conversation_id": conversation_id if isinstance(conversation_id, str) else "",
            "context": context if isinstance(context, dict) else {},
        }
        
        # Classify
        intent = classify_text(classify_request)
        
        # Build response
        response: ClassifyResponse = {
            "ok": True,
            "intent": intent,
        }
        
        # Log success
        _log_classify_event(
            remote=remote,
            ok=True,
            text_len=len(text),
            domain=intent["domain"],
            confidence=intent["confidence"],
            needs_confirmation=intent["needs_confirmation"],
            conversation_id=conversation_id if conversation_id else "",
            text_preview=text,
        )
        
        self._send_json_response(200, response)
    
    def _handle_chat_process(self, remote: str) -> None:
        """Handle POST /chat/process - Backend is King unified processing.

        Single entry point for all chat messages.  The backend owns routing —
        no UI-side classification.

        Request (M12 contract):
            {
                "text":             str   — optional when action is present
                "action":           dict  — optional structured action (M12)
                    {
                        "type":     str   — 'confirm'|'cancel'|'select'|
                                           'form_submit'|'plan_item_execute'
                        "target":   str?  — trace_id of originating message
                        "id":       str?  — item id (plan_item_execute)
                        "payload":  dict? — type-specific data
                    }
                "session_context":  dict  — optional multi-turn state
                "conversation_id":  str   — optional, for logging
            }

        Validation:
            At least one of "text" (non-empty) OR "action" must be present.

        Response:
            ChatCoreResponse fields: trace_id, domain, intent, mode,
            ui_actions, plan, needs_confirmation, session, audit.
        """
        import logging
        _log = logging.getLogger("chat_process")
        
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Read body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Validate request
        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # --- M12: Extract text and action (at least one required) -----------
        text_raw = data.get("text", "")
        text = text_raw.strip() if isinstance(text_raw, str) else ""

        action_raw = data.get("action")  # May be None, dict, or garbage

        # Validate action shape early so we can return a clean 400 before
        # touching the core pipeline.
        if action_raw is not None and not isinstance(action_raw, dict):
            status, error = _make_json_error(
                400, '"action" must be a JSON object', "BadRequest"
            )
            self._send_json_response(status, error)
            return

        if action_raw is not None and not isinstance(action_raw.get("type", ""), str):
            status, error = _make_json_error(
                400, '"action.type" must be a non-empty string', "BadRequest"
            )
            self._send_json_response(status, error)
            return

        # At least one of text or action must be meaningful
        if not text and action_raw is None:
            status, error = _make_json_error(
                400,
                'Missing required field: provide "text", "action", or both',
                "BadRequest",
            )
            self._send_json_response(status, error)
            return

        # Get optional session context
        session_data = data.get("session_context", {})
        if not isinstance(session_data, dict):
            session_data = {}

        # M17: if session_id provided, load context_id from DB (authoritative)
        session_id = data.get("session_id") if isinstance(data.get("session_id"), str) else None
        if session_id:
            db_sess = chat_db.get_session(session_id)
            if db_sess and db_sess.get("context_id"):
                session_data = dict(session_data)
                session_data["context_id"] = db_sess["context_id"]

        session = ChatSession(
            pending_flow=session_data.get("pending_flow"),
            pending_data=session_data.get("pending_data", {}),
            context_id=session_data.get("context_id") or new_context_id(),
            last_domain=session_data.get("last_domain"),
            last_action_type=session_data.get("last_action_type"),
        )

        # Get optional conversation_id for logging
        conversation_id = data.get("conversation_id", "")

        # --- BACKEND IS KING: Process through chat_core ---
        # action_raw is passed as-is; parse_action() in chat_core validates it.
        # M23 diagnostic: log incoming session state + action before dispatching
        incoming_action = action_raw.get("type") if isinstance(action_raw, dict) else None
        _log.info(
            "[M23][RECV] action=%s pending_flow_in=%s context_id=%s text=%r",
            incoming_action or "None",
            session.get("pending_flow") or "None",
            (session.get("context_id") or "")[:8],
            text[:40],
        )

        response: ChatCoreResponse = process_chat_input(
            text, session, action=action_raw
        )

        # Logging: trace_id, intent, pending_flow, action_types
        ui_action_types = [a.get("type", "") for a in response.get("ui_actions", [])]
        _log.info(
            "[M23][RESP] trace_id=%s intent=%s/%s mode=%s pending_flow_out=%s ui_actions=%s",
            response.get("trace_id", "N/A")[:8],
            response["domain"], response["intent"],
            response["mode"],
            response["session"].get("pending_flow") or "None",
            ui_action_types,
        )
        
        # Log chat message
        if conversation_id:
            _log_chat_message(
                remote=remote,
                conversation_id=conversation_id,
                text=text,
                context_id=response["session"].get("context_id", ""),
            )
        
        # Layer 2: render human-readable message from structured response
        rendered = render_chat_response(response)

        # Build base audit — merge core audit with action-level metadata so the
        # client can correlate which structured action triggered this response.
        base_audit = dict(response.get("audit", {}))
        if isinstance(action_raw, dict):
            base_audit.setdefault("action_type",   action_raw.get("type"))
            base_audit.setdefault("action_target", action_raw.get("target"))
            base_audit.setdefault("action_id",     action_raw.get("id"))

        # Convert ChatCoreResponse to JSON-serializable dict
        response_data = {
            "ok": True,
            "message": rendered.message,
            "trace_id": response.get("trace_id", ""),
            "domain": response["domain"],
            "intent": response["intent"],
            "mode": response["mode"],
            "needs_confirmation": response.get("needs_confirmation", False),
            "missing_fields": response.get("missing_fields", []),
            "plan": response.get("plan", []),
            "ui_actions": response.get("ui_actions", []),
            "session": dict(response.get("session", {})),
            "audit": base_audit,
        }

        # M17: persist messages + update context_id if session_id was provided
        if session_id:
            import uuid as _uuid2
            user_content = text or (
                f"[{action_raw.get('type', 'action')}]"
                if isinstance(action_raw, dict) else "[action]"
            )
            new_ctx = response["session"].get("context_id")
            try:
                chat_db.append_message(session_id, "user", {
                    "id":        str(_uuid2.uuid4()),
                    "role":      "user",
                    "content":   user_content,
                    "status":    "sent",
                    "createdAt": now_iso(),
                })
                chat_db.append_message(session_id, "assistant", {
                    "id":        str(_uuid2.uuid4()),
                    "role":      "assistant",
                    "content":   rendered.message,
                    "status":    "sent",
                    "createdAt": now_iso(),
                    "uiActions": response.get("ui_actions") or [],
                    "plan":      response.get("plan") or [],
                    "meta": {
                        "domain":            response["domain"],
                        "intent":            response["intent"],
                        "mode":              response["mode"],
                        "traceId":           response.get("trace_id", ""),
                        "needsConfirmation": response.get("needs_confirmation", False),
                    },
                    "kind":    "confirmation_request" if response.get("needs_confirmation") else "normal",
                    "handled": False,
                })
                if new_ctx:
                    chat_db.update_session(session_id, context_id=new_ctx)
            except Exception as _m17_exc:
                _log.warning("[M17] persist failed for session %s: %s", session_id, _m17_exc)

        self._send_json_response(200, response_data)
    
    def _handle_fin_plan(self, remote: str) -> None:
        """Handle POST /fin/plan - Plan Always entry point for FIN domain.
        
        Every FIN input goes through this endpoint FIRST.
        Returns an action_plan with N items (one per monto detected).
        Does NOT write to Sheets - only builds the plan.
        """
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Read body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Validate request structure
        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Validate "text" field (required)
        text = data.get("text", "")
        if not isinstance(text, str) or not text.strip():
            status, error = _make_json_error(400, 'Missing required field: "text"', "BadRequest")
            self._send_json_response(status, error)
            return
        
        session_id = data.get("session_id", "")
        session_context = data.get("session_context", {})
        
        # Generate plan
        plan_response = generate_fin_plan(text, session_context)
        
        # Log the plan event
        _log_fin_expense_event(
            remote=remote,
            ok=plan_response["ok"],
            action="plan",
            session_id=session_id,
            text_preview=text[:100] if text else "",
        )
        
        # Build response
        response_data = {
            "ok": plan_response["ok"],
            "kind": plan_response["kind"],
            "total_items": plan_response["total_items"],
            "message": plan_response["message"],
            "items": [
                {
                    "id": item["id"],
                    "draft_expense": dict(item["draft_expense"]),
                    "missing_fields": item["missing_fields"],
                    "confidence": item["confidence"],
                    "raw_segment": item["raw_segment"],
                }
                for item in plan_response["items"]
            ],
            "needs_clarification": plan_response["needs_clarification"],
            "clarification_prompt": plan_response["clarification_prompt"],
            "session_context": plan_response["session_context"],
        }
        
        self._send_json_response(200, response_data)
    
    def _handle_fin_commit(self, remote: str) -> None:
        """Handle POST /fin/commit - commit single expense from confirmed plan.
        
        This endpoint writes a single expense to Google Sheets.
        Called once per item after user confirms the plan.
        Validates dropdown canonicalization before saving.
        """
        try:
            self._handle_fin_commit_impl(remote)
        except Exception as e:
            import traceback
            traceback.print_exc()
            status, error = _make_json_error(500, f"Internal error: {e}", "InternalError")
            self._send_json_response(status, error)
    
    def _handle_fin_commit_impl(self, remote: str) -> None:
        """Implementation of /fin/commit handler."""
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Read body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Validate request structure
        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Validate "expense" field (required)
        expense_data = data.get("expense")
        if not isinstance(expense_data, dict):
            status, error = _make_json_error(400, 'Missing required field: "expense"', "BadRequest")
            self._send_json_response(status, error)
            return
        
        session_id = data.get("session_id", "")
        
        # Check Sheets availability
        if not check_sheets_available():
            response_data: FinCommitResponse = {
                "ok": False,
                "stored": False,
                "row_number": None,
                "sheet": SHEETS_TAB_NAME,
                "message": "Google Sheets integration not available",
                "error": "sheets_unavailable",
            }
            self._send_json_response(503, response_data)
            return
        
        # Build ParsedExpense from expense_data (canonicalize values)
        from .pipelines.fin_normalization import canonicalize_commit_expense
        parsed = canonicalize_commit_expense(expense_data)
        
        # Append to Sheets
        from .tools.google.append_expense_row_tool import AppendExpenseRowTool
        tool_result = AppendExpenseRowTool().execute({
            "fecha": parsed["fecha"],
            "descripcion": parsed["descripcion"],
            "factura": parsed.get("factura", ""),
            "responsable": parsed["responsable"],
            "monto": parsed["monto"],
            "moneda": parsed["moneda"],
            "itbms": parsed["itbms"] if parsed["itbms"] is not None else False,
            "categoria": parsed["categoria"],
            "metodo_pago": parsed.get("metodo_pago", "") or "",
            "notas": parsed.get("notas", ""),
            "fuente": parsed.get("fuente", "chat"),
            "link_archivo": parsed.get("link_archivo", ""),
            "expense_id": session_id,
        })

        if tool_result.ok:
            row_number = tool_result.data["row_number"]
            response_data = {
                "ok": True,
                "stored": True,
                "row_number": row_number,
                "sheet": SHEETS_TAB_NAME,
                "message": f"Gasto guardado en fila {row_number}",
                "error": None,
            }

            # Log success
            _log_fin_expense_event(
                remote=remote,
                ok=True,
                action="commit",
                monto=parsed["monto"],
                moneda=parsed["moneda"],
                responsable=parsed["responsable"],
                session_id=session_id,
            )

            self._send_json_response(200, response_data)
        else:
            err_msg = tool_result.error.message if tool_result.error else "Unknown error"
            response_data = {
                "ok": False,
                "stored": False,
                "row_number": None,
                "sheet": SHEETS_TAB_NAME,
                "message": f"Error al guardar: {err_msg}",
                "error": err_msg,
            }

            # Log error
            _log_fin_expense_event(
                remote=remote,
                ok=False,
                action="commit_error",
                error_message=err_msg,
                session_id=session_id,
            )

            self._send_json_response(500, response_data)

    def _handle_fin_sheets_status(self) -> None:
        """Handle GET /fin/sheets/status - return diagnostic info about Sheets integration."""
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        
        # Get comprehensive status
        status_info = get_sheets_status()
        
        # Convert to JSON-compatible dict
        response = {
            "ok": status_info.get("ok", False),
            "sheets_available": status_info.get("sheets_available", False),
            "config_path": status_info.get("config_path", ""),
            "config_exists": status_info.get("config_exists", False),
            "spreadsheet_id": status_info.get("spreadsheet_id", ""),
            "tab_name": status_info.get("tab_name", ""),
            "sheet_title": status_info.get("sheet_title", ""),
            "header_ok": status_info.get("header_ok", False),
            "last_error": status_info.get("last_error"),
            "interpreter": status_info.get("interpreter", ""),
            "gspread_version": status_info.get("gspread_version", ""),
        }
        
        self._send_json_response(200, response)
    
    def _handle_work_schema_get(self) -> None:
        """Handle GET /work/schema - return current database schema options."""
        try:
            # Check auth
            auth_error = self._check_auth()
            if auth_error:
                status, error = auth_error
                self._send_json_response(status, error)
                return
            
            # Get database schema
            schema = get_database_schema()
            
            # Handle case where schema is None or empty
            if not schema:
                self._send_json_response(404, {
                    "ok": False,
                    "error": {
                        "type": "NotFound",
                        "message": "Schema not available. Notion may not be configured or accessible.",
                    }
                })
                return
            
            # Extract select/multi_select/status options
            properties_info: dict[str, Any] = {}
            
            for prop_name, prop_data in schema.items():
                # Skip non-dict property values (can be bool or other types)
                if not isinstance(prop_data, dict):
                    continue
                
                prop_type = prop_data.get("type")
                
                if prop_type == "select":
                    options = [opt.get("name", "") for opt in prop_data.get("select", {}).get("options", [])]
                    properties_info[prop_name] = {"type": "select", "options": options}
                
                elif prop_type == "multi_select":
                    options = [opt.get("name", "") for opt in prop_data.get("multi_select", {}).get("options", [])]
                    properties_info[prop_name] = {"type": "multi_select", "options": options}
                
                elif prop_type == "status":
                    groups = prop_data.get("status", {}).get("groups", [])
                    options_by_group: dict[str, list[str]] = {}
                    for group in groups:
                        group_name = group.get("name", "")
                        option_ids = group.get("option_ids", [])
                        # Get option names from the status options
                        all_options = prop_data.get("status", {}).get("options", [])
                        option_names = [opt.get("name", "") for opt in all_options if opt.get("id") in option_ids]
                        options_by_group[group_name] = option_names
                    properties_info[prop_name] = {"type": "status", "groups": options_by_group}
                
                else:
                    # Include other property types with just the type
                    properties_info[prop_name] = {"type": prop_type}
            
            # Log schema request
            print(f"[SCHEMA] /work/schema: {len(properties_info)} properties returned")
            
            response = {
                "ok": True,
                "database_id": NOTION_WORK_DB_ID,
                "properties": properties_info,
            }
            
            self._send_json_response(200, response)
        
        except Exception as e:
            # Catch any exception and return a proper JSON error
            _log.error("_handle_work_schema_get exception: %s", e, exc_info=True)
            self._send_json_response(500, {
                "ok": False,
                "error": {
                    "type": "InternalError",
                    "message": f"Error fetching schema: {type(e).__name__}: {e}",
                }
            })

    def _handle_fin_expense(self, remote: str) -> None:
        """Handle POST /fin/expense - parse expense and auto-store if complete."""
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            _log_fin_expense_event(remote, ok=False, error_message="Unauthorized")
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            _log_fin_expense_event(remote, ok=False, error_message="Invalid content type")
            self._send_json_response(status, error)
            return
        
        # Read body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            _log_fin_expense_event(remote, ok=False, error_message="Failed to read body")
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            _log_fin_expense_event(remote, ok=False, error_message=f"Invalid JSON: {e}")
            self._send_json_response(status, error)
            return
        
        # Validate request structure
        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            _log_fin_expense_event(remote, ok=False, error_message="Invalid request format")
            self._send_json_response(status, error)
            return
        
        # Validate "text" field (required)
        if "text" not in data:
            status, error = _make_json_error(400, 'Missing required field: "text"', "BadRequest")
            _log_fin_expense_event(remote, ok=False, error_message="Missing text field")
            self._send_json_response(status, error)
            return
        
        text = data["text"]
        if not isinstance(text, str):
            status, error = _make_json_error(400, '"text" must be a string', "BadRequest")
            _log_fin_expense_event(remote, ok=False, error_message="Text must be string")
            self._send_json_response(status, error)
            return
        
        # Get optional fields
        override = data.get("overrides", data.get("override", {}))  # Accept both "overrides" and "override"
        session_id = data.get("session_id", "")
        
        # Build ExpenseRequest
        expense_request: ExpenseRequest = {
            "text": text,
            "override": override if isinstance(override, dict) else {},
            "session_id": session_id if isinstance(session_id, str) else "",
        }
        
        # Parse expense
        expense_response = parse_expense(expense_request)
        
        # Check if parsing was successful
        if not expense_response["ok"] or not expense_response["expense"]:
            response_data = {
                "ok": False,
                "stored": False,
                "status": "error",
                "message": expense_response["message"],
                "expense": None,
                "missing_fields": expense_response.get("missing_fields", []),
                "sheets_available": check_sheets_available(),
                "needs_confirmation": False,
                "row_number": None,
                "tab_name": SHEETS_TAB_NAME,
            }
            _log_fin_expense_event(
                remote=remote,
                ok=False,
                action="parse",
                error_message=expense_response["message"],
                session_id=session_id,
                text_preview=text,
            )
            self._send_json_response(400, response_data)
            return
        
        exp = expense_response["expense"]
        sheets_available = check_sheets_available()
        
        # If needs confirmation, return pending status without storing
        if expense_response["needs_confirmation"]:
            response_data = {
                "ok": True,
                "stored": False,
                "status": "needs_confirmation",
                "needs_confirmation": True,
                "missing_fields": expense_response["missing_fields"],
                "ambiguous_responsables": expense_response.get("ambiguous_responsables", []),
                "message": expense_response["message"],
                "expense": exp,
                "sheets_available": sheets_available,
                "row_number": None,
                "tab_name": SHEETS_TAB_NAME,
            }
            _log_fin_expense_event(
                remote=remote,
                ok=True,
                action="parse",
                monto=exp["monto"] or 0.0,
                moneda=exp["moneda"],
                categoria=exp["categoria"],
                responsable=exp["responsable"],
                needs_confirmation=True,
                session_id=session_id,
                text_preview=text,
            )
            self._send_json_response(200, response_data)
            return
        
        # All required fields present - auto-store to Sheets
        if not sheets_available:
            # Get specific error information
            last_error = get_sheets_last_error()
            error_type = last_error.get("type", "unknown_error") if last_error else "unknown_error"
            error_msg = last_error.get("message", "Sheets not configured") if last_error else "Sheets not configured"
            
            response_data = {
                "ok": True,
                "stored": False,
                "status": "sheets_unavailable",  # Generic status
                "error_type": error_type,  # Specific error type
                "needs_confirmation": False,
                "message": f"Expense parsed but could not store: {error_msg}",
                "expense": exp,
                "sheets_available": False,
                "sheets_error": last_error,  # Include full error details
                "row_number": None,
                "tab_name": SHEETS_TAB_NAME,
            }
            _log_fin_expense_event(
                remote=remote,
                ok=True,
                action="parse",
                monto=exp["monto"] or 0.0,
                moneda=exp["moneda"],
                categoria=exp["categoria"],
                responsable=exp["responsable"],
                needs_confirmation=False,
                session_id=session_id,
                text_preview=text,
                error_message=error_msg,
            )
            self._send_json_response(200, response_data)
            return
        
        # Store to Sheets
        from .tools.google.append_expense_row_tool import AppendExpenseRowTool
        tool_result = AppendExpenseRowTool().execute({
            "fecha": exp["fecha"],
            "descripcion": exp["descripcion"],
            "factura": exp.get("factura", ""),
            "responsable": exp["responsable"],
            "monto": exp["monto"] or 0.0,
            "moneda": exp["moneda"],
            "itbms": exp["itbms"],
            "categoria": exp["categoria"],
            "metodo_pago": exp.get("metodo_pago", "") or "",
            "notas": exp.get("notas", ""),
            "fuente": exp.get("fuente", "chat"),
            "link_archivo": exp.get("link_archivo", ""),
            "expense_id": session_id,
        })

        if tool_result.ok:
            row_number = tool_result.data["row_number"]
            response_data = {
                "ok": True,
                "stored": True,
                "status": "stored",
                "needs_confirmation": False,
                "row_number": row_number,
                "tab_name": SHEETS_TAB_NAME,
                "message": f"Guardado en Sheets (fila {row_number})",
                "expense": exp,
                "sheets_available": True,
            }
            _log_fin_expense_event(
                remote=remote,
                ok=True,
                action="stored",
                monto=exp["monto"] or 0.0,
                moneda=exp["moneda"],
                categoria=exp["categoria"],
                responsable=exp["responsable"],
                session_id=session_id,
                text_preview=text,
            )
            self._send_json_response(200, response_data)
        else:
            # Sheets error (e.g., HeaderMismatch, API error)
            err_msg = tool_result.error.message if tool_result.error else "Unknown error"
            last_error = get_sheets_last_error()
            if "Header mismatch" in err_msg:
                error_type = "SheetSchemaMismatch"
            elif last_error:
                error_type = last_error.get("type", "unknown_error")
            else:
                error_type = "unknown_error"

            response_data = {
                "ok": False,
                "stored": False,
                "status": "error",
                "needs_confirmation": False,
                "message": err_msg,
                "error_type": error_type,
                "expense": exp,
                "sheets_available": True,
                "sheets_error": last_error,
                "row_number": None,
                "tab_name": SHEETS_TAB_NAME,
            }
            _log_fin_expense_event(
                remote=remote,
                ok=False,
                action="sheets_error",
                error_message=err_msg,
                session_id=session_id,
                text_preview=text,
            )
            self._send_json_response(500, response_data)
    
    def _handle_fin_chaperon(self, remote: str) -> None:
        """Handle POST /fin/chaperon - preprocess text to detect multi-expense or continuation.
        
        The Chaperon runs AFTER classifier and BEFORE backend executor.
        It detects:
        - Multiple montos in a single message → requires confirmation
        - Continuation fragments ("y 15 para conejos") → inherits context
        - Single expense → passthrough to backend
        """
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Read body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Validate request structure
        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Validate "text" field (required)
        text = data.get("text", "")
        if not isinstance(text, str) or not text.strip():
            status, error = _make_json_error(400, 'Missing required field: "text"', "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Get optional domain (default to "FIN")
        domain = data.get("domain", "FIN")
        
        # Get optional session context
        session_data = data.get("session_context", {})
        session_context: SessionContext = SessionContext(
            last_domain=session_data.get("last_domain"),
            last_moneda=session_data.get("last_moneda"),
            last_fecha=session_data.get("last_fecha"),
            last_action_type=session_data.get("last_action_type"),
        )
        
        # Check for pending flow - respect priority
        if session_data.get("pending"):
            self._send_json_response(200, {
                "ok": True,
                "type": "pending_flow",
                "items": [],
                "requires_confirmation": False,
                "clarification_questions": [],
                "should_execute": False,
                "confirmation_message": "Tienes un flujo pendiente. Complétalo antes de continuar.",
                "inherited_context": dict(session_context),
                "raw_text": text,
                "detected_domain": domain,
            })
            return
        
        # Check if this is a WORK query - route to /work/query
        if domain == "WORK":
            from .classifier import is_work_query, parse_work_query_filters
            
            if is_work_query(text, domain):
                # Parse filters from natural language
                filters = parse_work_query_filters(text)
                
                # Check Notion availability
                if not check_notion_available():
                    notion_status = get_notion_status()
                    error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
                    self._send_json_response(200, {
                        "ok": True,
                        "type": "work_query_error",
                        "items": [],
                        "requires_confirmation": False,
                        "clarification_questions": [],
                        "should_execute": False,
                        "confirmation_message": f"❌ No puedo consultar Notion: {error_msg}",
                        "inherited_context": dict(session_context),
                        "raw_text": text,
                        "detected_domain": "WORK",
                    })
                    return
                
                # Query Notion
                result = query_work_db(filters=filters, limit=20)
                formatted = format_work_query_response(result)
                
                self._send_json_response(200, {
                    "ok": True,
                    "type": "work_query",
                    "items": result["items"],
                    "requires_confirmation": False,
                    "clarification_questions": [],
                    "should_execute": True,
                    "confirmation_message": formatted,
                    "inherited_context": {"last_domain": "WORK"},
                    "raw_text": text,
                    "detected_domain": "WORK",
                    "query_filters": filters,
                    "total": result["total"],
                })
                return
        
        # Run chaperon for FIN domain
        chaperon_response = run_chaperon(
            text=text,
            domain=domain,
            session_context=session_context,
        )
        
        # Build response
        action_plan = chaperon_response["action_plan"]
        
        response_data = {
            "ok": True,
            "type": action_plan["type"],
            "items": [
                {
                    "monto": item["monto"],
                    "moneda": item["moneda"],
                    "categoria": item["categoria"],
                    "responsable": item["responsable"],
                    "descripcion": item["descripcion"],
                    "raw_segment": item["raw_segment"],
                }
                for item in action_plan["items"]
            ],
            "requires_confirmation": action_plan["requires_confirmation"],
            "clarification_questions": action_plan["clarification_questions"],
            "should_execute": chaperon_response["should_execute"],
            "confirmation_message": chaperon_response["confirmation_message"],
            "inherited_context": dict(action_plan["inherited_context"]),
            "raw_text": chaperon_response["raw_text"],
            "detected_domain": chaperon_response["detected_domain"],
        }
        
        self._send_json_response(200, response_data)
    
    def _handle_fin_expense_batch(self, remote: str) -> None:
        """Handle POST /fin/expense/batch - execute multiple expenses from confirmed action_plan.
        
        Expects a list of expense items (from chaperon) to process in batch.
        Each item is processed and stored to Sheets individually.
        """
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Read body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Validate request structure
        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Get items list
        items = data.get("items", [])
        if not isinstance(items, list) or len(items) == 0:
            status, error = _make_json_error(400, 'Missing required field: "items"', "BadRequest")
            self._send_json_response(status, error)
            return
        
        # Process each item
        results = []
        sheets_available = check_sheets_available()
        
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                results.append({
                    "index": i,
                    "ok": False,
                    "error": "Item must be a JSON object",
                    "stored": False,
                })
                continue
            
            # Build text from item for parsing
            raw_segment = item.get("raw_segment", "")
            if not raw_segment:
                # Reconstruct from fields
                monto = item.get("monto", 0)
                moneda = item.get("moneda", "USD")
                categoria = item.get("categoria", "")
                responsable = item.get("responsable", "")
                raw_segment = f"${monto} {categoria} {responsable}"
            
            # Build expense request
            expense_request: ExpenseRequest = {
                "text": raw_segment,
                "override": {
                    "responsable": item.get("responsable") or "",
                    "moneda": item.get("moneda") or "",
                },
                "session_id": data.get("session_id", ""),
            }
            
            # Parse expense
            expense_response = parse_expense(expense_request)
            
            if not expense_response["ok"] or not expense_response["expense"]:
                results.append({
                    "index": i,
                    "ok": False,
                    "error": expense_response["message"],
                    "stored": False,
                })
                continue
            
            exp = expense_response["expense"]
            
            # Override with confirmed values from batch item
            if item.get("monto") is not None:
                exp["monto"] = item["monto"]
            if item.get("moneda"):
                exp["moneda"] = item["moneda"]
            if item.get("categoria"):
                exp["categoria"] = item["categoria"]
            if item.get("responsable"):
                exp["responsable"] = item["responsable"]
            
            # Try to store to Sheets
            if sheets_available and expense_response["ok"] and not expense_response["needs_confirmation"]:
                from .tools.google.append_expense_row_tool import AppendExpenseRowTool
                sheet_result = AppendExpenseRowTool().execute({
                    "fecha": exp["fecha"],
                    "descripcion": exp["descripcion"],
                    "factura": exp.get("factura", ""),
                    "responsable": exp["responsable"],
                    "monto": exp["monto"] or 0.0,
                    "moneda": exp["moneda"],
                    "itbms": exp["itbms"] if exp.get("itbms") is not None else False,
                    "categoria": exp["categoria"],
                    "metodo_pago": exp.get("metodo_pago", "") or "",
                    "notas": exp.get("notas", ""),
                    "fuente": exp.get("fuente", "chat"),
                    "link_archivo": exp.get("link_archivo", ""),
                })

                if sheet_result.ok:
                    results.append({
                        "index": i,
                        "ok": True,
                        "stored": True,
                        "row_number": sheet_result.data["row_number"],
                        "expense": exp,
                    })
                else:
                    err_msg = sheet_result.error.message if sheet_result.error else "Unknown sheets error"
                    results.append({
                        "index": i,
                        "ok": True,
                        "stored": False,
                        "error": err_msg,
                        "expense": exp,
                    })
            else:
                results.append({
                    "index": i,
                    "ok": True,
                    "stored": False,
                    "needs_confirmation": expense_response["needs_confirmation"],
                    "missing_fields": expense_response["missing_fields"],
                    "expense": exp,
                })
        
        # Build response
        stored_count = sum(1 for r in results if r.get("stored", False))
        
        response_data = {
            "ok": True,
            "total_items": len(items),
            "stored_count": stored_count,
            "sheets_available": sheets_available,
            "results": results,
            "message": f"Procesados {len(items)} gastos, {stored_count} guardados en Sheets",
        }
        
        self._send_json_response(200, response_data)

    def _handle_fin_expense_confirm(self, remote: str) -> None:
        """Handle POST /fin/expense/confirm - confirm expense and append to Sheets."""
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message="Unauthorized")
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message="Invalid content type")
            self._send_json_response(status, error)
            return
        
        # Read body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message="Failed to read body")
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message=f"Invalid JSON: {e}")
            self._send_json_response(status, error)
            return
        
        # Validate required expense fields
        required = ["fecha", "monto", "moneda", "descripcion", "responsable"]
        missing = [f for f in required if f not in data or data[f] is None]
        if missing:
            status, error = _make_json_error(400, f'Missing required fields: {", ".join(missing)}', "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message=f"Missing fields: {missing}")
            self._send_json_response(status, error)
            return
        
        # Extract fields
        fecha = data["fecha"]
        monto = data["monto"]
        moneda = data["moneda"]
        descripcion = data["descripcion"]
        responsable = data["responsable"]
        categoria = data.get("categoria", "otros")
        itbms = data.get("itbms", False)
        metodo_pago = data.get("metodo_pago", "")
        notas = data.get("notas", "")
        factura = data.get("factura", "")
        session_id = data.get("session_id", "")
        
        # Validate monto is numeric
        try:
            monto = float(monto)
        except (ValueError, TypeError):
            status, error = _make_json_error(400, "monto must be a number", "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message="Invalid monto")
            self._send_json_response(status, error)
            return
        
        # Append to Google Sheets using new 13-column format
        from .tools.google.append_expense_row_tool import AppendExpenseRowTool
        tool_result = AppendExpenseRowTool().execute({
            "fecha": fecha,
            "descripcion": descripcion,
            "factura": factura,
            "responsable": responsable,
            "monto": monto,
            "moneda": moneda,
            "itbms": itbms,
            "categoria": categoria,
            "metodo_pago": metodo_pago,
            "notas": notas,
            "fuente": "Texto",
            "link_archivo": "",
            "expense_id": session_id,
        })

        # Log
        err_msg = "" if tool_result.ok else (tool_result.error.message if tool_result.error else "")
        _log_fin_expense_event(
            remote=remote,
            ok=tool_result.ok,
            action="sheets_append",
            monto=monto,
            moneda=moneda,
            categoria=categoria,
            responsable=responsable,
            session_id=session_id,
            error_message=err_msg,
        )

        if tool_result.ok:
            row_number = tool_result.data["row_number"]
            response = {
                "ok": True,
                "message": f"Guardado en Sheets (fila {row_number})",
                "row_number": row_number,
                "expense": {
                    "fecha": fecha,
                    "monto": monto,
                    "moneda": moneda,
                    "descripcion": descripcion,
                    "categoria": categoria,
                    "responsable": responsable,
                    "itbms": itbms,
                },
            }
            self._send_json_response(200, response)
        else:
            status, error = _make_json_error(500, err_msg, "SheetsError")
            self._send_json_response(status, error)
    
    def _handle_fin_receipt(self, remote: str) -> None:
        """
        Handle POST /fin/receipt - receive receipt image (stub).
        
        Accepts: { "filename": "...", "content_base64": "...", "text_hint": "...optional" }
        For now:
        - Saves file to memory/receipts/
        - Generates Factura ID
        - Returns pending if missing monto/fecha/responsable
        """
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            _log_fin_expense_event(remote, ok=False, action="receipt", error_message="Unauthorized")
            self._send_json_response(status, error)
            return
        
        # Check content-type
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="receipt", error_message="Invalid content type")
            self._send_json_response(status, error)
            return
        
        # Read body with larger limit for receipts
        result = self._read_body(max_bytes=WEBHOOK_MAX_BYTES_RECEIPT)
        if result[1] is not None:
            status, error = result[1]
            _log_fin_expense_event(remote, ok=False, action="receipt", error_message="Failed to read body")
            self._send_json_response(status, error)
            return
        
        body = result[0]
        
        # Parse JSON
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="receipt", error_message=f"Invalid JSON: {e}")
            self._send_json_response(status, error)
            return
        
        # Validate request structure
        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="receipt", error_message="Invalid request format")
            self._send_json_response(status, error)
            return
        
        # Validate required fields
        if "content_base64" not in data and "url" not in data:
            status, error = _make_json_error(400, 'Missing required field: "content_base64" or "url"', "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="receipt", error_message="Missing content")
            self._send_json_response(status, error)
            return
        
        # Get optional fields
        filename = data.get("filename", "")
        text_hint = data.get("text_hint", "")
        content_base64 = data.get("content_base64", "")
        url = data.get("url", "")
        
        # Generate receipt ID
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        
        if filename:
            # Use provided filename
            import os
            ext = os.path.splitext(filename)[1] or ".jpg"
            receipt_id = f"REC-{timestamp}{ext}"
        else:
            receipt_id = f"REC-{timestamp}.jpg"
        
        # Create receipts directory
        receipts_dir = MEMORY_DIR / "receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        
        local_path = ""
        
        # Save file if base64 provided
        if content_base64:
            import base64
            try:
                file_bytes = base64.b64decode(content_base64)
                file_path = receipts_dir / receipt_id
                file_path.write_bytes(file_bytes)
                local_path = str(file_path)
            except Exception as e:
                status, error = _make_json_error(400, f"Invalid base64: {e}", "BadRequest")
                _log_fin_expense_event(remote, ok=False, action="receipt", error_message=f"Base64 decode error: {e}")
                self._send_json_response(status, error)
                return
        elif url:
            # For URL mode, just store the URL reference (download later)
            local_path = url
        
        # Parse hint text for expense data if provided
        expense_data = {}
        missing_fields = []
        
        if text_hint:
            # Use existing parser to extract what we can
            expense_request: ExpenseRequest = {"text": text_hint, "override": {}, "session_id": ""}
            expense_response = parse_expense(expense_request)
            if expense_response["expense"]:
                exp = expense_response["expense"]
                expense_data = {
                    "fecha": exp["fecha"],
                    "descripcion": exp["descripcion"],
                    "responsable": exp["responsable"],
                    "monto": exp["monto"],
                    "moneda": exp["moneda"],
                    "itbms": exp["itbms"],
                    "categoria": exp["categoria"],
                    "metodo_pago": exp.get("metodo_pago", "Otro"),
                }
                # Check what's missing
                if exp["monto"] is None:
                    missing_fields.append("monto")
                if exp["responsable"] == "unknown":
                    missing_fields.append("responsable")
        else:
            # No hint - all expense fields are missing
            missing_fields = ["monto", "responsable", "descripcion"]
            from datetime import date
            expense_data = {
                "fecha": date.today().isoformat(),
                "descripcion": "",
                "responsable": "unknown",
                "monto": None,
                "moneda": "USD",
                "itbms": False,
                "categoria": "Otros",
                "metodo_pago": "Otro",
            }
        
        # Add receipt-specific fields
        expense_data["factura"] = receipt_id
        expense_data["fuente"] = "Receipt"
        expense_data["link_archivo"] = local_path
        
        needs_confirmation = len(missing_fields) > 0
        
        response_data = {
            "ok": True,
            "stored": False,  # Not stored yet - needs confirmation
            "status": "pending" if needs_confirmation else "ready",
            "needs_confirmation": needs_confirmation,
            "missing_fields": missing_fields,
            "receipt_id": receipt_id,
            "local_path": local_path,
            "expense": expense_data,
            "message": f"Receipt saved as {receipt_id}. " + (
                f"Missing fields: {', '.join(missing_fields)}. Please confirm to store."
                if needs_confirmation else "Ready to store."
            ),
            "sheets_available": check_sheets_available(),
        }
        
        _log_fin_expense_event(
            remote=remote,
            ok=True,
            action="receipt",
            session_id=receipt_id,
        )
        
        self._send_json_response(200, response_data)
    
    def _handle_shutdown(self, remote: str) -> None:
        """Handle POST /shutdown (for tests only)."""
        # Check auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        
        # Signal shutdown
        self._send_json_response(200, {"status": "ok", "message": "Shutting down"})
        
        # Schedule shutdown in separate thread to allow response to be sent
        def shutdown():
            self.server.shutdown()
        
        threading.Thread(target=shutdown, daemon=True).start()

    def _handle_work_query(self, remote: str) -> None:
        """Handle POST /work/query — see handlers/work.py for implementation."""
        from .handlers.work import handle_work_query
        handle_work_query(self, remote)

    def _handle_work_create(self, remote: str) -> None:
        """Handle POST /work/create — see handlers/work.py for implementation."""
        from .handlers.work import handle_work_create
        handle_work_create(self, remote)

    def _handle_work_delete(self, remote: str) -> None:
        """Handle POST /work/delete — see handlers/work.py for implementation."""
        from .handlers.work import handle_work_delete
        handle_work_delete(self, remote, trash_db_id=NOTION_WORK_TRASH_DB_ID)

    def _handle_work_schema_plan(self, remote: str) -> None:
        """
        Handle POST /work/schema/plan - Plan schema changes (admin only).
        
        Request JSON:
        {
            "changes": [
                {"property": "Proyecto", "add_options": ["THCyE", "NewProject"]},
                {"property": "Tags", "add_options": ["davinci", "urgent"]}
            ]
        }
        
        Response JSON:
        {
            "ok": true,
            "needs_confirmation": true,
            "action_plan": [...],
            "skipped": [...],
            "errors": [],
            "message": "📋 Plan de cambios..."
        }
        """
        try:
            # Check admin auth (admin token required)
            auth_error = self._check_auth()
            if auth_error:
                status, error = auth_error
                self._send_json_response(status, error)
                return
            
            # Verify admin token specifically (not just UI token)
            admin_token = self.headers.get("X-Assistant-Admin-Token", "")
            if not admin_token:
                status, error = _make_json_error(403, "Admin token required for schema operations", "Forbidden")
                self._send_json_response(status, error)
                return
            
            # Read body
            result = self._read_body()
            if result[1] is not None:
                status, error = result[1]
                self._send_json_response(status, error)
                return
            
            body = result[0]
            
            # Parse JSON
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError as e:
                status, error = _make_json_error(400, f"Invalid JSON: {e}", "InvalidJSON")
                self._send_json_response(status, error)
                return
            
            # Generate plan
            plan_result = generate_schema_plan(SchemaPlanRequest(changes=data.get("changes", [])))
            
            _log_webhook_event(
                "/work/schema/plan",
                remote,
                ok=plan_result["ok"],
                event_type="schema_plan",
            )
            
            self._send_json_response(200, plan_result)
            
        except Exception as e:
            _log.error("_handle_work_schema_plan exception: %s", e, exc_info=True)
            self._send_json_response(500, {
                "ok": False,
                "needs_confirmation": False,
                "action_plan": [],
                "skipped": [],
                "errors": [str(e)],
                "message": f"❌ Error interno: {e}"
            })

    def _handle_work_schema_commit(self, remote: str) -> None:
        """
        Handle POST /work/schema/commit - Apply schema changes (admin only).
        
        Request JSON: (same as /work/schema/plan)
        {
            "changes": [
                {"property": "Proyecto", "add_options": ["THCyE"]},
                {"property": "Tags", "add_options": ["davinci"]}
            ]
        }
        
        Response JSON:
        {
            "ok": true,
            "applied": [...],
            "errors": [],
            "message": "✅ 2 cambio(s) aplicado(s)..."
        }
        """
        try:
            # Check admin auth
            auth_error = self._check_auth()
            if auth_error:
                status, error = auth_error
                self._send_json_response(status, error)
                return
            
            # Verify admin token specifically
            admin_token = self.headers.get("X-Assistant-Admin-Token", "")
            if not admin_token:
                status, error = _make_json_error(403, "Admin token required for schema operations", "Forbidden")
                self._send_json_response(status, error)
                return
            
            # Read body
            result = self._read_body()
            if result[1] is not None:
                status, error = result[1]
                self._send_json_response(status, error)
                return
            
            body = result[0]
            
            # Parse JSON
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError as e:
                status, error = _make_json_error(400, f"Invalid JSON: {e}", "InvalidJSON")
                self._send_json_response(status, error)
                return
            
            # Commit changes
            commit_result = commit_schema_changes(SchemaPlanRequest(changes=data.get("changes", [])))
            
            _log_webhook_event(
                "/work/schema/commit",
                remote,
                ok=commit_result["ok"],
                event_type="schema_commit",
            )
            
            self._send_json_response(200, commit_result)
            
        except Exception as e:
            _log.error("_handle_work_schema_commit exception: %s", e, exc_info=True)
            self._send_json_response(500, {
                "ok": False,
                "applied": [],
                "errors": [str(e)],
                "message": f"❌ Error interno: {e}"
            })

    # -------------------------------------------------------------------------
    # CodeOps Endpoints
    # -------------------------------------------------------------------------

    def _handle_codeops_plan(self, remote: str) -> None:
        """
        Handle POST /codeops/plan - Plan a code task.
        
        Request JSON (TaskSpec):
        {
            "repo": "owner/repo",
            "goal": "Add unit tests for auth module",
            "base_branch": "main",          // optional
            "module_scope": "src/auth",     // optional
            "acceptance": "All tests pass"  // optional
        }
        
        Response JSON (PlanResponse):
        {
            "ok": true,
            "steps": [...],
            "files_to_touch": [...],
            "warnings": [...],
            "error": null
        }
        """
        context_id = new_context_id()
        
        try:
            # Check auth
            auth_error = self._check_auth()
            if auth_error:
                status, error = auth_error
                self._send_json_response(status, error)
                return
            
            # Read body with CodeOps-specific limit
            result = self._read_body(max_bytes=CODEOPS_MAX_BYTES)
            if result[1] is not None:
                status, error = result[1]
                self._send_json_response(status, error)
                return
            
            body = result[0]
            
            # Parse JSON
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError as e:
                status, error = _make_json_error(400, f"Invalid JSON: {e}", "InvalidJSON")
                self._send_json_response(status, error)
                return
            
            # Validate TaskSpec
            is_valid, validation_error = validate_task_spec(data)
            if not is_valid:
                _log_codeops_event(
                    remote=remote,
                    endpoint="/codeops/plan",
                    ok=False,
                    context_id=context_id,
                    error_message=validation_error,
                )
                self._send_json_response(400, {
                    "ok": False,
                    "steps": [],
                    "files_to_touch": [],
                    "warnings": [],
                    "error": validation_error,
                })
                return
            
            repo = data.get("repo", "")
            goal = data.get("goal", "")
            module_scope = data.get("module_scope")
            
            # Guardrail: Check repo allowlist
            if not is_repo_allowed(repo):
                _log_codeops_event(
                    remote=remote,
                    endpoint="/codeops/plan",
                    ok=False,
                    repo=repo,
                    goal=goal,
                    context_id=context_id,
                    error_message=f"Repository not allowed: {repo}",
                )
                self._send_json_response(403, {
                    "ok": False,
                    "steps": [],
                    "files_to_touch": [],
                    "warnings": [],
                    "error": f"Repository '{repo}' is not in the allowed list",
                })
                return
            
            # Guardrail: Check module_scope is within workspace if provided
            if module_scope:
                from pathlib import Path
                scope_path = Path(module_scope)
                # Only reject if it looks like an absolute path trying to escape
                if scope_path.is_absolute() and not is_path_in_workspace(scope_path):
                    _log_codeops_event(
                        remote=remote,
                        endpoint="/codeops/plan",
                        ok=False,
                        repo=repo,
                        goal=goal,
                        context_id=context_id,
                        error_message=f"module_scope outside workspace: {module_scope}",
                    )
                    self._send_json_response(400, {
                        "ok": False,
                        "steps": [],
                        "files_to_touch": [],
                        "warnings": [],
                        "error": f"module_scope must be a relative path within the workspace",
                    })
                    return
            
            # Create handler and plan task
            handler = CodeOpsHandler()
            plan_result: PlanResponse = handler.plan_task(data)
            
            _log_codeops_event(
                remote=remote,
                endpoint="/codeops/plan",
                ok=plan_result["ok"],
                repo=repo,
                goal=goal,
                context_id=context_id,
                warnings=plan_result.get("warnings"),
                error_message=plan_result.get("error") or "",
            )
            
            self._send_json_response(200, plan_result)
            
        except Exception as e:
            _log.error("_handle_codeops_plan exception: %s", e, exc_info=True)

            _log_codeops_event(
                remote=remote,
                endpoint="/codeops/plan",
                ok=False,
                context_id=context_id,
                error_message=str(e),
            )
            
            self._send_json_response(500, {
                "ok": False,
                "steps": [],
                "files_to_touch": [],
                "warnings": [],
                "error": f"Internal error: {e}",
            })

    def _handle_codeops_pr(self, remote: str) -> None:
        """
        Handle POST /codeops/pr - Create a PR from task spec.
        
        NOTE: Currently returns mock response. Full implementation requires:
        - GITHUB_TOKEN environment variable
        - CODEOPS_LIVE_MODE=true to enable actual operations
        
        Request JSON (TaskSpec):
        {
            "repo": "owner/repo",
            "goal": "Add unit tests for auth module",
            "base_branch": "main",          // optional
            "module_scope": "src/auth",     // optional
            "acceptance": "All tests pass"  // optional
        }
        
        Response JSON (PRResponse):
        {
            "ok": true,
            "pr_number": 1,
            "pr_url": "https://github.com/owner/repo/pull/1",
            "branch": "codeops/add-unit-tests",
            "error": null
        }
        """
        context_id = new_context_id()
        
        try:
            # Check auth
            auth_error = self._check_auth()
            if auth_error:
                status, error = auth_error
                self._send_json_response(status, error)
                return
            
            # Read body with CodeOps-specific limit
            result = self._read_body(max_bytes=CODEOPS_MAX_BYTES)
            if result[1] is not None:
                status, error = result[1]
                self._send_json_response(status, error)
                return
            
            body = result[0]
            
            # Parse JSON
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError as e:
                status, error = _make_json_error(400, f"Invalid JSON: {e}", "InvalidJSON")
                self._send_json_response(status, error)
                return
            
            # Validate TaskSpec
            is_valid, validation_error = validate_task_spec(data)
            if not is_valid:
                _log_codeops_event(
                    remote=remote,
                    endpoint="/codeops/pr",
                    ok=False,
                    context_id=context_id,
                    error_message=validation_error,
                )
                self._send_json_response(400, {
                    "ok": False,
                    "pr_number": None,
                    "pr_url": None,
                    "branch": None,
                    "error": validation_error,
                })
                return
            
            repo = data.get("repo", "")
            goal = data.get("goal", "")
            module_scope = data.get("module_scope")
            
            # Guardrail: Check repo allowlist
            if not is_repo_allowed(repo):
                _log_codeops_event(
                    remote=remote,
                    endpoint="/codeops/pr",
                    ok=False,
                    repo=repo,
                    goal=goal,
                    context_id=context_id,
                    error_message=f"Repository not allowed: {repo}",
                )
                self._send_json_response(403, {
                    "ok": False,
                    "pr_number": None,
                    "pr_url": None,
                    "branch": None,
                    "error": f"Repository '{repo}' is not in the allowed list",
                })
                return
            
            # Guardrail: Check module_scope is within workspace if provided
            if module_scope:
                from pathlib import Path
                scope_path = Path(module_scope)
                if scope_path.is_absolute() and not is_path_in_workspace(scope_path):
                    _log_codeops_event(
                        remote=remote,
                        endpoint="/codeops/pr",
                        ok=False,
                        repo=repo,
                        goal=goal,
                        context_id=context_id,
                        error_message=f"module_scope outside workspace: {module_scope}",
                    )
                    self._send_json_response(400, {
                        "ok": False,
                        "pr_number": None,
                        "pr_url": None,
                        "branch": None,
                        "error": f"module_scope must be a relative path within the workspace",
                    })
                    return
            
            # Warn if live mode is disabled (but still return mock response)
            if not CODEOPS_LIVE_MODE:
                print(f"[CODEOPS] Live mode disabled - returning mock PR response for {repo}")
            
            # Create handler and create PR
            handler = CodeOpsHandler()
            pr_result: PRResponse = handler.create_pr(data)
            
            _log_codeops_event(
                remote=remote,
                endpoint="/codeops/pr",
                ok=pr_result["ok"],
                repo=repo,
                goal=goal,
                context_id=context_id,
                pr_url=pr_result.get("pr_url") or "",
                error_message=pr_result.get("error") or "",
            )
            
            self._send_json_response(200, pr_result)
            
        except Exception as e:
            _log.error("_handle_codeops_pr exception: %s", e, exc_info=True)

            _log_codeops_event(
                remote=remote,
                endpoint="/codeops/pr",
                ok=False,
                context_id=context_id,
                error_message=str(e),
            )
            
            self._send_json_response(500, {
                "ok": False,
                "pr_number": None,
                "pr_url": None,
                "branch": None,
                "error": f"Internal error: {e}",
            })


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class WebhookHTTPServer(HTTPServer):
    """HTTP Server with clean shutdown support."""
    
    allow_reuse_address = True
    
    def __init__(self, host: str, port: int):
        super().__init__((host, port), WebhookHandler)
        self._shutdown_flag = False


def _print_integration_banner() -> None:
    """Print an integration health banner to stdout on server startup."""
    from .executors.startup import get_code_executor_status, get_propose_executor_status

    notion_ok = check_notion_available()
    notion_status = get_notion_status()
    sheets_status = get_sheets_status()
    sheets_ok = sheets_status.get("ok", False)
    code_status = get_code_executor_status()
    code_ok = code_status["live"]
    propose_status = get_propose_executor_status()
    propose_ok = propose_status["live"]

    def _line(label: str, ok: bool, detail: str = "") -> str:
        badge = "OK  " if ok else "STUB"
        suffix = f"  ({detail})" if detail else ""
        return f"  {label:<24} {badge}{suffix}"

    notion_detail = ""
    if not notion_ok:
        err = notion_status.get("last_error") or {}
        notion_detail = err.get("message", "unavailable")

    sheets_detail = ""
    if not sheets_ok:
        err = sheets_status.get("last_error") or {}
        sheets_detail = err.get("message", "unavailable")

    code_detail = code_status["model"] if code_ok else "set ANTHROPIC_API_KEY to enable"
    propose_detail = propose_status["model"] if propose_ok else "set ANTHROPIC_API_KEY to enable"

    print()
    print("INTEGRATION STATUS")
    print("------------------")
    print(_line("Notion:", notion_ok, notion_detail))
    print(_line("Google Sheets:", sheets_ok, sheets_detail))
    print(_line("CODE (read):", code_ok, code_detail))
    print(_line("CODE (preview):", propose_ok, propose_detail))
    print(_line("Classifier:", True))
    print(_line("Pipelines:", True))
    print()


def run_server(host: str = WEBHOOK_HOST, port: int = WEBHOOK_PORT) -> None:
    """
    Start the webhook HTTP server.

    Args:
        host: Bind address (default: 127.0.0.1)
        port: Port number (default: 8787)
    """
    from .executors.startup import setup_all_code_executors
    setup_all_code_executors()

    server = WebhookHTTPServer(host, port)

    _print_integration_banner()

    print(f"Starting Assistant OS Webhook Server on http://{host}:{port}")
    print("Endpoints:")
    print(f"  GET  /chat            - Web chat interface")
    print(f"  GET  /chat/history    - Chat history (requires token)")
    print(f"  POST /command         - Execute commands (full response)")
    print(f"  POST /command/summary - Execute commands (mobile-friendly summary)")
    print(f"  POST /classify        - Classify intent (deterministic)")
    print(f"  POST /fin/plan        - Generate expense plan (Plan Always)")
    print(f"  POST /fin/commit      - Commit expense to Sheets")
    print(f"  POST /fin/expense     - Register expense (legacy, auto-store)")
    print(f"  POST /fin/chaperon    - Pre-process text (multi-expense)")
    print(f"  POST /fin/expense/batch - Execute batch expenses")
    print(f"  POST /fin/receipt     - Upload receipt image (stub)")
    print(f"  POST /work/query      - Query WORK tasks (Notion, read-only)")
    print(f"  POST /work/schema/plan - Plan schema changes (admin only)")
    print(f"  POST /work/schema/commit - Apply schema changes (admin only)")
    print(f"  POST /codeops/plan    - Plan code task (no execution)")
    print(f"  POST /codeops/pr      - Create PR from task (mock for now)")
    print(f"  GET  /health          - Health check")
    print(f"  POST /shutdown        - Shutdown server (requires token)")
    print()
    print("Press Ctrl+C to stop.")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()


def start_server_thread(host: str = WEBHOOK_HOST, port: int = 0) -> tuple[WebhookHTTPServer, int]:
    """
    Start server in a background thread (for testing).
    
    Args:
        host: Bind address
        port: Port number (0 = auto-assign)
    
    Returns:
        (server_instance, actual_port)
    """
    server = WebhookHTTPServer(host, port)
    actual_port = server.server_address[1]
    
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    
    return server, actual_port


if __name__ == "__main__":
    run_server()
