"""
Shared webhook utilities.

Extracted from webhook_server.py to allow handler modules (handlers/work.py,
handlers/fin.py) to import these helpers without creating circular imports.

webhook_server.py re-imports these under its own namespace so existing tests
that patch 'assistant_os.webhook_server._make_json_error' etc. keep working.
"""
import json

from .config import MEMORY_DIR, LOG_FILE
from .contracts import new_context_id, now_iso
from .type_aliases import JsonErrorResponse, JsonResponse


# ---------------------------------------------------------------------------
# Response Helpers
# ---------------------------------------------------------------------------

def _make_json_error(
    status_code: int,
    message: str,
    err_type: str = "BadRequest",
) -> JsonErrorResponse:
    """Build a JSON error response dict."""
    context_id = new_context_id()
    response: JsonResponse = {
        "context_id": context_id,
        "agent": "webhook",
        "status": "error",
        "output": {},
        "error": {"type": err_type, "message": message},
        "ts": now_iso(),
    }
    return status_code, response


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_webhook_event(
    path: str,
    remote: str,
    ok: bool,
    agent: str = "",
    context_id: str = "",
    event_type: str = "webhook",
    text_len: int = 0,
    conversation_id: str = "",
) -> None:
    """Append webhook event to log.ndjson."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    event: dict = {
        "ts": now_iso(),
        "type": event_type,
        "path": path,
        "remote": remote,
        "ok": ok,
        "agent": agent,
        "context_id": context_id,
    }

    if text_len > 0:
        event["text_len"] = text_len

    if conversation_id:
        event["conversation_id"] = conversation_id

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _log_fin_expense_event(
    remote: str,
    ok: bool,
    action: str = "parse",  # "parse" | "confirm" | "sheets_append"
    monto: float = 0.0,
    moneda: str = "",
    categoria: str = "",
    responsable: str = "",
    needs_confirmation: bool = False,
    session_id: str = "",
    error_message: str = "",
    text_preview: str = "",
) -> None:
    """Log a FIN expense event (type=fin_expense)."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    event: dict = {
        "ts": now_iso(),
        "type": "fin_expense",
        "remote": remote,
        "ok": ok,
        "action": action,
    }

    if ok:
        event["monto"] = monto
        event["moneda"] = moneda
        event["categoria"] = categoria
        event["responsable"] = responsable
        event["needs_confirmation"] = needs_confirmation

    if session_id:
        event["session_id"] = session_id

    if error_message:
        event["error"] = error_message

    if text_preview:
        event["text_preview"] = text_preview[:120] if len(text_preview) > 120 else text_preview

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
