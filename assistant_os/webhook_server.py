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
from socketserver import ThreadingMixIn
from typing import Any, Optional

from .config import (
    WEBHOOK_TOKEN,
    WEBHOOK_HOST,
    WEBHOOK_PORT,
    WEBHOOK_MAX_BYTES,
    WEBHOOK_MAX_BYTES_RECEIPT,
    WEBHOOK_INCLUDE_RAW_DEFAULT,
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
# A1.5: parse_command_to_request / route_request are kept available for
# router.py callers and tests; they are no longer called from the webhook
# handler after the canonical reroute (all text goes through handle_request).
from .router import parse_command_to_request, route_request  # noqa: F401
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
from .operability import (
    build_agents_registry_response,
    build_mso_state_response,
    build_system_capabilities_response,
)
from .system_assistant.observer import observe_system
from .system_assistant.interpreter import interpret_system_snapshot
from .mso.governance_surface import get_governance_summary, get_operational_mode, get_recent_governance

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
# Planner re-exports (backward compatibility)
# Authoritative implementations moved to core/planner.py in M0.7B.
# These names are re-exported here so existing test imports continue to
# work without modification.  The real owner is core.planner.
# ---------------------------------------------------------------------------
from .core.planner import (  # noqa: E402
    _has_test_intent,
    _has_test_reset_intent,
    _is_invalid_title,
    _has_create_intent,
    _apply_routing_overrides,
    _create_plan_from_intent,
)
# parse_work_create_fields: authoritative owner is parsers.work_create_parser.
# Re-exported here for backward compatibility with existing test imports.
from .parsers.work_create_parser import parse_work_create_fields  # noqa: F401


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
    surface: str = "",
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

    if surface:
        event["surface"] = surface
    
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



def _process_mso_confirm_request(body_bytes: bytes) -> tuple[int, dict]:
    """Parse and validate a confirm request body. Returns (status_code, response_dict).

    Writes a HumanConfirmationRecord. Does NOT grant execution authority, satisfy any
    authority chain step, issue tokens, call PoliceGate, or invoke runner.
    execution_allowed and can_execute_now remain False.
    """
    import json as _json

    from .mso.human_confirmation import record_human_confirmation
    from .mso.prepared_action_queue import get_confirmable_action_queue_entry

    try:
        data = _json.loads(body_bytes) if body_bytes else {}
    except Exception:  # noqa: BLE001
        return 400, {"ok": False, "error": "Invalid JSON body"}

    entry_id = (data.get("entry_id") or "").strip()
    action_id = (data.get("action_id") or "").strip()
    confirmed = data.get("confirmed")
    operator_note = data.get("operator_note") or ""

    if not entry_id:
        return 400, {"ok": False, "error": "entry_id required"}
    if not action_id:
        return 400, {"ok": False, "error": "action_id required"}
    if not isinstance(confirmed, bool):
        return 400, {"ok": False, "error": "confirmed must be bool (true or false)"}

    entry = get_confirmable_action_queue_entry(entry_id)
    if entry is None:
        return 404, {"ok": False, "error": "prepared action not found", "entry_id": entry_id}

    record = record_human_confirmation(
        entry_id=entry_id,
        action_id=action_id,
        confirmed=confirmed,
        operator_note=operator_note,
    )

    return 200, {
        "ok": True,
        "entry_id": entry_id,
        "action_id": action_id,
        "human_confirmation_status": "human_confirmed" if confirmed else "human_rejected",
        "execution_allowed": False,
        "can_execute_now": False,
        "recorded_at": record.recorded_at.isoformat(),
        "note": (
            "Human confirmation recorded. Execution remains closed. "
            "Full authority chain (PolicyDecision → CapabilityToken → OperationBinding "
            "→ AuthorizedPlan → PoliceGate) is still required."
        ),
    }


def _process_mso_policy_review_request(body_bytes: bytes) -> tuple[int, dict]:
    """Parse, validate, and evaluate MSO capability policy for a confirmed prepared action.

    Returns (status_code, response_dict).
    Produces an MSOPolicyDecisionDraft — the first authority chain artifact.

    Does NOT: issue CapabilityToken, create OperationBinding/AuthorizedPlan, call
    PoliceGate, invoke runner or Machine Operator, or change execution_allowed.
    execution_allowed and can_execute_now remain False always.
    """
    import json as _json

    try:
        data = _json.loads(body_bytes) if body_bytes else {}
    except Exception:  # noqa: BLE001
        return 400, {"ok": False, "error": "Invalid JSON body"}

    entry_id = (data.get("entry_id") or "").strip()
    action_id = (data.get("action_id") or "").strip()

    if not entry_id or not action_id:
        return 400, {"ok": False, "error": "entry_id and action_id are required"}

    from .mso.prepared_action_queue import get_confirmable_action_queue_entry
    from .mso.human_confirmation import get_human_confirmation
    from .mso.policy_review import evaluate_mso_policy_for_prepared_action

    entry = get_confirmable_action_queue_entry(entry_id)
    if entry is None:
        return 404, {"ok": False, "error": f"Queue entry not found: {entry_id!r}"}

    confirmation = get_human_confirmation(entry_id)
    if confirmation is None:
        return 422, {
            "ok": False,
            "error": "confirmation_required: no human confirmation recorded for this entry",
            "execution_allowed": False,
            "can_execute_now": False,
        }

    if not confirmation.confirmed:
        return 422, {
            "ok": False,
            "error": "action_rejected: action was rejected by operator, cannot evaluate policy",
            "execution_allowed": False,
            "can_execute_now": False,
        }

    if confirmation.action_id != action_id:
        return 400, {
            "ok": False,
            "error": (
                f"action_id mismatch: confirmation has action_id={confirmation.action_id!r}, "
                f"request has action_id={action_id!r}"
            ),
            "execution_allowed": False,
            "can_execute_now": False,
        }

    try:
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
    except ValueError as exc:
        return 422, {
            "ok": False,
            "error": str(exc),
            "execution_allowed": False,
            "can_execute_now": False,
        }

    return 200, {
        "ok": True,
        "entry_id": draft.entry_id,
        "action_id": draft.action_id,
        "policy_review_id": draft.policy_review_id,
        "policy_outcome": draft.policy_outcome,
        "capability_mode": draft.capability_mode,
        "execution_allowed": False,
        "can_execute_now": False,
        "used_execution": False,
        "human_confirmation_satisfied": draft.human_confirmation_satisfied,
        "created_at": draft.created_at.isoformat(),
        "note": (
            "Policy decision draft recorded. Execution remains closed. "
            "CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate still required."
        ),
    }


def _process_mso_authority_binding_request(body_bytes: bytes) -> tuple[int, dict]:
    """Parse, validate, and create an MSOAuthorityBindingDraft for an approved prepared action.

    Returns (status_code, response_dict).

    Does NOT: call token_issuer.issue_token(), create OperationBinding/AuthorizedPlan,
    call PoliceGate enforcement.check(), invoke RunnerAPI.execute(), or change
    execution_allowed. execution_allowed, can_execute_now, and used_execution remain False always.
    """
    import json as _json

    try:
        data = _json.loads(body_bytes) if body_bytes else {}
    except Exception:  # noqa: BLE001
        return 400, {"ok": False, "error": "Invalid JSON body"}

    entry_id = (data.get("entry_id") or "").strip()
    action_id = (data.get("action_id") or "").strip()

    if not entry_id or not action_id:
        return 400, {"ok": False, "error": "entry_id and action_id are required"}

    from .mso.prepared_action_queue import get_confirmable_action_queue_entry
    from .mso.policy_review import get_mso_policy_review
    from .mso.authority_binding import create_mso_authority_binding

    entry = get_confirmable_action_queue_entry(entry_id)
    if entry is None:
        return 404, {"ok": False, "error": f"Queue entry not found: {entry_id!r}"}

    if entry.prepared_action_id != action_id:
        return 400, {
            "ok": False,
            "error": (
                f"action_id mismatch: entry has action_id={entry.prepared_action_id!r}, "
                f"request has action_id={action_id!r}"
            ),
            "execution_allowed": False,
            "can_execute_now": False,
        }

    policy_review = get_mso_policy_review(entry_id)
    if policy_review is None:
        return 422, {
            "ok": False,
            "error": "policy_review_required: no policy review recorded for this entry",
            "execution_allowed": False,
            "can_execute_now": False,
        }

    if policy_review.policy_outcome not in ("approved", "approved_confirm_only"):
        return 422, {
            "ok": False,
            "error": (
                f"policy_denied: policy_outcome={policy_review.policy_outcome!r} "
                "does not permit authority binding"
            ),
            "execution_allowed": False,
            "can_execute_now": False,
            "policy_outcome": policy_review.policy_outcome,
        }

    try:
        binding = create_mso_authority_binding(entry, policy_review)
    except ValueError as exc:
        return 422, {
            "ok": False,
            "error": str(exc),
            "execution_allowed": False,
            "can_execute_now": False,
        }

    return 200, {
        "ok": True,
        "entry_id": binding.entry_id,
        "action_id": binding.action_id,
        "policy_review_id": binding.policy_review_id,
        "authority_binding_id": binding.authority_binding_id,
        "binding_status": binding.binding_status,
        "requires_authorized_plan": binding.requires_authorized_plan,
        "requires_police_gate": binding.requires_police_gate,
        "execution_allowed": False,
        "can_execute_now": False,
        "used_execution": False,
        "created_at": binding.created_at.isoformat(),
        "note": (
            "Authority binding draft recorded. "
            "AuthorizedPlan, PoliceGate, and execution still required."
        ),
    }


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
        # "type" stays at top level for backward compat with summary.py consumers.
        # Mirrors the legacy type string stored in data["type"] when present,
        # otherwise falls back to result_type.
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

    Dispatch priority:
    1. Cross-domain result_types (plan_confirmation_required, plan_generated) — checked
       FIRST regardless of domain, because these are kernel-level states that must not be
       intercepted by domain-specific wrappers.
    2. Domain-specific cases (WORK, FIN) — only reached for fully-executed domain results.
    3. Fallback: unknown domain/result_type.

    Invariant: result_type is the authoritative semantic signal. Domain is secondary.
    """
    domain = dr.get("domain", "UNKNOWN")
    result_type = dr.get("result_type", "")

    # --- Cross-domain result_types: checked before any domain-specific dispatch ---
    # plan_confirmation_required is produced exclusively by core/orchestrator.py when
    # requires_confirmation=True. It is never produced by domain pipelines.
    # Checking domain first would silently swallow the pending-confirmation semantic.
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

    # --- Domain-specific dispatch: only for fully-executed domain results ---
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

    if domain == "HOST":
        return _host_dr_to_response(dr)

    # Fallback: unknown domain/result_type
    return {
        "context_id": context_id,
        "agent": "kernel",
        "status": "ok" if dr["ok"] else "error",
        "output": dr.get("data", {}),
        "error": dr.get("error"),
        "ts": now_iso(),
    }


# /chat/process result_type → intent label (authoritative mapping)
_CHAT_RESULT_TYPE_TO_INTENT: dict = {
    "plan_confirmation_required": "confirm",
    "plan_generated": "plan",
    "cognitive_execution": "cognitive",
    "denied": "denied",
    "error": "error",
    "confirm_error": "error",
}


def _chat_wire_from_domain_result(
    dr: "DomainResult",
    *,
    context_id: str,
    action_raw: "dict | None",
    identity: "Any",
    guard_result: "Any",
    surface: str = "",
) -> dict:
    """Adapt a DomainResult from handle_request to the /chat/process wire format.

    Sole translation layer between the MSO kernel output and the chat UI
    contract.  No domain logic here — only field projection.

    session.pending_confirm_plan_id carries the plan_id so the next turn
    can route through metadata["confirm_plan_id"] to the confirmation path.
    """
    domain = dr.get("domain", "UNKNOWN")
    result_type = dr.get("result_type", "")
    data = dr.get("data") or {}

    intent = _CHAT_RESULT_TYPE_TO_INTENT.get(result_type, result_type or "processed")
    needs_confirmation = (result_type == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED)

    # Plan list: orchestrator stores the plan dict inside data["plan"].
    plan_raw = data.get("plan", {})
    if isinstance(plan_raw, dict) and plan_raw:
        plan_list: list = [plan_raw]
    elif isinstance(plan_raw, list):
        plan_list = plan_raw
    else:
        plan_list = []

    # Confirmation UI actions — only emitted when kernel decided confirm.
    ui_actions: list = []
    if needs_confirmation:
        ui_actions = [
            {"type": "confirm", "label": "Confirmar"},
            {"type": "cancel", "label": "Cancelar"},
        ]

    # Session: carry context_id and plan_id for next-turn confirmation.
    plan_id = data.get("plan_id", "")
    session_out: dict = {"context_id": context_id, "last_domain": domain}
    if plan_id:
        session_out["pending_confirm_plan_id"] = plan_id

    # Audit: expose MSO decision metadata for client observability.
    _gov = data.get("governance_trace") or {}
    base_audit: dict = {
        "result_type": result_type,
        "domain": domain,
        "execution_mode": _gov.get("effective_execution_mode", ""),
        "mso_decided": True,
    }
    if isinstance(action_raw, dict):
        base_audit["action_type"] = action_raw.get("type")
        base_audit["action_target"] = action_raw.get("target")
        base_audit["action_id"] = action_raw.get("id")
    if surface:
        base_audit["surface"] = surface

    wire: dict = {
        "ok": bool(dr.get("ok", True)),
        "message": dr.get("message", ""),
        "trace_id": context_id,
        "domain": domain,
        "intent": intent,
        "mode": "chat",
        "needs_confirmation": needs_confirmation,
        "missing_fields": [],
        "plan": plan_list,
        "ui_actions": ui_actions,
        "session": session_out,
        "audit": base_audit,
        "identity": identity.to_audit_dict(),
        "guard": guard_result.to_audit_dict(),
        "response_source": "orchestrator",
    }
    if "execution_status" in dr:
        wire["execution_status"] = dr["execution_status"]
    return wire


# ---------------------------------------------------------------------------
# A1.5: _gated_legacy_route REMOVED
#
# This function was introduced in A1-FIX as a separate mini-policy path for
# prefix commands (CODE:, DOC:, JOBS:, BIZ:).  It used synthetic identity
# values (subject_state="active", guard_decision="allow") that were never
# grounded in a real RequestIdentity — a structural weakness.
#
# A1.5 eliminates the parallel path entirely.  All text — with or without a
# legacy prefix — now routes through _route_text_by_classification(), which
# calls handle_request() via the canonical orchestrator.  Policy (S10),
# token (S12), and grant (S13) enforcement are applied uniformly by the
# orchestrator, with the same identity context used for every request.
#
# The legacy prefix-detection helpers (_has_command_prefix, _has_invalid_prefix)
# are kept as utility functions but no longer drive separate code paths.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# HOST HTTP layer — Phase 4B contract helpers
#
# All HOST HTTP responses use the canonical shape:
#   { ok, domain, result_type, data, error: {type, message, code} | null }
#
# These helpers are the sole source of HOST response construction. Neither
# _handle_host_action nor _handle_host_confirm build dicts directly.
# ---------------------------------------------------------------------------

# Actions accepted by the HTTP API. ONLY short names — no HOST_ prefix aliases.
_HOST_VALID_ACTIONS: frozenset = frozenset({
    "open_app", "close_pid", "open_directory", "open_url",
    "list_directory", "open_file", "read_text_file",
    # Phase 5A/5B — sandboxed write (all require confirmation)
    "write_text_file", "append_text_file", "create_directory",
})

# Short name → canonical ACTION_HOST_* constant value
_HOST_SHORT_TO_CANONICAL: dict = {
    "open_app":       "HOST_OPEN_APP",
    "close_pid":      "HOST_CLOSE_PID",
    "open_directory": "HOST_OPEN_DIRECTORY",
    "open_url":       "HOST_OPEN_URL",
    "list_directory": "HOST_LIST_DIRECTORY",
    "open_file":      "HOST_OPEN_FILE",
    "read_text_file": "HOST_READ_TEXT_FILE",
    # Phase 5A/5B
    "write_text_file":  "HOST_WRITE_TEXT_FILE",
    "append_text_file": "HOST_APPEND_TEXT_FILE",
    "create_directory": "HOST_CREATE_DIRECTORY",
}

# Canonical action → risk level (definitive, not overridable by callers)
# Write actions are RISK_MEDIUM: they mutate filesystem state but are
# contained in the sandbox and individually reversible by the user.
# They are intentionally NOT low-risk: no write action should auto-execute.
_HOST_ACTION_RISK: dict = {
    "HOST_OPEN_APP":       "medium",
    "HOST_CLOSE_PID":      "medium",
    "HOST_OPEN_DIRECTORY": "medium",
    "HOST_OPEN_URL":       "medium",
    "HOST_LIST_DIRECTORY": "low",
    "HOST_OPEN_FILE":      "medium",
    "HOST_READ_TEXT_FILE": "low",
    # Phase 5A/5B — write actions: always RISK_MEDIUM (confirm required)
    "HOST_WRITE_TEXT_FILE":  "medium",
    "HOST_APPEND_TEXT_FILE": "medium",
    "HOST_CREATE_DIRECTORY": "medium",
}

# error type/code → structured CODE value (enriched in HTTP layer, not pipeline)
_HOST_ERROR_CODE_MAP: dict = {
    "PlanNotFound":            "PLAN_NOT_FOUND",
    "ControlPlaneBlocked":     "CONTROL_PLANE_BLOCKED",
    "control_plane_blocked":   "CONTROL_PLANE_BLOCKED",   # HostErrorCode enum value
    "InvalidHostPayload":      "INVALID_HOST_PAYLOAD",
    "directory_not_found":     "DIRECTORY_NOT_FOUND",
    "directory_not_allowed":   "DIRECTORY_NOT_ALLOWED",
    "file_not_allowed":        "FILE_NOT_ALLOWED",
    "extension_not_allowed":   "EXTENSION_NOT_ALLOWED",
    "file_not_found":          "FILE_NOT_FOUND",
    "file_too_large":          "FILE_TOO_LARGE",
    "invalid_encoding":        "INVALID_ENCODING",
    "rate_limit_exceeded":     "RATE_LIMIT_EXCEEDED",
    "BadRequest":              "BAD_REQUEST",
    "Unauthorized":            "UNAUTHORIZED",
    "Forbidden":               "FORBIDDEN",
    "PipelineError":           "PIPELINE_ERROR",
    "HostPipelineError":       "PIPELINE_ERROR",
    "HostActionFailed":        "HOST_ACTION_FAILED",
    # Phase 5A/5B — write action error codes
    "write_not_allowed":        "WRITE_NOT_ALLOWED",
    "path_conflict":            "PATH_CONFLICT",
    "directory_already_exists": "DIRECTORY_ALREADY_EXISTS",
}

# Constant for pre-pipeline (HTTP-layer) errors that have no DomainResult
_HOST_RESULT_TYPE_ERROR = "host_error"


def _host_error(type_: str, message: str, code: str | None = None) -> dict:
    """Build a structured HOST error object: {type, message, code}."""
    return {
        "type":    type_,
        "message": message,
        "code":    code or _HOST_ERROR_CODE_MAP.get(type_, type_.upper()),
    }


def _host_response(
    ok: bool,
    result_type: str,
    data: dict,
    error: "dict | None",
) -> dict:
    """Build the canonical HOST HTTP response body.

    Contract (all cases):
      {
        "ok":          bool,
        "domain":      "HOST",
        "result_type": str,
        "data":        dict,
        "error":       {"type": str, "message": str, "code": str} | null
      }

    Invariants:
    - domain is always "HOST"
    - result_type is always present (may be "" for pre-pipeline errors)
    - error is always present (null or structured dict with type/message/code)
    - no extra fields (no "status", "agent", "message", "ts", "context_id")
    """
    return {
        "ok":          ok,
        "domain":      "HOST",
        "result_type": result_type,
        "data":        data if data is not None else {},
        "error":       error,
    }


def _host_dr_to_response(dr: "DomainResult") -> dict:
    """Convert a HOST DomainResult to the canonical HOST response shape.

    - Normalizes dr["error"] to include 'code'.
    - Handles control_plane_blocked from both dr["error"]["type"] and
      dr["data"]["error_code"] (both are produced depending on the code path).
    """
    dr_data   = dr.get("data") or {}
    raw_error = dr.get("error")

    if raw_error:
        error = _host_error(
            type_=raw_error.get("type", "UnknownError"),
            message=raw_error.get("message", ""),
        )
    elif not dr.get("ok"):
        # Fallback: error_code in data with no dr["error"]
        ec = dr_data.get("error_code", "")
        error = _host_error(ec, f"Agent error: {ec}") if ec else _host_error("UnknownError", "Unexpected failure")
    else:
        error = None

    return _host_response(
        ok=dr.get("ok", False),
        result_type=dr.get("result_type", ""),
        data=dr_data,
        error=error,
    )


def _host_http_status(dr: "DomainResult") -> int:
    """Map a HOST DomainResult to the correct HTTP status code.

    Definitive mapping:
      202  plan_confirmation_required
      200  host_action ok=True (or any ok=True)
      404  confirm_error + PlanNotFound | file_not_found (append)
      409  control_plane_blocked | path_conflict | directory_already_exists
      400  InvalidHostPayload | write/read validation errors
      500  unexpected pipeline errors
    """
    from .contracts import (
        RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
        RESULT_TYPE_CONFIRM_ERROR,
    )
    result_type = dr.get("result_type", "")
    dr_error    = dr.get("error") or {}
    dr_data     = dr.get("data") or {}
    error_type  = dr_error.get("type", "")
    error_code  = dr_data.get("error_code", "")

    if result_type == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED:
        return 202
    if dr.get("ok"):
        return 200
    # 404 — resource not found
    if result_type == RESULT_TYPE_CONFIRM_ERROR and error_type == "PlanNotFound":
        return 404
    if error_type == "file_not_found" or error_code == "file_not_found":
        return 404
    # 409 — conflict / control plane blocked
    if error_type in ("control_plane_blocked", "path_conflict", "directory_already_exists"):
        return 409
    if error_code in ("control_plane_blocked", "path_conflict", "directory_already_exists"):
        return 409
    # 400 — client / payload validation errors
    _400_error_types = frozenset({
        "InvalidHostPayload",
        "file_not_allowed", "extension_not_allowed", "file_too_large",
        "invalid_encoding", "directory_not_allowed", "directory_not_found",
        "write_not_allowed", "confirmed_required", "rate_limit_exceeded",
        "invalid_app_name", "invalid_pid", "pid_not_owned",
        "process_already_exited", "url_invalid", "url_scheme_not_allowed",
        "url_domain_not_allowed",
    })
    if error_type in _400_error_types or error_code in _400_error_types:
        return 400
    return 500


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
# HTTP Handler
# ---------------------------------------------------------------------------
# NOTE: _has_create_intent, _apply_routing_overrides, _create_plan_from_intent,
# parse_work_create_fields, etc. were defined here prior to M0.7B.  They are
# now re-exported from core/planner.py and parsers/work_create_parser.py
# via the compatibility block above.  The HTTP Handler follows directly.
# ---------------------------------------------------------------------------





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
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, X-Assistant-Token",
            )
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

        Fail-closed: if WEBHOOK_TOKEN is not configured, rejects ALL requests
        with 503 — the server is misconfigured and must not accept traffic.

        Accepts:
        - X-Assistant-Token: standard UI token (WEBHOOK_TOKEN)
        """
        if not WEBHOOK_TOKEN:
            return _make_json_error(
                503,
                "Server authentication not configured — WEBHOOK_TOKEN is required.",
                "ServiceUnavailable",
            )
        token = self.headers.get("X-Assistant-Token", "")
        if token == WEBHOOK_TOKEN:
            return None
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
        
        # Route: /mso/outcome/status
        if path == "/mso/outcome/status":
            status, error = _make_json_error(405, "Method not allowed", "MethodNotAllowed")
            self._send_json_response(status, error)
            return

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
        
        # Route: /host/action (execute HOST action through orchestrator)
        if path == "/host/action":
            self._handle_host_action(remote)
            return

        # Route: /host/confirm (confirm a pending HOST plan by plan_id)
        if path == "/host/confirm":
            self._handle_host_confirm(remote)
            return

        # Route: /codeops/plan (plan code task - no execution)
        if path == "/codeops/plan":
            self._handle_codeops_plan(remote)
            return
        
        # Route: /codeops/pr (create PR from task - mock for now)
        if path == "/codeops/pr":
            self._handle_codeops_pr(remote)
            return

        # M29: POST /cognition/preferences — update cognitive usage policy
        if path == "/cognition/preferences":
            self._handle_cognition_preferences_post(remote)
            return

        # ALFA kill-switch: POST /admin/governance/mode
        # Sets or clears the system operational mode (FROZEN / DEGRADED / RESTRICTED / NORMAL).
        # FROZEN blocks ALL execution across every path including /chat/process.
        if path == "/admin/governance/mode":
            self._handle_governance_mode(remote)
            return

        # UI operator freeze/restore — proxied from ui/app/api/system/freeze/route.ts
        if path == "/mso/freeze":
            self._handle_mso_freeze(remote)
            return

        # S-HUMAN-CONFIRM-01: record human confirmation signal for a prepared action
        if path == "/mso/prepared-actions/confirm":
            self._handle_mso_prepared_actions_confirm_post()
            return

        # S-MSO-POLICY-01: evaluate MSO capability policy for a confirmed prepared action
        if path == "/mso/prepared-actions/policy-review":
            self._handle_mso_prepared_actions_policy_review_post()
            return

        # S-MSO-AUTHORITY-01: create MSOAuthorityBindingDraft for an approved policy review
        if path == "/mso/prepared-actions/authority-binding":
            self._handle_mso_prepared_actions_authority_binding_post()
            return

        # Route: /machine_operator/execute (execute a bounded browser capability)
        if path == "/machine_operator/execute":
            self._handle_machine_operator_execute(remote)
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
        """Handle GET requests (health, chat, operability, sheets status)."""
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

        # The legacy HTML UI (/ and /chat) was retired when the Next.js UI
        # in ui/ became the primary interface.  Return 410 Gone so callers
        # get a clear signal instead of a silent 404.
        if path == "/" or path == "/chat":
            status, error = _make_json_error(
                410,
                "The built-in HTML UI has been retired. "
                "Use the Next.js UI in ui/ (npm run dev) instead.",
                "Gone",
            )
            self._send_json_response(status, error)
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

        if path == "/agents/registry":
            self._handle_agents_registry_get()
            return

        if path == "/system/capabilities":
            self._handle_system_capabilities_get()
            return

        if path == "/mso/state":
            self._handle_mso_state_get()
            return

        if path == "/mso/governance/recent":
            self._handle_mso_governance_recent_get()
            return

        if path == "/mso/governance/status":
            self._handle_mso_governance_status_get()
            return

        if path == "/mso/authority/status":
            self._handle_mso_authority_status_get()
            return

        if path == "/mso/outcome/status":
            self._handle_mso_outcome_status_get()
            return

        if path == "/system-assistant/state":
            self._handle_system_assistant_state_get()
            return

        # M29: Cognition presence endpoints (feature-flagged)
        if path == "/cognition/providers":
            self._handle_cognition_providers_get()
            return

        if path == "/cognition/providers/health":
            self._handle_cognition_providers_health_get()
            return

        if path == "/cognition/preferences":
            self._handle_cognition_preferences_get()
            return

        # S-CODE-READINESS-01B: read-only CODE readiness surface
        if path == "/code/readiness":
            self._handle_code_readiness_get()
            return

        # S-CONFIRM-FLOW-01B: read-only confirm flow queue observability
        if path == "/confirm/pending":
            self._handle_confirm_pending_get()
            return

        # S-PREPARED-ACTIONS-01: read-only prepared action review queue
        if path == "/mso/prepared-actions/pending":
            self._handle_mso_prepared_actions_pending_get()
            return

        # S-MSO-SEAT-PROVIDER-01: read-only MSO Seat provider metadata
        if path == "/mso/seat/provider":
            self._handle_mso_seat_provider_get()
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
        body = result[0]
        if body:
            data, json_err = _safe_parse_json(body)
            if json_err is not None:
                status, error = json_err
                self._send_json_response(status, error)
                return
        else:
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
        body = result[0]
        if body:
            data, json_err = _safe_parse_json(body)
            if json_err is not None:
                status, error = json_err
                self._send_json_response(status, error)
                return
        else:
            data = {}
        if not isinstance(data, dict):
            data = {}
        kwargs = {}
        if "title"      in data: kwargs["title"]      = str(data["title"])
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

    def _handle_agents_registry_get(self) -> None:
        """GET /agents/registry — expose the canonical backend agent registry."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        self._send_json_response(200, build_agents_registry_response())

    def _handle_system_capabilities_get(self) -> None:
        """GET /system/capabilities — expose backend capability and feature state."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        self._send_json_response(200, build_system_capabilities_response())

    def _handle_mso_state_get(self) -> None:
        """GET /mso/state — expose the current observable MSO/system state."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        self._send_json_response(200, build_mso_state_response())

    def _handle_mso_governance_recent_get(self) -> None:
        """GET /mso/governance/recent — recent in-memory governance decisions (ephemeral)."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        params = self._parse_query_params()
        try:
            limit = int(params.get("limit", "20"))
        except ValueError:
            limit = 20
        if limit < 1:
            limit = 1
        if limit > 50:
            limit = 50
        try:
            decisions = get_recent_governance(limit=limit)

            def _pick(obj: object, *keys: str) -> dict:
                # nested fields may be typed dataclass objects OR plain dicts
                # (the latter happens when GovernanceDecision is reconstructed via asdict())
                if isinstance(obj, dict):
                    return {k: obj.get(k, "") for k in keys}
                return {k: getattr(obj, k, "") for k in keys}

            serialized = [
                {
                    "governance_ref": d.governance_ref,
                    "created_at": d.created_at,
                    "action": d.action,
                    "target_domain": d.target_domain,
                    "target_action": d.target_action,
                    "risk_level": d.risk_level,
                    "operational_mode": d.operational_mode,
                    "effective_execution_mode": d.effective_execution_mode,
                    "justification": d.justification,
                    "reasons": [_pick(r, "code", "detail") for r in d.reasons],
                    "constraints": [_pick(c, "kind", "value") for c in d.constraints],
                    "interventions": [_pick(i, "kind", "value", "reason") for i in d.interventions],
                }
                for d in decisions
            ]
            self._send_json_response(200, {
                "ok": True,
                "source": "mso_governance",
                "decisions": serialized,
                "count": len(serialized),
                "limit": limit,
                "ephemeral": True,
            })
        except Exception:
            self._send_json_response(200, {
                "ok": False,
                "source": "mso_governance",
                "error": "governance state unavailable",
                "decisions": [],
                "count": 0,
                "limit": limit,
                "ephemeral": True,
            })

    def _handle_mso_governance_status_get(self) -> None:
        """GET /mso/governance/status — read-only operational mode and key governance counts (ephemeral)."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        try:
            summary = get_governance_summary()
            mode, reason, source = get_operational_mode()
            self._send_json_response(200, {
                "ok": True,
                "source": "mso_governance",
                "operational_mode": mode,
                "operational_mode_reason": reason,
                "operational_mode_source": source,
                "hardened_domains": summary.hardened_domains,
                "hardened_domain_count": len(summary.hardened_domains),
                "active_revocation_count": summary.active_revocation_count,
                "active_grant_count": summary.active_grant_count,
                "recent_anomaly_count": summary.recent_anomaly_count,
                "ephemeral": True,
            })
        except Exception:
            self._send_json_response(200, {
                "ok": False,
                "source": "mso_governance",
                "error": "governance status unavailable",
                "ephemeral": True,
            })

    def _handle_mso_authority_status_get(self) -> None:
        """GET /mso/authority/status — read-only authority posture matrix summary."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        try:
            from .mso.authority_status import get_authority_status
            summary = get_authority_status()
            self._send_json_response(
                200,
                {
                    "ok": True,
                    "source": "authority_status",
                    **summary,
                },
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft read-only surface
            self._send_json_response(
                200,
                {
                    "ok": False,
                    "source": "authority_status",
                    "capabilities": [],
                    "counts": {
                        "total": 0,
                        "allow": 0,
                        "confirm_only": 0,
                        "deny": 0,
                        "blocked": 0,
                        "active_grants": 0,
                        "active_revocations": 0,
                    },
                    "error": str(exc),
                    "note": "Authority status unavailable; this does not grant execution permission.",
                },
            )

    def _handle_mso_outcome_status_get(self) -> None:
        """GET /mso/outcome/status — read-only execution outcome observability."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        note = "Outcome status is observational; it does not grant execution permission."
        params = self._parse_query_params()
        try:
            from .mso.outcome_status import build_outcome_status

            summary = build_outcome_status(
                plan_id=params.get("plan_id"),
                context_id=params.get("context_id"),
                trace_id=params.get("trace_id"),
                execution_id=params.get("execution_id"),
            )
            self._send_json_response(
                200,
                {
                    **summary,
                    "source": "outcome_status",
                    "note": note,
                },
            )
        except Exception:  # noqa: BLE001 — fail-soft read-only surface
            self._send_json_response(
                200,
                {
                    "ok": False,
                    "source": "outcome_status",
                    "note": note,
                    "error": "outcome_status_unavailable",
                },
            )

    def _handle_system_assistant_state_get(self) -> None:
        """GET /system-assistant/state — read-only observer + interpretation payload."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        try:
            snapshot = observe_system()
            interpretation = interpret_system_snapshot(snapshot)
            self._send_json_response(
                200,
                {
                    "ok": True,
                    "snapshot": snapshot,
                    "interpretation": interpretation,
                },
            )
            return
        except Exception:
            snapshot = {
                "status": "unavailable",
                "warnings": ["system assistant state unavailable"],
            }
            interpretation = interpret_system_snapshot(snapshot)
            self._send_json_response(
                200,
                {
                    "ok": True,
                    "snapshot": snapshot,
                    "interpretation": interpretation,
                },
            )

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
        
        # A1.5: All text routes through the canonical orchestrator path regardless
        # of prefix.  The NL classifier handles prefix text uniformly; no separate
        # mini-policy path exists.  Policy (S10), token (S12), and grant (S13)
        # enforcement are applied by handle_request() for every request.
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
        
        # A1.5: All text routes through the canonical orchestrator path regardless
        # of prefix.  The NL classifier handles prefix text uniformly; no separate
        # mini-policy path exists.  Policy (S10), token (S12), and grant (S13)
        # enforcement are applied by handle_request() for every request.
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
        response = _adapt_result_to_response(result, req["context_id"])

        # M30: Lift cognitive_trace from DomainResult data to the top-level
        # HTTP response when ASSISTANT_LOCAL_LLM_ENABLED is set.
        # This exposes real LLM participation metadata to callers without
        # changing existing output contracts (it's an additive field).
        from .config import ASSISTANT_LOCAL_LLM_ENABLED
        if ASSISTANT_LOCAL_LLM_ENABLED:
            ct = (result.get("data") or {}).get("cognitive_trace")
            if ct:
                response["cognitive_trace"] = ct

        return response
    
    def _execute_work_query_from_plan(self, plan: Plan, context_id: str) -> Response:
        """
        A1-FIX: Dead code — never called from any reachable path.

        Raises RuntimeError unconditionally to prevent accidental reactivation.
        This method previously called the work pipeline directly without any
        policy, token, or grant enforcement.  Any future implementation MUST
        route through handle_request() instead.
        """
        raise RuntimeError(
            "_execute_work_query_from_plan is an unreachable unsafe execution path "
            "(A1-FIX: direct pipeline call without policy enforcement). "
            "Route through handle_request() instead."
        )

    def _execute_work_update_preview(self, plan: Plan, context_id: str, text: str) -> Response:
        """
        A1-FIX: Dead code — never called from any reachable path.

        Raises RuntimeError unconditionally to prevent accidental reactivation.
        This method previously called the work pipeline directly without any
        policy, token, or grant enforcement.  Any future implementation MUST
        route through handle_request() instead.
        """
        raise RuntimeError(
            "_execute_work_update_preview is an unreachable unsafe execution path "
            "(A1-FIX: direct pipeline call without policy enforcement). "
            "Route through handle_request() instead."
        )

    def _execute_confirmed_plan(self, context_id: str, remote: str) -> Response:
        """
        Execute a previously stored plan after user confirmation.

        A1-FIX: Routes through handle_request() to enforce the full S10/S12/S13
        policy chain before any domain pipeline executes:
          evaluate_policy (S10/S13) → issue_token (S12) → verify+consume token →
          orchestrator._execute_confirmed_plan → domain pipeline.

        The orchestrator detects metadata["confirm_plan_id"] and dispatches to its
        internal _execute_confirmed_plan(plan_id, context_id) function, which
        retrieves the stored plan and calls the registered domain pipeline.

        Single-use guarantee: the orchestrator removes the pending plan from the
        context store BEFORE calling the pipeline (replay protection). The
        remove_pending_plan() call below is a harmless no-op when the orchestrator
        has already consumed the entry.

        Args:
            context_id: The context ID of the stored plan (plan_id for lookup)
            remote: Remote address for logging

        Returns:
            Response with execution result
        """
        # Quick existence check: surface a clean error before building a request
        # when the plan has already been consumed or has expired.
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
                    "message": (
                        f"No pending plan found for context_id={context_id}. "
                        "It may have expired or already been executed."
                    ),
                },
                "ts": now_iso(),
            }

        # A1-FIX: Route through handle_request so that evaluate_policy (S10/S13),
        # token issuance (S12), and grant enforcement (S13) all fire before
        # the domain pipeline executes.
        #
        # A fresh context_id is generated for this execution request so the
        # orchestrator can track it independently.  The original context_id is
        # passed as confirm_plan_id so the orchestrator's _execute_confirmed_plan
        # can look up and remove the stored plan.
        from .core.orchestrator import handle_request as _handle_request
        from .contracts import normalize_request as _normalize_request, new_context_id as _new_ctx_id

        execution_req = _normalize_request(
            text="",
            context_id=_new_ctx_id(),
            metadata={"confirm_plan_id": context_id},
        )
        domain_result = _handle_request(execution_req)
        result = _adapt_result_to_response(domain_result, execution_req["context_id"])

        # Orchestrator already removed the plan; this is a no-op safety net.
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

    # A2-FIX: _execute_work_create, _execute_work_delete, _execute_work_update_bulk,
    # and _execute_work_update were callable bypass methods that invoked work_pipeline
    # functions directly — no handle_request, no evaluate_policy, no issue_token,
    # no verify_token, no consume_token.  They are neutered here matching the
    # A1-FIX pattern for _execute_work_query_from_plan and _execute_work_update_preview.
    #
    # All WORK execution now routes through:
    #   handle_request() → evaluate_policy (S10) → issue_token (S12) → verify_token
    #   → consume_token → work_pipeline._work_{create,delete,update,update_bulk}_execute()
    #
    # These method stubs are preserved to keep the class surface stable and to make
    # accidental re-wiring fail loudly rather than silently bypass policy.

    def _execute_work_create(self, plan: Plan, context_id: str, test_mode: bool = False) -> Response:
        """A2-FIX: Neutered — unreachable unsafe execution path removed in A2-FIX."""
        raise RuntimeError(
            "_execute_work_create is an unreachable unsafe execution path "
            "removed in A2-FIX. All WORK_CREATE execution must route through "
            "handle_request() to enforce policy (S10), token issuance (S12), "
            "and token verification before the pipeline executes."
        )

    def _execute_work_delete(
        self,
        plan: Plan,
        context_id: str,
        test_mode: bool = False,
        reset_all: bool = False,
    ) -> Response:
        """A2-FIX: Neutered — unreachable unsafe execution path removed in A2-FIX."""
        raise RuntimeError(
            "_execute_work_delete is an unreachable unsafe execution path "
            "removed in A2-FIX. All WORK_DELETE execution must route through "
            "handle_request() to enforce policy (S10), token issuance (S12), "
            "and token verification before the pipeline executes."
        )

    def _execute_work_update_bulk(self, plan: dict, context_id: str) -> dict:
        """A2-FIX: Neutered — unreachable unsafe execution path removed in A2-FIX."""
        raise RuntimeError(
            "_execute_work_update_bulk is an unreachable unsafe execution path "
            "removed in A2-FIX. All WORK_UPDATE_BULK execution must route through "
            "handle_request() to enforce policy (S10), token issuance (S12), "
            "and token verification before the pipeline executes."
        )

    def _execute_work_update(self, plan: Plan, context_id: str) -> Response:
        """A2-FIX: Neutered — unreachable unsafe execution path removed in A2-FIX."""
        raise RuntimeError(
            "_execute_work_update is an unreachable unsafe execution path "
            "removed in A2-FIX. All WORK_UPDATE execution must route through "
            "handle_request() to enforce policy (S10), token issuance (S12), "
            "and token verification before the pipeline executes."
        )

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
                "surface":          str   — optional UI surface label for audit/trace context
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

        # Extract context_id and any pending confirmation from session.
        # pending_confirm_plan_id bridges the orchestrator's plan_id across turns.
        _context_id: str = session_data.get("context_id") or new_context_id()
        _pending_confirm_plan_id: "str | None" = session_data.get("pending_confirm_plan_id")

        # Get optional conversation_id for logging
        conversation_id = data.get("conversation_id", "")
        surface = data.get("surface", "")
        if not isinstance(surface, str):
            surface = ""
        surface = surface.strip()

        # Build canonical metadata for the kernel request:
        #   - action carries the structured action (M12) into the orchestrator's structured path
        #   - confirm_plan_id routes an existing pending plan to the confirmation path
        #   - surface is descriptive UI context only; it never changes policy or execution
        _meta: dict = {}
        if action_raw is not None:
            _meta["action"] = action_raw
        if _pending_confirm_plan_id:
            _meta["confirm_plan_id"] = _pending_confirm_plan_id
        if surface:
            _meta["surface"] = surface

        # --- Route ALL input through the canonical kernel (MSO) ---
        incoming_action = action_raw.get("type") if isinstance(action_raw, dict) else None
        _log.info(
            "chat_recv: action=%s pending_confirm=%s context_id=%s text=%r",
            incoming_action or "None",
            _pending_confirm_plan_id or "None",
            _context_id[:8],
            text[:40],
        )

        # F3: Build RequestIdentity and run the centralized guard in one call.
        # build_guarded_request is the single canonical path:
        #   anonymous_human → normalize_request → identity_guard (once) → guard_decision stamped
        # The returned (req, guard_result) pair is the authoritative source.
        # Downstream must NOT call identity_guard() independently.
        from .identity import anonymous_human
        from .identity_guard import build_guarded_request, enforce_guard_for_handler
        request_identity = anonymous_human(session_id=session_id)
        req, guard_result = build_guarded_request(
            request_identity,
            text=text,
            context_id=_context_id,
            metadata=_meta if _meta else None,
        )

        _log.debug(
            "guard: principal=%s state=%s decision=%s",
            request_identity.principal.id,
            request_identity.subject_state.value,
            req["guard_decision"],
        )

        # F3: Enforcement reads guard_decision FROM CanonicalRequest — not recomputed.
        # DENY → HTTP 403 immediately; no domain logic executes.
        guard_error = enforce_guard_for_handler(
            req, action=None,
            principal_id=request_identity.principal.id,
        )
        if guard_error and guard_error[0] == "access_denied":
            self._send_json_response(403, {
                "ok": False,
                "error": "access_denied",
                "reason": guard_result.reason,
                "subject_state": guard_result.subject_state,
                "identity": request_identity.to_audit_dict(),
                "guard": guard_result.to_audit_dict(),
            })
            return

        if (
            surface == "assistant_chat"
            and not _pending_confirm_plan_id
            and isinstance(session_data.get("context_request"), dict)
        ):
            from .cognition.context_resolver import resolve_context_request
            from .surface_behavior import _build_surface_response as _build_context_surface_response

            _resolution = resolve_context_request(
                session_data["context_request"],
                text,
                context_id=_context_id,
            )
            _resolution_status = _resolution.get("status")
            _resolved_context = _resolution.get("context_request")

            if _resolution_status == "cancelled":
                _context_resp = _build_context_surface_response(
                    message="Contexto cancelado. Puedes iniciar una solicitud nueva.",
                    domain="ASSISTANT",
                    surface=surface,
                    context_id=_context_id,
                    identity=request_identity,
                    guard_result=guard_result,
                    result_type="surface_response",
                    intent="context_cancelled",
                    missing_fields=[],
                )
                self._send_json_response(200, _context_resp)
                return

            if _resolution_status != "expired" and isinstance(_resolved_context, dict):
                _missing = list(_resolved_context.get("missing_fields") or [])
                _complete = _resolution_status == "complete"
                _message = (
                    "Contexto completo. No ejecuto nada todavia; envia la solicitud final para continuar."
                    if _complete
                    else str(_resolved_context.get("prompted_question") or "Necesito un poco mas de contexto.")
                )
                _context_resp = _build_context_surface_response(
                    message=_message,
                    domain=str(_resolved_context.get("domain") or "UNKNOWN"),
                    surface=surface,
                    context_id=_context_id,
                    identity=request_identity,
                    guard_result=guard_result,
                    result_type="clarification",
                    intent="needs_context",
                    missing_fields=_missing,
                    context_request=_resolved_context,
                )
                if _complete:
                    _context_resp["session"].pop("context_request", None)
                self._send_json_response(200, _context_resp)
                return

        # Surface behavior layer: short-circuit pure conversational inputs.
        # Runs AFTER identity guard (security must pass) but BEFORE the governance
        # gate and orchestrator dispatch. Conversational responses carry no execution,
        # so they bypass governance intentionally — small talk must not be blocked.
        from .surface_behavior import (
            get_assistant_chat_routing_context as _get_assistant_chat_routing_context,
            get_surface_behavior_response as _get_surf_resp,
        )
        _surface_resp = _get_surf_resp(
            surface=surface,
            text=text,
            context_id=_context_id,
            identity=request_identity,
            guard_result=guard_result,
            session_id=session_id,
        )
        if _surface_resp is not None:
            self._send_json_response(200, _surface_resp)
            if conversation_id:
                _log_chat_message(
                    remote=remote,
                    conversation_id=conversation_id,
                    text=text,
                    context_id=_context_id,
                    surface=surface,
                )
            if session_id:
                import uuid as _uuid_surf
                try:
                    chat_db.append_message(session_id, "user", {
                        "id":        str(_uuid_surf.uuid4()),
                        "role":      "user",
                        "content":   text,
                        "status":    "sent",
                        "createdAt": now_iso(),
                    })
                    chat_db.append_message(session_id, "assistant", {
                        "id":        str(_uuid_surf.uuid4()),
                        "role":      "assistant",
                        "content":   _surface_resp["message"],
                        "status":    "sent",
                        "createdAt": now_iso(),
                        "uiActions": [],
                        "plan":      [],
                        "meta": {
                            "domain":            _surface_resp["domain"],
                            "intent":            _surface_resp["intent"],
                            "mode":              "chat",
                            "traceId":           _context_id,
                            "needsConfirmation": False,
                        },
                        "kind":    "normal",
                        "handled": False,
                    })
                    chat_db.update_session(session_id, context_id=_context_id)
                except Exception as _surf_persist_exc:
                    _log.warning(
                        "[surface_behavior] session persist failed %s: %s",
                        session_id, _surf_persist_exc,
                    )
            return

        _routing_context = _get_assistant_chat_routing_context(
            surface=surface,
            text=text,
            context_id=_context_id,
        )
        if _routing_context is not None:
            req_metadata = req.get("metadata")
            if not isinstance(req_metadata, dict):
                req_metadata = {}
            req_metadata = dict(req_metadata)
            # Non-authoritative handoff only. Do not set metadata["action"].
            req_metadata["routing_context"] = _routing_context
            req["metadata"] = req_metadata

        # ALFA governance gate — checked before ANY kernel dispatch.
        #
        # FROZEN  → absolute block; operator must explicitly clear the freeze.
        # DEGRADED → block chat mutations; canonical paths require confirmation already.
        #
        # Fail-closed: if the governance snapshot itself fails, block the request.
        try:
            from .mso.system_state import build_system_state_snapshot as _chat_snap
            _chat_mode = _chat_snap().operational_mode
            if _chat_mode in ("FROZEN", "DEGRADED"):
                _log.warning(
                    "chat_process: governance gate blocked request operational_mode=%s",
                    _chat_mode,
                )
                self._send_json_response(503, {
                    "ok": False,
                    "error": "governance_blocked",
                    "execution_status": "unavailable",
                    "operational_mode": _chat_mode,
                    "reason": (
                        "System is FROZEN. All chat execution blocked until operator clears the freeze."
                        if _chat_mode == "FROZEN"
                        else "System is DEGRADED. Chat mutations are blocked. Use the canonical API endpoints."
                    ),
                })
                return
        except Exception as _chat_gov_exc:
            _log.error("chat_process: governance snapshot failed, blocking request: %s", _chat_gov_exc)
            self._send_json_response(503, {
                "ok": False,
                "error": "governance_check_failed",
                "execution_status": "unavailable",
                "reason": "Governance check failed. Request blocked for safety.",
            })
            return

        # Canonical kernel dispatch — single authority path through MSO.
        # req is a fully-stamped CanonicalRequest (guard_decision, action_type,
        # principal_id, context_id, metadata with action/confirm_plan_id).
        # No classification, no routing, no domain logic runs here.
        from .core.orchestrator import handle_request
        domain_result = handle_request(req)
        request_metadata = req.get("metadata") or {}
        request_surface = ""
        if isinstance(request_metadata, dict):
            request_surface = str(request_metadata.get("surface", "")).strip()
        response_data = _chat_wire_from_domain_result(
            domain_result,
            context_id=req["context_id"],
            action_raw=action_raw,
            identity=request_identity,
            guard_result=guard_result,
            surface=request_surface,
        )
        if isinstance(request_metadata, dict) and isinstance(request_metadata.get("routing_context"), dict):
            audit = dict(response_data.get("audit") or {})
            audit["routing_context"] = {
                "source": request_metadata["routing_context"].get("source"),
                "authoritative": request_metadata["routing_context"].get("authoritative"),
                "intent_type": request_metadata["routing_context"].get("intent_type"),
                "domain": request_metadata["routing_context"].get("domain"),
                "action": request_metadata["routing_context"].get("action"),
                "router_version": request_metadata["routing_context"].get("router_version"),
                "context_id": request_metadata["routing_context"].get("context_id"),
            }
            response_data["audit"] = audit

        ui_action_types = [a.get("type", "") for a in response_data.get("ui_actions", [])]
        _log.info(
            "chat_resp: trace=%s  intent=%s/%s  mode=%s  execution_mode=%s  ui_actions=%s",
            response_data.get("trace_id", "N/A")[:8],
            response_data["domain"], response_data["intent"],
            response_data["mode"],
            (response_data.get("audit") or {}).get("execution_mode", ""),
            ui_action_types,
        )

        # Log chat message
        if conversation_id:
            _log_chat_message(
                remote=remote,
                conversation_id=conversation_id,
                text=text,
                context_id=response_data["session"].get("context_id", ""),
                surface=request_surface,
            )

        # M29: Attach cognitive_trace when the feature is enabled.
        # The chat path is deterministic — handle_request does not invoke a local LLM
        # for NL routing. cognitive_trace.used = False is the truthful value.
        from .config import ASSISTANT_LOCAL_LLM_ENABLED
        if ASSISTANT_LOCAL_LLM_ENABLED:
            response_data["cognitive_trace"] = {
                "used": False,
                "provider": None,
                "task_type": None,
                "validation": None,
                "confidence": None,
                "fallback_used": False,
                "path": "deterministic",
            }

        # M17: persist messages + update context_id if session_id was provided
        if session_id:
            import uuid as _uuid2
            user_content = text or (
                f"[{action_raw.get('type', 'action')}]"
                if isinstance(action_raw, dict) else "[action]"
            )
            new_ctx = response_data["session"].get("context_id")
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
                    "content":   response_data["message"],
                    "status":    "sent",
                    "createdAt": now_iso(),
                    "uiActions": response_data.get("ui_actions") or [],
                    "plan":      response_data.get("plan") or [],
                    "meta": {
                        "domain":            response_data["domain"],
                        "intent":            response_data["intent"],
                        "mode":              response_data["mode"],
                        "traceId":           response_data.get("trace_id", ""),
                        "needsConfirmation": response_data.get("needs_confirmation", False),
                    },
                    "kind":    "confirmation_request" if response_data.get("needs_confirmation") else "normal",
                    "handled": False,
                })
                if new_ctx:
                    chat_db.update_session(session_id, context_id=new_ctx)
            except Exception as _m17_exc:
                _log.warning("[M17] persist failed for session %s: %s", session_id, _m17_exc)

        self._send_json_response(200, response_data)
    
    def _handle_fin_plan(self, remote: str) -> None:
        """Handle POST /fin/plan - Plan Always entry point for FIN domain.

        Sprint 2 canonical entry: normalize_request → handle_request → DomainResult.
        Reads text, optional session_context. Does NOT write to Sheets.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        body = result[0]

        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            self._send_json_response(status, error)
            return

        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return

        text = data.get("text", "")
        if not isinstance(text, str) or not text.strip():
            status, error = _make_json_error(400, 'Missing required field: "text"', "BadRequest")
            self._send_json_response(status, error)
            return

        session_id = data.get("session_id", "")
        session_context = data.get("session_context", {})

        from .contracts import normalize_request, ACTION_FIN_PLAN, RISK_LOW
        from .core.orchestrator import handle_request as _handle_request

        req = normalize_request(
            text=text,
            filters={"session_context": session_context},
            metadata={
                "action": ACTION_FIN_PLAN,
                "domain": "FIN",
                "risk_level": RISK_LOW,
                "requires_confirmation": False,
            },
        )
        dr = _handle_request(req)

        _log_fin_expense_event(
            remote=remote,
            ok=dr["ok"],
            action="plan",
            session_id=session_id,
            text_preview=text[:100],
        )

        plan_data = dr.get("data", {})
        self._send_json_response(200, {
            "ok": dr["ok"],
            "kind": plan_data.get("kind", "fin_plan"),
            "total_items": plan_data.get("total_items", 0),
            "message": plan_data.get("message", dr.get("message", "")),
            "items": plan_data.get("items", []),
            "needs_clarification": plan_data.get("needs_clarification", False),
            "clarification_prompt": plan_data.get("clarification_prompt", ""),
            "session_context": plan_data.get("session_context", {}),
            "execution_id": dr.get("plan_id"),
        })
    
    def _handle_fin_commit(self, remote: str) -> None:
        """Handle POST /fin/commit - commit single expense from confirmed plan.

        Sprint 2 canonical entry: normalize_request → handle_request → DomainResult.
        Canonicalization (dropdown normalization) is delegated to the pipeline.
        """
        try:
            auth_error = self._check_auth()
            if auth_error:
                status, error = auth_error
                self._send_json_response(status, error)
                return

            result = self._read_body()
            if result[1] is not None:
                status, error = result[1]
                self._send_json_response(status, error)
                return
            body = result[0]

            try:
                data = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
                self._send_json_response(status, error)
                return

            if not isinstance(data, dict):
                status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
                self._send_json_response(status, error)
                return

            expense_data = data.get("expense")
            if not isinstance(expense_data, dict):
                status, error = _make_json_error(400, 'Missing required field: "expense"', "BadRequest")
                self._send_json_response(status, error)
                return

            session_id = data.get("session_id", "")

            if not check_sheets_available():
                self._send_json_response(503, {
                    "ok": False,
                    "stored": False,
                    "row_number": None,
                    "sheet": SHEETS_TAB_NAME,
                    "message": "Google Sheets integration not available",
                    "error": "sheets_unavailable",
                })
                return

            from .contracts import normalize_request, ACTION_FIN_COMMIT, RISK_MEDIUM
            from .core.orchestrator import handle_request as _handle_request

            req = normalize_request(
                text="",
                filters={"expense": expense_data, "session_id": session_id},
                metadata={
                    "action": ACTION_FIN_COMMIT,
                    "domain": "FIN",
                    "risk_level": RISK_MEDIUM,
                    "requires_confirmation": False,
                },
            )
            dr = _handle_request(req)

            commit_data = dr.get("data", {})
            if dr["ok"]:
                row_number = commit_data.get("row_number")
                expense_out = commit_data.get("expense", expense_data)
                _log_fin_expense_event(
                    remote=remote,
                    ok=True,
                    action="commit",
                    monto=expense_out.get("monto", 0),
                    moneda=expense_out.get("moneda", ""),
                    responsable=expense_out.get("responsable", ""),
                    session_id=session_id,
                )
                self._send_json_response(200, {
                    "ok": True,
                    "stored": True,
                    "row_number": row_number,
                    "sheet": SHEETS_TAB_NAME,
                    "message": dr.get("message", f"Gasto guardado en fila {row_number}"),
                    "error": None,
                    "execution_id": dr.get("plan_id"),
                })
            else:
                err_msg = dr.get("error", {}).get("message", "Error") if dr.get("error") else "Error"
                _log_fin_expense_event(
                    remote=remote,
                    ok=False,
                    action="commit_error",
                    error_message=err_msg,
                    session_id=session_id,
                )
                self._send_json_response(500, {
                    "ok": False,
                    "stored": False,
                    "row_number": None,
                    "sheet": SHEETS_TAB_NAME,
                    "message": f"Error al guardar: {err_msg}",
                    "error": err_msg,
                    "execution_id": dr.get("plan_id"),
                })

        except Exception as e:
            import traceback
            traceback.print_exc()
            status, error = _make_json_error(500, f"Internal error: {e}", "InternalError")
            self._send_json_response(status, error)

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
        """Handle POST /fin/expense — parse expense and auto-store if complete.

        Sprint 2 canonical entry
        ------------------------
        Parse step routes through orchestrator structured path:
            normalize_request() → handle_request() → DomainResult

        Auto-store (AppendExpenseRowTool) remains a transport-layer concern:
        it is a conditional side effect applied to the parse DomainResult when
        no missing fields and no confirmation is needed.
        """
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
        safe_override = override if isinstance(override, dict) else {}
        safe_session_id = session_id if isinstance(session_id, str) else ""

        # ── Canonical entry (parse + auto-store) ────────────────────────
        from .contracts import normalize_request, ACTION_FIN_EXPENSE, RISK_MEDIUM
        from .core.orchestrator import handle_request as _handle_request

        req = normalize_request(
            text=text,
            filters={"override": safe_override, "session_id": safe_session_id},
            metadata={
                "action": ACTION_FIN_EXPENSE,
                "domain": "FIN",
                "risk_level": RISK_MEDIUM,
                "requires_confirmation": False,
                "target": "expense parse",
            },
        )
        dr = _handle_request(req)
        execution_id = dr.get("plan_id")
        # ── End canonical entry ──────────────────────────────────────────

        parse_data = dr.get("data", {})
        exp = parse_data.get("expense")
        stored = parse_data.get("stored", False)
        needs_confirmation = parse_data.get("needs_confirmation", False)
        missing_fields = parse_data.get("missing_fields", [])
        ambiguous_responsables = parse_data.get("ambiguous_responsables", [])
        sheets_available = parse_data.get("sheets_available", False)
        sheets_error = parse_data.get("sheets_error")
        row_number = parse_data.get("row_number")

        # Sheets write error (parse succeeded but store failed)
        if not dr["ok"] and exp is not None:
            err_msg = dr.get("message", "Error guardando en Sheets")
            error_type = (dr.get("error") or {}).get("type", "unknown_error")
            _log_fin_expense_event(
                remote=remote,
                ok=False,
                action="sheets_error",
                error_message=err_msg,
                session_id=safe_session_id,
                text_preview=text,
            )
            self._send_json_response(500, {
                "ok": False,
                "stored": False,
                "status": "error",
                "needs_confirmation": False,
                "message": err_msg,
                "error_type": error_type,
                "expense": exp,
                "sheets_available": True,
                "sheets_error": sheets_error,
                "row_number": None,
                "tab_name": SHEETS_TAB_NAME,
                "execution_id": execution_id,
            })
            return

        # Parse failed
        if not dr["ok"]:
            _log_fin_expense_event(
                remote=remote,
                ok=False,
                action="parse",
                error_message=dr.get("message", "Parse failed"),
                session_id=safe_session_id,
                text_preview=text,
            )
            self._send_json_response(400, {
                "ok": False,
                "stored": False,
                "status": "error",
                "message": dr.get("message", "No se pudo parsear el gasto"),
                "expense": None,
                "missing_fields": missing_fields,
                "sheets_available": sheets_available,
                "needs_confirmation": False,
                "row_number": None,
                "tab_name": SHEETS_TAB_NAME,
                "execution_id": execution_id,
            })
            return

        # Needs confirmation — return parsed data without storing
        if needs_confirmation:
            _log_fin_expense_event(
                remote=remote,
                ok=True,
                action="parse",
                monto=(exp.get("monto") or 0.0) if exp else 0.0,
                moneda=exp.get("moneda", "") if exp else "",
                categoria=exp.get("categoria", "") if exp else "",
                responsable=exp.get("responsable", "") if exp else "",
                needs_confirmation=True,
                session_id=safe_session_id,
                text_preview=text,
            )
            self._send_json_response(200, {
                "ok": True,
                "stored": False,
                "status": "needs_confirmation",
                "needs_confirmation": True,
                "missing_fields": missing_fields,
                "ambiguous_responsables": ambiguous_responsables,
                "message": dr.get("message", ""),
                "expense": exp,
                "sheets_available": sheets_available,
                "row_number": None,
                "tab_name": SHEETS_TAB_NAME,
                "execution_id": execution_id,
            })
            return

        # Sheets unavailable — expense parsed but not stored
        if not sheets_available:
            last_error = sheets_error
            error_type = last_error.get("type", "unknown_error") if last_error else "unknown_error"
            error_msg = last_error.get("message", "Sheets not configured") if last_error else "Sheets not configured"
            _log_fin_expense_event(
                remote=remote,
                ok=True,
                action="parse",
                monto=(exp.get("monto") or 0.0) if exp else 0.0,
                moneda=exp.get("moneda", "") if exp else "",
                categoria=exp.get("categoria", "") if exp else "",
                responsable=exp.get("responsable", "") if exp else "",
                needs_confirmation=False,
                session_id=safe_session_id,
                text_preview=text,
                error_message=error_msg,
            )
            self._send_json_response(200, {
                "ok": True,
                "stored": False,
                "status": "sheets_unavailable",
                "error_type": error_type,
                "needs_confirmation": False,
                "message": f"Expense parsed but could not store: {error_msg}",
                "expense": exp,
                "sheets_available": False,
                "sheets_error": last_error,
                "row_number": None,
                "tab_name": SHEETS_TAB_NAME,
                "execution_id": execution_id,
            })
            return

        # Successfully stored by pipeline
        _log_fin_expense_event(
            remote=remote,
            ok=True,
            action="stored",
            monto=(exp.get("monto") or 0.0) if exp else 0.0,
            moneda=exp.get("moneda", "") if exp else "",
            categoria=exp.get("categoria", "") if exp else "",
            responsable=exp.get("responsable", "") if exp else "",
            session_id=safe_session_id,
            text_preview=text,
        )
        self._send_json_response(200, {
            "ok": True,
            "stored": True,
            "status": "stored",
            "needs_confirmation": False,
            "row_number": row_number,
            "tab_name": SHEETS_TAB_NAME,
            "message": dr.get("message", f"Guardado en Sheets"),
            "expense": exp,
            "sheets_available": True,
            "execution_id": execution_id,
        })
    
    def _handle_fin_chaperon(self, remote: str) -> None:
        """Handle POST /fin/chaperon - preprocess text to detect multi-expense or continuation.

        Sprint 2 canonical entry: normalize_request → handle_request → DomainResult.
        FIN domain: routes to ACTION_FIN_CHAPERON → fin_pipeline._fin_chaperon_execute.
        WORK domain: routes to ACTION_WORK_QUERY → work_pipeline.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        body = result[0]

        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            self._send_json_response(status, error)
            return

        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return

        text = data.get("text", "")
        if not isinstance(text, str) or not text.strip():
            status, error = _make_json_error(400, 'Missing required field: "text"', "BadRequest")
            self._send_json_response(status, error)
            return

        domain = data.get("domain", "FIN")
        session_data = data.get("session_context", {})

        # Pending flow guard — short-circuit before any routing
        if session_data.get("pending"):
            self._send_json_response(200, {
                "ok": True,
                "type": "pending_flow",
                "items": [],
                "requires_confirmation": False,
                "clarification_questions": [],
                "should_execute": False,
                "confirmation_message": "Tienes un flujo pendiente. Complétalo antes de continuar.",
                "inherited_context": dict(session_data),
                "raw_text": text,
                "detected_domain": domain,
            })
            return

        from .contracts import normalize_request, ACTION_FIN_CHAPERON, ACTION_WORK_QUERY, RISK_LOW
        from .core.orchestrator import handle_request as _handle_request

        if domain == "WORK":
            # Route WORK queries through the canonical WORK_QUERY path
            from .classifier import parse_work_query_filters
            from .config import NOTION_WORK_ACTIVE_STATUSES
            work_filters = parse_work_query_filters(text)
            if "status" not in work_filters:
                work_filters["status"] = NOTION_WORK_ACTIVE_STATUSES

            req = normalize_request(
                text=text,
                filters=dict(work_filters),
                metadata={
                    "action": ACTION_WORK_QUERY,
                    "domain": "WORK",
                    "risk_level": RISK_LOW,
                    "requires_confirmation": False,
                    "target": "work db query",
                },
            )
            dr = _handle_request(req)
            work_data = dr.get("data", {})
            self._send_json_response(200, {
                "ok": dr["ok"],
                "type": "work_query",
                "items": work_data.get("items", []),
                "requires_confirmation": False,
                "clarification_questions": [],
                "should_execute": True,
                "confirmation_message": work_data.get("formatted", ""),
                "inherited_context": {"last_domain": "WORK"},
                "raw_text": text,
                "detected_domain": "WORK",
                "query_filters": work_filters,
                "total": work_data.get("total", 0),
                "execution_id": dr.get("plan_id"),
            })
            return

        # FIN domain: run chaperon via pipeline
        req = normalize_request(
            text=text,
            filters={"domain": domain, "session_context": session_data},
            metadata={
                "action": ACTION_FIN_CHAPERON,
                "domain": "FIN",
                "risk_level": RISK_LOW,
                "requires_confirmation": False,
            },
        )
        dr = _handle_request(req)
        chap_data = dr.get("data", {})
        action_plan = chap_data.get("action_plan", {})

        self._send_json_response(200, {
            "ok": dr["ok"],
            "type": action_plan.get("type", "passthrough"),
            "items": [
                {
                    "monto":       item.get("monto"),
                    "moneda":      item.get("moneda"),
                    "categoria":   item.get("categoria"),
                    "responsable": item.get("responsable"),
                    "descripcion": item.get("descripcion"),
                    "raw_segment": item.get("raw_segment"),
                }
                for item in action_plan.get("items", [])
            ],
            "requires_confirmation": action_plan.get("requires_confirmation", False),
            "clarification_questions": action_plan.get("clarification_questions", []),
            "should_execute": chap_data.get("should_execute", True),
            "confirmation_message": chap_data.get("confirmation_message"),
            "inherited_context": dict(action_plan.get("inherited_context", {})),
            "raw_text": chap_data.get("raw_text", text),
            "detected_domain": chap_data.get("detected_domain", domain),
            "execution_id": dr.get("plan_id"),
        })
    
    def _handle_fin_expense_batch(self, remote: str) -> None:
        """Handle POST /fin/expense/batch - execute multiple expenses from confirmed action_plan.

        Sprint 2 canonical entry: normalize_request → handle_request → DomainResult.
        Batch processing (parse + store per item) is delegated to the pipeline.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        body = result[0]

        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            self._send_json_response(status, error)
            return

        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return

        items = data.get("items", [])
        if not isinstance(items, list) or len(items) == 0:
            status, error = _make_json_error(400, 'Missing required field: "items"', "BadRequest")
            self._send_json_response(status, error)
            return

        from .contracts import normalize_request, ACTION_FIN_BATCH, RISK_MEDIUM
        from .core.orchestrator import handle_request as _handle_request

        req = normalize_request(
            text="",
            filters={"items": items, "session_id": data.get("session_id", "")},
            metadata={
                "action": ACTION_FIN_BATCH,
                "domain": "FIN",
                "risk_level": RISK_MEDIUM,
                "requires_confirmation": False,
            },
        )
        dr = _handle_request(req)
        batch_data = dr.get("data", {})

        self._send_json_response(200, {
            "ok": dr["ok"],
            "total_items": batch_data.get("total_items", len(items)),
            "stored_count": batch_data.get("stored_count", 0),
            "sheets_available": batch_data.get("sheets_available", True),
            "results": batch_data.get("results", []),
            "message": batch_data.get("message", dr.get("message", "")),
            "execution_id": dr.get("plan_id"),
        })

    def _handle_fin_expense_confirm(self, remote: str) -> None:
        """Handle POST /fin/expense/confirm - confirm expense and append to Sheets.

        Sprint 2 canonical entry: normalize_request → handle_request → DomainResult.
        All expense fields passed as flat filters to ACTION_FIN_CONFIRM pipeline.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message="Unauthorized")
            self._send_json_response(status, error)
            return

        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message="Failed to read body")
            self._send_json_response(status, error)
            return
        body = result[0]

        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message=f"Invalid JSON: {e}")
            self._send_json_response(status, error)
            return

        required = ["fecha", "monto", "moneda", "descripcion", "responsable"]
        missing = [f for f in required if f not in data or data[f] is None]
        if missing:
            status, error = _make_json_error(400, f'Missing required fields: {", ".join(missing)}', "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message=f"Missing fields: {missing}")
            self._send_json_response(status, error)
            return

        try:
            monto = float(data["monto"])
        except (ValueError, TypeError):
            status, error = _make_json_error(400, "monto must be a number", "BadRequest")
            _log_fin_expense_event(remote, ok=False, action="confirm", error_message="Invalid monto")
            self._send_json_response(status, error)
            return

        session_id = data.get("session_id", "")

        from .contracts import normalize_request, ACTION_FIN_CONFIRM, RISK_MEDIUM
        from .core.orchestrator import handle_request as _handle_request

        req = normalize_request(
            text="",
            filters={
                "fecha":       data["fecha"],
                "monto":       monto,
                "moneda":      data["moneda"],
                "descripcion": data["descripcion"],
                "responsable": data["responsable"],
                "categoria":   data.get("categoria", "otros"),
                "itbms":       data.get("itbms", False),
                "metodo_pago": data.get("metodo_pago", ""),
                "notas":       data.get("notas", ""),
                "factura":     data.get("factura", ""),
                "session_id":  session_id,
            },
            metadata={
                "action": ACTION_FIN_CONFIRM,
                "domain": "FIN",
                "risk_level": RISK_MEDIUM,
                "requires_confirmation": False,
            },
        )
        dr = _handle_request(req)
        confirm_data = dr.get("data", {})

        _log_fin_expense_event(
            remote=remote,
            ok=dr["ok"],
            action="sheets_append",
            monto=monto,
            moneda=data["moneda"],
            categoria=data.get("categoria", "otros"),
            responsable=data["responsable"],
            session_id=session_id,
            error_message="" if dr["ok"] else (dr.get("error") or {}).get("message", ""),
        )

        if dr["ok"]:
            row_number = confirm_data.get("row_number")
            self._send_json_response(200, {
                "ok": True,
                "message": dr.get("message", f"Guardado en Sheets (fila {row_number})"),
                "row_number": row_number,
                "expense": confirm_data.get("expense", {}),
                "execution_id": dr.get("plan_id"),
            })
        else:
            err_msg = (dr.get("error") or {}).get("message", "SheetsError")
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

    def _handle_mso_freeze(self, remote: str) -> None:
        """POST /mso/freeze — operator freeze or restore the system from the UI.

        Body: { "action": "freeze"|"restore", "source": str, "reason": str }
        Response: { "ok": true, "operational_mode": str, "message": str }

        Auth: shared-secret only (same as all other authenticated endpoints).
        This endpoint is the UI proxy target for ui/app/api/system/freeze/route.ts.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        body = result[0]
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            status, error = _make_json_error(400, f"Invalid JSON: {exc}", "BadRequest")
            self._send_json_response(status, error)
            return
        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return

        action = str(data.get("action", "freeze")).strip().lower()
        source = str(data.get("source", "unknown")).strip()
        reason = str(data.get("reason", f"Operator {action} via UI (source={source})")).strip()

        from .mso.governance_surface import (
            set_operational_mode_override as _set_mode,
            clear_operational_mode as _clear_mode,
            get_operational_mode as _get_mode,
        )
        from .mso.system_state import persist_current_mode as _persist_mode

        if action == "freeze":
            _set_mode("FROZEN", reason=reason)
            _persist_mode()
            _log_webhook_event(
                "/mso/freeze", remote, ok=True,
                event_type="governance_freeze", context_id="FROZEN",
            )
        elif action in ("restore", "unfreeze"):
            _clear_mode()
            _persist_mode()
            _log_webhook_event(
                "/mso/freeze", remote, ok=True,
                event_type="governance_restore", context_id="NORMAL",
            )
        else:
            status, error = _make_json_error(
                400, f"Unknown action '{action}'. Use 'freeze' or 'restore'.", "BadRequest"
            )
            self._send_json_response(status, error)
            return

        current_mode, current_reason, _ = _get_mode()
        message = (
            "System frozen. All execution blocked until operator restores."
            if current_mode == "FROZEN"
            else "System restored. Execution resumed."
        )
        self._send_json_response(200, {
            "ok": True,
            "operational_mode": current_mode,
            "message": message,
            "reason": current_reason,
        })

    def _handle_governance_mode(self, remote: str) -> None:
        """
        ALFA kill-switch: POST /admin/governance/mode

        Set or clear the system-wide operational mode.  This is the operator
        kill-switch that blocks ALL execution across EVERY path (canonical,
        chat, confirm replay) until explicitly cleared.

        Auth: requires shared-secret auth AND X-Assistant-Admin-Token header
        (same two-layer guard as schema endpoints).

        Request body:
            {
                "mode":   "FROZEN" | "DEGRADED" | "RESTRICTED" | "NORMAL",
                "reason": str   — required, explains why the mode was set
            }

        "NORMAL" or omitted mode → clears the override (system returns to
        derived mode from anomaly analysis).

        Response:
            {
                "ok":   true,
                "mode": str,    — mode that was applied
                "cleared": bool — true when override was cleared
            }

        Mode semantics
        --------------
        FROZEN     → absolute kill-switch; ALL execution blocked everywhere.
                     No auto-unfreeze. Operator must POST mode=NORMAL to clear.
        DEGRADED   → all AUTO execution → CONFIRM (canonical path);
                     /chat/process mutations blocked.
        RESTRICTED → AUTO execution with medium/low risk → CONFIRM.
        NORMAL     → clears any override; derived from anomaly analysis.
        """
        # Layer 1: shared-secret auth
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        # Layer 2: admin token — fail-closed.
        # If WEBHOOK_ADMIN_TOKEN is not configured, ALL admin requests are rejected.
        # An empty or absent WEBHOOK_ADMIN_TOKEN is not a "presence-only" mode.
        from .config import WEBHOOK_ADMIN_TOKEN as _ADMIN_TOKEN
        admin_token = self.headers.get("X-Assistant-Admin-Token", "")
        if not _ADMIN_TOKEN or not admin_token or admin_token != _ADMIN_TOKEN:
            status, error = _make_json_error(
                403, "Admin token missing or invalid for governance operations", "Forbidden"
            )
            self._send_json_response(status, error)
            return

        # Read + parse body
        result = self._read_body()
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        body = result[0]
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            status, error = _make_json_error(400, f"Invalid JSON: {exc}", "BadRequest")
            self._send_json_response(status, error)
            return
        if not isinstance(data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return

        mode = str(data.get("mode", "NORMAL")).strip().upper()
        reason = str(data.get("reason", "")).strip()

        _VALID_MODES = {"FROZEN", "DEGRADED", "RESTRICTED", "NORMAL"}
        if mode not in _VALID_MODES:
            status, error = _make_json_error(
                400,
                f"Invalid mode {mode!r}. Must be one of: {', '.join(sorted(_VALID_MODES))}",
                "BadRequest",
            )
            self._send_json_response(status, error)
            return

        if mode != "NORMAL" and not reason:
            status, error = _make_json_error(
                400, "reason is required when setting a non-NORMAL mode", "BadRequest"
            )
            self._send_json_response(status, error)
            return

        from .mso.governance_surface import (
            set_operational_mode_override as _set_mode,
            clear_operational_mode as _clear_mode,
            get_operational_mode as _get_mode,
        )
        from .mso.system_state import persist_current_mode as _persist_mode

        cleared = False
        if mode == "NORMAL":
            _clear_mode()
            _persist_mode()
            cleared = True
            _log_webhook_event(
                "/admin/governance/mode", remote, ok=True,
                event_type="governance_mode_cleared",
            )
        else:
            _set_mode(mode, reason=reason)  # type: ignore[arg-type]
            _persist_mode()
            _log_webhook_event(
                "/admin/governance/mode", remote, ok=True,
                event_type="governance_mode_set",
                context_id=mode,
            )

        current_mode, current_reason, current_source = _get_mode()
        self._send_json_response(200, {
            "ok": True,
            "mode": current_mode,
            "cleared": cleared,
            "reason": current_reason,
            "source": current_source,
        })

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

    def _apply_schema_policy_gate(self) -> "tuple[int, dict] | None":
        """
        A2-FIX: Enforce the full S10/S12/S13 policy + capability-token chain
        for schema admin endpoints.

        Returns None when all checks pass (caller may execute).
        Returns (status_code, error_dict) on any failure (caller must abort).

        Chain enforced:
          evaluate_policy (S10) → issue_token (S12) → verify_token → consume_token

        action_type="schema_write" is a purpose-specific tag that causes the
        policy engine to evaluate the schema mutation against the same guard,
        subject-state, and grant checks that apply to all other write operations.
        The token is single-use: issued, immediately verified, and consumed so
        execution can proceed only once per request with no replay.
        """
        import uuid as _uuid
        from .policy.policy_engine import evaluate_policy as _eval_policy
        from .policy.policy_models import PolicyContext as _PolicyContext
        from .grants.grant_store import get_default_store as _get_grant_store
        from .capabilities.token_models import OperationBinding as _OperationBinding
        from .capabilities.token_issuer import issue_token as _issue_token
        from .capabilities.token_verifier import verify_token as _vt, consume_token as _ct

        context_id = str(_uuid.uuid4())

        # S10: policy gate
        policy_ctx = _PolicyContext(
            subject_state="",
            guard_decision="",
            action_type="schema_write",
            principal_id="",
            operation_key=context_id,
        )
        policy_decision = _eval_policy(policy_ctx, grant_store=_get_grant_store())

        if not policy_decision.permitted:
            status, error = _make_json_error(
                403,
                f"Policy denied schema operation: {policy_decision.detail}",
                policy_decision.error_type,
            )
            return status, error

        # S12: issue + verify + consume (single-use enforcement)
        tok_binding = _OperationBinding(
            principal_id="",
            subject_state="",
            action_type="schema_write",
            capability=None,
            operation_key=context_id,
        )
        cap_token = _issue_token(tok_binding)

        if not _vt(cap_token, tok_binding):
            status, error = _make_json_error(
                500,
                "Schema capability token verification failed — execution blocked.",
                "token_invalid",
            )
            return status, error

        _ct(cap_token)
        return None

    def _handle_work_schema_plan(self, remote: str) -> None:
        """
        Handle POST /work/schema/plan - Plan schema changes (admin only).

        A2-FIX: Schema endpoints now enforce the full S10/S12/S13 chain via
        _apply_schema_policy_gate() before any execution occurs.
        
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
            # Layer 1: shared-secret auth
            auth_error = self._check_auth()
            if auth_error:
                status, error = auth_error
                self._send_json_response(status, error)
                return

            # Layer 2: admin token — fail-closed.
            # If WEBHOOK_ADMIN_TOKEN is not configured, ALL schema requests are rejected.
            from .config import WEBHOOK_ADMIN_TOKEN as _SCHEMA_ADMIN_TOKEN
            admin_token = self.headers.get("X-Assistant-Admin-Token", "")
            if not _SCHEMA_ADMIN_TOKEN or not admin_token or admin_token != _SCHEMA_ADMIN_TOKEN:
                status, error = _make_json_error(
                    403, "Admin token missing or invalid for schema operations", "Forbidden"
                )
                self._send_json_response(status, error)
                return

            # Layer 3: A2-FIX — full policy + capability-token gate (S10/S12/S13).
            gate_error = self._apply_schema_policy_gate()
            if gate_error is not None:
                gate_status, gate_body = gate_error
                self._send_json_response(gate_status, gate_body)
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

        A2-FIX: Schema endpoints now enforce the full S10/S12/S13 chain via
        _apply_schema_policy_gate() before any execution occurs.

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
            # Layer 1: shared-secret auth
            auth_error = self._check_auth()
            if auth_error:
                status, error = auth_error
                self._send_json_response(status, error)
                return

            # Layer 2: admin token — fail-closed.
            # If WEBHOOK_ADMIN_TOKEN is not configured, ALL schema requests are rejected.
            from .config import WEBHOOK_ADMIN_TOKEN as _SCHEMA_ADMIN_TOKEN
            admin_token = self.headers.get("X-Assistant-Admin-Token", "")
            if not _SCHEMA_ADMIN_TOKEN or not admin_token or admin_token != _SCHEMA_ADMIN_TOKEN:
                status, error = _make_json_error(
                    403, "Admin token missing or invalid for schema operations", "Forbidden"
                )
                self._send_json_response(status, error)
                return

            # Layer 3: A2-FIX — full policy + capability-token gate (S10/S12/S13).
            gate_error = self._apply_schema_policy_gate()
            if gate_error is not None:
                gate_status, gate_body = gate_error
                self._send_json_response(gate_status, gate_body)
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
    # M29: Cognition Presence Endpoints
    # -------------------------------------------------------------------------

    def _handle_cognition_providers_get(self) -> None:
        """GET /cognition/providers — list all cognitive providers and their health."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        try:
            from .cognition.providers import get_providers
            result = get_providers()
            self._send_json_response(200, result)
        except Exception as exc:
            status, error = _make_json_error(500, f"Cognition providers error: {exc}", "InternalError")
            self._send_json_response(status, error)

    # -------------------------------------------------------------------------
    # S-CODE-READINESS-01B: CODE readiness (read-only passive surface)
    # -------------------------------------------------------------------------

    def _handle_code_readiness_get(self) -> None:
        """GET /code/readiness — read-only CODE domain readiness summary.

        Wraps assistant_os.codeops.readiness.get_code_readiness() in a stable
        envelope. No execution, no mutation, no apply. Authority remains with
        MSO; this surface only reports source availability and configuration.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        try:
            from .codeops.readiness import get_code_readiness
            summary = get_code_readiness()
            self._send_json_response(
                200,
                {
                    "ok": True,
                    "source": "code_readiness",
                    **summary,
                },
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft per readiness contract
            self._send_json_response(
                200,
                {
                    "ok": False,
                    "source": "code_readiness",
                    "domain": "CODE",
                    "error": f"readiness producer unavailable: {exc}",
                    "note": (
                        "Readiness is source availability and configuration only — "
                        "it is not authority. Capabilities are governed by MSO."
                    ),
                },
            )

    # -------------------------------------------------------------------------
    # S-CONFIRM-FLOW-01B: Confirm flow queue observability (read-only)
    # -------------------------------------------------------------------------

    def _handle_confirm_pending_get(self) -> None:
        """GET /confirm/pending — read-only confirm flow queue summary.

        Exposes observability over the pending confirmation queue.
        No execution, no mutation, no approval.  Authority remains with
        MSO/policy; this surface only reports queue state.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        params = self._parse_query_params()
        _raw_limit = params.get("limit", "")
        try:
            limit = int(_raw_limit)
        except (ValueError, TypeError):
            limit = 10
        limit = max(1, min(50, limit))

        _NOTE_ENDPOINT = (
            "Confirm flow queue is observability only — confirmation remains governed "
            "by MSO/policy and consumed by domain confirmation endpoints."
        )
        try:
            from .confirm_flow.readiness import get_confirm_flow_summary
            summary = get_confirm_flow_summary(limit=limit)
            self._send_json_response(
                200,
                {
                    "ok": True,
                    "source": "confirm_flow",
                    **summary,
                },
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft
            self._send_json_response(
                200,
                {
                    "ok": False,
                    "source": "confirm_flow",
                    "pending_count": 0,
                    "expired_pending_count": 0,
                    "pending": [],
                    "error": str(exc),
                    "note": _NOTE_ENDPOINT,
                },
            )

    def _handle_mso_prepared_actions_pending_get(self) -> None:
        """GET /mso/prepared-actions/pending — read-only ConfirmablePreparedAction queue.

        Exposes the current in-memory manual review queue.
        Read-only: no execution, no mutation, no approval, no token issuance,
        no AuthorizedPlan creation, no PoliceGate call, no runner/pipeline.
        Authority remains closed.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        _NOTE = (
            "Prepared action review queue is read-only. "
            "Human confirmation and the full authority chain are still pending. "
            "This surface does not execute, approve, or issue tokens."
        )
        try:
            from .mso.human_confirmation import merge_confirmation_into_dict
            from .mso.policy_review import merge_policy_review_into_dict
            from .mso.authority_binding import merge_authority_binding_into_dict
            from .mso.prepared_action_queue import list_pending_confirmable_action_dicts
            items = [
                merge_authority_binding_into_dict(
                    merge_policy_review_into_dict(merge_confirmation_into_dict(i))
                )
                for i in list_pending_confirmable_action_dicts()
            ]
            self._send_json_response(
                200,
                {
                    "ok": True,
                    "source": "prepared_action_queue",
                    "count": len(items),
                    "items": items,
                    "review_only": True,
                    "execution_allowed": False,
                    "can_execute_now": False,
                    "note": _NOTE,
                },
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft
            self._send_json_response(
                200,
                {
                    "ok": False,
                    "source": "prepared_action_queue",
                    "count": 0,
                    "items": [],
                    "review_only": True,
                    "execution_allowed": False,
                    "can_execute_now": False,
                    "note": _NOTE,
                    "error": str(exc),
                },
            )

    def _handle_mso_prepared_actions_confirm_post(self) -> None:
        """POST /mso/prepared-actions/confirm — record a human confirmation signal.

        Writes a HumanConfirmationRecord for the given prepared action entry.
        Does NOT grant execution authority, satisfy any authority chain step,
        issue tokens, create AuthorizedPlan, call PoliceGate, or invoke runner.
        execution_allowed and can_execute_now remain False.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        body = self._read_body()
        status, response = _process_mso_confirm_request(body)
        self._send_json_response(status, response)

    def _handle_mso_prepared_actions_policy_review_post(self) -> None:
        """POST /mso/prepared-actions/policy-review — evaluate MSO capability policy for a confirmed prepared action.

        Produces an MSOPolicyDecisionDraft — the first authority chain artifact after HumanConfirmationRecord.
        Does NOT issue CapabilityToken, create OperationBinding or AuthorizedPlan, call PoliceGate,
        invoke runner, or grant execution authority.
        execution_allowed and can_execute_now remain False.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        body = self._read_body()
        status, response = _process_mso_policy_review_request(body)
        self._send_json_response(status, response)

    def _handle_mso_prepared_actions_authority_binding_post(self) -> None:
        """POST /mso/prepared-actions/authority-binding — create MSOAuthorityBindingDraft.

        Second authority chain artifact after MSOPolicyDecisionDraft.
        Requires policy_outcome in ("approved", "approved_confirm_only").
        Does NOT call token_issuer, create OperationBinding/AuthorizedPlan,
        call PoliceGate, or invoke runner. execution_allowed remains False.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        body = self._read_body()
        status, response = _process_mso_authority_binding_request(body)
        self._send_json_response(status, response)

    def _handle_mso_seat_provider_get(self) -> None:
        """GET /mso/seat/provider — read-only MSO Seat cognitive provider metadata.

        Returns the currently configured Delegated MSO Seat provider and its
        honest availability state.

        Read-only: no execution, no network calls to provider, no token issuance,
        no AuthorizedPlan creation, no PoliceGate call, no runner/pipeline.
        Provider metadata is config-derived only — never fabricated.
        """
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return

        _NOTE = (
            "MSO Seat provider metadata is read-only. "
            "Provider availability is config-derived — no network calls are made. "
            "This surface does not execute, approve, or issue tokens. "
            "Cognitive only. Used execution: false."
        )

        try:
            from .mso.seat_model_provider_registry import (
                get_seated_provider,
                describe_seated_provider,
            )

            provider = get_seated_provider()
            description = describe_seated_provider()

            if provider is None:
                self._send_json_response(
                    200,
                    {
                        "ok": True,
                        "seat_provider": None,
                        "description": description,
                        "execution_allowed": False,
                        "can_execute_now": False,
                        "note": _NOTE,
                    },
                )
                return

            provider_dict = provider.to_dict()
            seat_provider = {
                "provider_name": provider_dict["provider_name"],
                "model_name": provider_dict["model_name"],
                "provider_kind": provider_dict["provider_name"],
                "is_available": provider_dict["is_available"],
                "availability": provider_dict["availability"],
                "local_or_remote": provider_dict["local_or_remote"],
                "cognitive_only": True,
                "used_execution": False,
                "non_executing": True,
            }

            self._send_json_response(
                200,
                {
                    "ok": True,
                    "seat_provider": seat_provider,
                    "description": description,
                    "execution_allowed": False,
                    "can_execute_now": False,
                    "note": _NOTE,
                },
            )

        except Exception as exc:  # noqa: BLE001 — fail-soft
            self._send_json_response(
                200,
                {
                    "ok": False,
                    "seat_provider": None,
                    "description": "MSO Seat provider metadata unavailable.",
                    "execution_allowed": False,
                    "can_execute_now": False,
                    "note": _NOTE,
                    "error": str(exc),
                },
            )

    def _handle_cognition_providers_health_get(self) -> None:
        """GET /cognition/providers/health — compact health snapshot for all providers."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        try:
            from .cognition.providers import get_providers_health
            providers = get_providers_health()
            self._send_json_response(200, {"ok": True, "providers": providers})
        except Exception as exc:
            status, error = _make_json_error(500, f"Cognition health error: {exc}", "InternalError")
            self._send_json_response(status, error)

    def _handle_cognition_preferences_get(self) -> None:
        """GET /cognition/preferences — return current cognitive usage policy."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        try:
            from .cognition.preferences import get_preferences
            prefs = get_preferences()
            self._send_json_response(200, {"ok": True, **prefs})
        except Exception as exc:
            status, error = _make_json_error(500, f"Cognition preferences error: {exc}", "InternalError")
            self._send_json_response(status, error)

    def _handle_cognition_preferences_post(self, remote: str) -> None:
        """POST /cognition/preferences — update cognitive usage policy."""
        auth_error = self._check_auth()
        if auth_error:
            status, error = auth_error
            self._send_json_response(status, error)
            return
        result = self._read_body(max_bytes=WEBHOOK_MAX_BYTES)
        if result[1] is not None:
            status, error = result[1]
            self._send_json_response(status, error)
            return
        try:
            body = json.loads(result[0]) if result[0] else {}
        except json.JSONDecodeError as exc:
            status, error = _make_json_error(400, f"Invalid JSON: {exc}", "InvalidJSON")
            self._send_json_response(status, error)
            return
        policy = body.get("policy", "")
        if not isinstance(policy, str) or not policy:
            status, error = _make_json_error(400, "Missing required field: policy", "BadRequest")
            self._send_json_response(status, error)
            return
        try:
            from .cognition.preferences import set_preferences
            success, err_msg = set_preferences(policy)
            if not success:
                status, error = _make_json_error(400, err_msg, "BadRequest")
                self._send_json_response(status, error)
                return
            from .cognition.preferences import get_preferences
            prefs = get_preferences()
            self._send_json_response(200, {"ok": True, **prefs})
        except Exception as exc:
            status, error = _make_json_error(500, f"Cognition preferences update error: {exc}", "InternalError")
            self._send_json_response(status, error)

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
            
            # ALFA invariant — NO fake success.
            # When live mode is disabled, the server MUST NOT claim a PR was
            # created. We return ok=False and execution_status="stub" so
            # callers (and the UI) can render the truthful state.
            handler = CodeOpsHandler()
            if not CODEOPS_LIVE_MODE:
                planned_branch = handler._generate_branch_name(goal)
                stub_response = {
                    "ok": False,
                    "pr_number": None,
                    "pr_url": None,
                    "branch": planned_branch,
                    "execution_status": "stub",
                    "error": (
                        "CodeOps live mode disabled — no PR was created. "
                        "Set CODEOPS_LIVE_MODE=true and provide a valid GITHUB_TOKEN "
                        "to enable real PR execution."
                    ),
                }
                _log_codeops_event(
                    remote=remote,
                    endpoint="/codeops/pr",
                    ok=False,
                    repo=repo,
                    goal=goal,
                    context_id=context_id,
                    pr_url="",
                    error_message="codeops_live_mode_disabled",
                )
                self._send_json_response(200, stub_response)
                return

            # Live mode — delegate to handler (real PR path).
            pr_result: PRResponse = handler.create_pr(data)
            wire_response = dict(pr_result)
            # Stamp execution_status so the wire is unambiguous either way.
            wire_response["execution_status"] = "real" if pr_result["ok"] else "unavailable"

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

            self._send_json_response(200, wire_response)
            
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

    # -------------------------------------------------------------------------
    # HOST domain handlers (Phase 4A)
    # -------------------------------------------------------------------------

    def _handle_host_action(self, remote: str) -> None:
        """Handle POST /host/action — execute a HOST action through the orchestrator.

        API contract (Phase 4B)
        -----------------------
        Request body:
          {
            "action":  str   — required, one of: open_app | close_pid | open_directory |
                               open_url | list_directory | open_file | read_text_file
            "payload": dict  — required, action-specific payload
          }

        Response shape (all cases):
          { "ok": bool, "domain": "HOST", "result_type": str,
            "data": dict, "error": {"type", "message", "code"} | null }

        HTTP status:
          200  action executed (ok=True)
          202  plan_confirmation_required (RISK_MEDIUM, use /host/confirm with data.plan_id)
          400  missing/invalid fields, unknown action
          401  missing or invalid auth token
          409  CONTROL_PLANE_BLOCKED
          500  unexpected pipeline error

        Invariants:
        - NEVER calls host_pipeline or host_agent directly
        - action field accepts ONLY short names (no HOST_ prefix)
        - risk_level is NOT overridable by callers — determined by action
        - single response shape for ALL outcomes
        """
        # --- Auth ---
        auth_error = self._check_auth()
        if auth_error:
            http_s, raw = auth_error
            err = (raw.get("error") or {})
            self._send_json_response(http_s, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error(err.get("type", "Unauthorized"), err.get("message", "Authentication required")),
            ))
            return

        # --- Content-Type ---
        if "application/json" not in self.headers.get("Content-Type", ""):
            self._send_json_response(400, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error("BadRequest", "Content-Type must be application/json"),
            ))
            return

        # --- Read body ---
        body_result = self._read_body()
        if body_result[1] is not None:
            http_s, raw = body_result[1]
            err = (raw.get("error") or {})
            self._send_json_response(http_s, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error(err.get("type", "BadRequest"), err.get("message", "Failed to read body")),
            ))
            return
        body = body_result[0]

        # --- Parse JSON ---
        try:
            req_data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json_response(400, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error("BadRequest", f"Invalid JSON: {exc}"),
            ))
            return

        if not isinstance(req_data, dict):
            self._send_json_response(400, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error("BadRequest", "Request body must be a JSON object"),
            ))
            return

        # --- Validate: action (required, must be a known short name) ---
        action = req_data.get("action")
        if not action or not isinstance(action, str) or action not in _HOST_VALID_ACTIONS:
            known = ", ".join(sorted(_HOST_VALID_ACTIONS))
            msg = f'Invalid or missing "action". Must be one of: {known}'
            self._send_json_response(400, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error("BadRequest", msg),
            ))
            return

        # --- Validate: payload (required, must be a dict) ---
        payload = req_data.get("payload")
        if payload is None or not isinstance(payload, dict):
            self._send_json_response(400, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error("BadRequest", 'Missing required field: "payload" (must be an object)'),
            ))
            return

        # --- Resolve canonical action and risk level (not overridable) ---
        canonical_action = _HOST_SHORT_TO_CANONICAL[action]
        risk_level = _HOST_ACTION_RISK[canonical_action]

        # --- Build CanonicalRequest and call orchestrator ---
        from .contracts import normalize_request
        from .core.orchestrator import handle_request as _handle_request

        req = normalize_request(
            text="",
            metadata={
                "action":               canonical_action,
                "domain":               "HOST",
                "risk_level":           risk_level,
                "requires_confirmation": risk_level != "low",
                "domain_payload":       payload,
            },
        )
        dr = _handle_request(req)

        # --- Adapt DomainResult → canonical HOST response shape ---
        self._send_json_response(_host_http_status(dr), _host_dr_to_response(dr))

    def _handle_host_confirm(self, remote: str) -> None:
        """Handle POST /host/confirm — confirm a pending HOST plan by plan_id.

        API contract (Phase 4B)
        -----------------------
        Request body:
          { "plan_id": str }  — UUID from /host/action 202 response data.plan_id

        Response shape (all cases):
          { "ok": bool, "domain": "HOST", "result_type": str,
            "data": dict, "error": {"type", "message", "code"} | null }

        HTTP status:
          200  confirmed action executed
          400  missing or invalid plan_id
          401  missing or invalid auth token
          404  plan_id not found or expired (single-use: already consumed)
          409  CONTROL_PLANE_BLOCKED (agent quarantined between passes)
          500  unexpected pipeline error

        Invariants:
        - plan_id is single-use (removed before execution — Phase 3C)
        - NEVER calls host_pipeline or host_agent directly
        - single response shape for ALL outcomes
        """
        # --- Auth ---
        auth_error = self._check_auth()
        if auth_error:
            http_s, raw = auth_error
            err = (raw.get("error") or {})
            self._send_json_response(http_s, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error(err.get("type", "Unauthorized"), err.get("message", "Authentication required")),
            ))
            return

        # --- Content-Type ---
        if "application/json" not in self.headers.get("Content-Type", ""):
            self._send_json_response(400, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error("BadRequest", "Content-Type must be application/json"),
            ))
            return

        # --- Read body ---
        body_result = self._read_body()
        if body_result[1] is not None:
            http_s, raw = body_result[1]
            err = (raw.get("error") or {})
            self._send_json_response(http_s, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error(err.get("type", "BadRequest"), err.get("message", "Failed to read body")),
            ))
            return
        body = body_result[0]

        # --- Parse JSON ---
        try:
            req_data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json_response(400, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error("BadRequest", f"Invalid JSON: {exc}"),
            ))
            return

        if not isinstance(req_data, dict):
            self._send_json_response(400, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error("BadRequest", "Request body must be a JSON object"),
            ))
            return

        # --- Validate: plan_id (required, non-empty string) ---
        plan_id = req_data.get("plan_id")
        if not plan_id or not isinstance(plan_id, str):
            self._send_json_response(400, _host_response(
                ok=False, result_type=_HOST_RESULT_TYPE_ERROR, data={},
                error=_host_error("BadRequest", 'Missing required field: "plan_id" (must be a non-empty string)'),
            ))
            return

        # --- Build CanonicalRequest and call orchestrator confirm path ---
        from .contracts import normalize_request
        from .core.orchestrator import handle_request as _handle_request

        dr = _handle_request(normalize_request(
            text="",
            metadata={"confirm_plan_id": plan_id},
        ))

        # --- Adapt DomainResult → canonical HOST response shape ---
        self._send_json_response(_host_http_status(dr), _host_dr_to_response(dr))

    def _handle_machine_operator_execute(self, remote: str) -> None:
        """Handle POST /machine_operator/execute — run a bounded browser capability.

        API contract
        ------------
        Request body:
          {
            "capability": str  — required; one of: browser.navigate | browser.snapshot |
                                 browser.screenshot | browser.read_visible_text
            "arguments":  dict — optional; capability-specific arguments (default: {})
          }

        Response: raw DomainResult JSON
          { "ok": bool, "domain": "MACHINE_OPERATOR", "result_type": str,
            "data": dict, "execution_status": str, "error": dict | null, ... }

        HTTP status:
          200  ok=True (real execution completed)
          200  ok=False (policy/contract/backend failure — error details in body)
          400  missing/invalid fields
          401  missing or invalid auth token
        """
        import uuid as _uuid

        # --- Auth ---
        auth_error = self._check_auth()
        if auth_error:
            http_s, raw = auth_error
            self._send_json_response(http_s, raw)
            return

        # --- Content-Type ---
        if "application/json" not in self.headers.get("Content-Type", ""):
            status, error = _make_json_error(400, "Content-Type must be application/json", "BadRequest")
            self._send_json_response(status, error)
            return

        # --- Read body ---
        body_result = self._read_body()
        if body_result[1] is not None:
            status, error = body_result[1]
            self._send_json_response(status, error)
            return
        body = body_result[0]

        # --- Parse JSON ---
        try:
            req_data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            status, error = _make_json_error(400, f"Invalid JSON: {exc}", "BadRequest")
            self._send_json_response(status, error)
            return

        if not isinstance(req_data, dict):
            status, error = _make_json_error(400, "Request body must be a JSON object", "BadRequest")
            self._send_json_response(status, error)
            return

        # --- Validate: capability ---
        from .mso.contracts import MACHINE_OPERATOR_ALLOWED_CAPABILITIES
        capability = req_data.get("capability")
        if not capability or not isinstance(capability, str):
            status, error = _make_json_error(400, 'Missing required field: "capability"', "BadRequest")
            self._send_json_response(status, error)
            return
        if capability not in MACHINE_OPERATOR_ALLOWED_CAPABILITIES:
            known = ", ".join(sorted(MACHINE_OPERATOR_ALLOWED_CAPABILITIES))
            status, error = _make_json_error(
                400, f'Unknown capability {capability!r}. Allowed: {known}', "BadRequest"
            )
            self._send_json_response(status, error)
            return

        # --- Validate: arguments (optional, must be dict if present) ---
        arguments = req_data.get("arguments", {})
        if not isinstance(arguments, dict):
            status, error = _make_json_error(400, '"arguments" must be a JSON object', "BadRequest")
            self._send_json_response(status, error)
            return

        # browser.navigate is interactive and requires approval_mode=required.
        # This endpoint operates in auto/none mode — reject navigate explicitly.
        if capability == "browser.navigate":
            self._send_json_response(200, {
                "ok": False,
                "domain": "MACHINE_OPERATOR",
                "result_type": "machine_operator_action",
                "execution_status": "unavailable",
                "message": (
                    "browser.navigate requires approval_mode=required and cannot be "
                    "auto-executed through this endpoint. Submit a supervised request "
                    "with an explicit approval token."
                ),
                "data": {},
                "error": {
                    "type": "PolicyViolation",
                    "reason_code": "approval_mode_mismatch",
                    "message": "navigate requires approval_mode=required",
                },
            })
            return

        # All remaining capabilities are read-only (N0, approval_mode=none).
        capability_tier = "read_only"

        intent_id      = str(_uuid.uuid4())
        correlation_id = str(_uuid.uuid4())

        machine_operator_request = {
            "intent_id":      intent_id,
            "correlation_id": correlation_id,
            "capability_name": capability,
            "capability_tier": capability_tier,
            "arguments":      arguments,
            "policy_context": {
                "policy_decision_ref": f"auto:{intent_id}",
                "governance_ref":      "governance://machine_operator/execute",
                "execution_mode":      "auto",
                "approval_mode":       "none",
                "constraints":         [],
                "allowlist_refs":      ["system:browser_read_only"],
                "secret_refs":         [],
            },
            "budget": {
                "max_steps":        1,
                "max_duration_ms":  30000,
                "max_output_bytes": 131072,
                "max_side_effects": 0,
            },
            "requested_side_effects": [],
        }

        from .contracts import normalize_request, ACTION_MACHINE_OPERATOR_EXECUTE, RISK_LOW
        from .core.orchestrator import handle_request as _handle_request

        req = normalize_request(
            text="",
            metadata={
                "action":                ACTION_MACHINE_OPERATOR_EXECUTE,
                "domain":                "MACHINE_OPERATOR",
                "risk_level":            RISK_LOW,
                "requires_confirmation": False,
                "domain_payload": {
                    "machine_operator_request": machine_operator_request,
                },
            },
        )
        dr = _handle_request(req)
        self._send_json_response(200, dict(dr))


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class WebhookHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTP Server with threaded request handling and clean shutdown support."""

    daemon_threads = True
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

    Raises RuntimeError before binding if WEBHOOK_TOKEN is not configured.

    Args:
        host: Bind address (default: 127.0.0.1)
        port: Port number (default: 8787)
    """
    from .config import validate_startup_config
    validate_startup_config()

    from .executors.startup import setup_all_code_executors
    from .mso.system_state import _load_persisted_state as _apply_persisted_mode
    _apply_persisted_mode()
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

    # poll_interval=0.05 (50 ms) vs default 0.5 s: server notices shutdown()
    # faster and releases the socket sooner.  This reduces the Windows loopback
    # socket-churn window that causes WinError 10053 (ConnectionAborted) when
    # many test servers start and stop in rapid succession within one process.
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
    )
    thread.start()

    return server, actual_port


if __name__ == "__main__":
    run_server()
