"""
WORK domain HTTP handlers.

Standalone functions extracted from WebhookHandler class in webhook_server.py.
Each function accepts the handler instance as first argument so it can call
self._check_auth(), self._read_body(), self._send_json_response() unchanged.

The WebhookHandler class delegates to these functions via one-liner methods:

    def _handle_work_query(self, remote: str) -> None:
        from .handlers.work import handle_work_query
        handle_work_query(self, remote)

Test patching note:
  NOTION_WORK_TRASH_DB_ID is kept in webhook_server module namespace and passed
  as parameter so @patch('assistant_os.webhook_server.NOTION_WORK_TRASH_DB_ID')
  continues to work in existing tests.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..webhook_server import WebhookHandler

from ..webhook_utils import _make_json_error, _log_webhook_event
from ..integrations.notion import (
    query_work_db,
    format_work_query_response,
    check_notion_available,
    get_notion_status,
    create_work_item,
    WorkCreateRequest,
    query_work_items_by_keywords,
    archive_pages,
)
from ..config import NOTION_WORK_DB_ID


# ---------------------------------------------------------------------------
# WORK Query
# ---------------------------------------------------------------------------

def handle_work_query(handler: "WebhookHandler", remote: str) -> None:
    """
    Handle POST /work/query - Query WORK tasks from Notion (read-only).

    Request JSON:
    {
        "filters": {
            "status": ["NEXT", "SCHEDULED"],
            "project": "CELLAB",
            "load": "Alta",
            "date_range": {"from": "2026-02-26", "to": "2026-03-02"}
        },
        "limit": 20,
        "sort": [{"field": "due", "dir": "asc"}],
        "session_context": {}  // Optional: to check for pending flows
    }
    """
    try:
        auth_error = handler._check_auth()
        if auth_error:
            status, error = auth_error
            handler._send_json_response(status, error)
            return

        result = handler._read_body()
        if result[1] is not None:
            status, error = result[1]
            handler._send_json_response(status, error)
            return

        body = result[0]

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "InvalidJSON")
            handler._send_json_response(status, error)
            return

        # Check for pending session
        session_context = data.get("session_context", {})
        if session_context.get("pending"):
            handler._send_json_response(200, {
                "ok": False,
                "items": [],
                "total": 0,
                "formatted": "Tienes un flujo pendiente. Complétalo antes de consultar tareas.",
                "error": "pending_flow"
            })
            return

        # Check Notion availability
        if not check_notion_available():
            notion_status = get_notion_status()
            error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
            handler._send_json_response(200, {
                "ok": False,
                "items": [],
                "total": 0,
                "formatted": f"❌ Notion no está configurado: {error_msg}",
                "error": error_msg
            })
            return

        # Extract filters - support both structured filters and natural language
        text = data.get("text", "")
        filters: dict = data.get("filters", {})

        if text and not filters:
            from ..classifier import parse_work_query_filters
            filters = parse_work_query_filters(text)

        limit = data.get("limit", 20)
        sort = data.get("sort")

        if "status" not in filters:
            from ..config import NOTION_WORK_ACTIVE_STATUSES
            filters["status"] = NOTION_WORK_ACTIVE_STATUSES

        query_result = query_work_db(filters=filters, limit=limit, sort=sort)
        formatted = format_work_query_response(query_result)

        _log_webhook_event(
            "/work/query",
            remote,
            ok=query_result["ok"],
            event_type="work_query",
        )

        handler._send_json_response(200, {
            "ok": query_result["ok"],
            "items": query_result["items"],
            "total": query_result["total"],
            "formatted": formatted,
            "error": query_result["error"],
            "query_filters": filters,
        })

    except Exception as e:
        _log.error("handle_work_query exception: %s", e, exc_info=True)
        _log_webhook_event("/work/query", remote, ok=False, event_type="work_query_error")
        handler._send_json_response(500, {
            "ok": False,
            "items": [],
            "total": 0,
            "formatted": f"❌ Error interno: {e}",
            "error": str(e)
        })


# ---------------------------------------------------------------------------
# WORK Create
# ---------------------------------------------------------------------------

def handle_work_create(handler: "WebhookHandler", remote: str) -> None:
    """
    Handle POST /work/create - Create a WORK task in Notion.

    This endpoint is called AFTER user confirms the create action.

    Request JSON:
    {
        "title": "Task title (required)",
        "project": "Project name (optional)",
        "status": "INBOX (optional, default)",
        "load": "Alta|Media|Baja (optional)",
        "due": "YYYY-MM-DD (optional)",
        "notes": "Additional notes (optional)",
        "plan": {...}  // Original plan for audit
    }
    """
    try:
        auth_error = handler._check_auth()
        if auth_error:
            status, error = auth_error
            handler._send_json_response(status, error)
            return

        result = handler._read_body()
        if result[1] is not None:
            status, error = result[1]
            handler._send_json_response(status, error)
            return

        body = result[0]

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "InvalidJSON")
            handler._send_json_response(status, error)
            return

        title = data.get("title", "").strip()
        if not title:
            status, error = _make_json_error(400, "Missing required field: title", "BadRequest")
            _log_webhook_event("/work/create", remote, ok=False, event_type="work_create")
            handler._send_json_response(status, error)
            return

        if not check_notion_available():
            notion_status = get_notion_status()
            error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
            handler._send_json_response(200, {
                "ok": False,
                "page_id": "",
                "url": "",
                "title": title,
                "error": error_msg
            })
            return

        create_request: WorkCreateRequest = {
            "title": title,
            "project": data.get("project"),
            "status": data.get("status", "INBOX"),
            "load": data.get("load"),
            "due": data.get("due"),
            "notes": data.get("notes"),
        }

        create_result = create_work_item(create_request)

        _log_webhook_event(
            "/work/create",
            remote,
            ok=create_result["ok"],
            event_type="work_create",
        )

        handler._send_json_response(200, {
            "ok": create_result["ok"],
            "page_id": create_result["page_id"],
            "url": create_result["url"],
            "title": create_result["title"],
            "error": create_result["error"],
        })

    except Exception as e:
        _log.error("handle_work_create exception: %s", e, exc_info=True)
        _log_webhook_event("/work/create", remote, ok=False, event_type="work_create_error")
        handler._send_json_response(500, {
            "ok": False,
            "page_id": "",
            "url": "",
            "title": "",
            "error": str(e)
        })


# ---------------------------------------------------------------------------
# WORK Delete (execution helper + handler)
# ---------------------------------------------------------------------------

def _execute_work_delete(
    keywords: list[str],
    delete_all: bool,
    delete_mode: str,
    trash_db_id: str | None = None,
) -> dict:
    """
    Execute work delete operation.

    Args:
        keywords: Keywords to match in task titles.
        delete_all: If True, delete all matching (up to 50 items).
        delete_mode: "archive" or "trash".
        trash_db_id: NOTION_WORK_TRASH_DB_ID from caller's scope so that
                     test patches on webhook_server.NOTION_WORK_TRASH_DB_ID
                     propagate correctly.

    Returns:
        dict with ok, deleted_count, archived_count, pages, error.
    """
    if not check_notion_available():
        return {
            "ok": False,
            "deleted_count": 0,
            "archived_count": 0,
            "pages": [],
            "error": "Notion not available",
        }

    if not NOTION_WORK_DB_ID:
        return {
            "ok": False,
            "deleted_count": 0,
            "archived_count": 0,
            "pages": [],
            "error": "NOTION_WORK_DB_ID not configured",
        }

    if delete_all and not keywords:
        matching_items = query_work_items_by_keywords(
            db_id=NOTION_WORK_DB_ID,
            keywords=[],
            limit=50,
        )
    else:
        matching_items = query_work_items_by_keywords(
            db_id=NOTION_WORK_DB_ID,
            keywords=keywords,
            op="OR",
            limit=100,
        )

    if not matching_items:
        return {
            "ok": True,
            "deleted_count": 0,
            "archived_count": 0,
            "pages": [],
            "error": "",
        }

    page_ids = [item["id"] for item in matching_items]

    if delete_mode == "trash":
        if trash_db_id:
            from ..integrations.notion import move_pages_to_db
            moved_count = move_pages_to_db(page_ids, trash_db_id)
            return {
                "ok": True,
                "deleted_count": moved_count,
                "archived_count": 0,
                "pages": matching_items[:moved_count],
                "error": "",
            }
        else:
            archived_count = archive_pages(page_ids)
            return {
                "ok": True,
                "deleted_count": 0,
                "archived_count": archived_count,
                "pages": matching_items[:archived_count],
                "error": "NOTION_WORK_TRASH_DB_ID not configured, falling back to archive",
            }
    else:
        archived_count = archive_pages(page_ids)
        return {
            "ok": True,
            "deleted_count": 0,
            "archived_count": archived_count,
            "pages": matching_items[:archived_count],
            "error": "",
        }


def handle_work_delete(
    handler: "WebhookHandler",
    remote: str,
    *,
    trash_db_id: str | None = None,
) -> None:
    """
    Handle POST /work/delete - Delete/archive WORK tasks from Notion.

    trash_db_id is passed explicitly from webhook_server so that tests that
    patch assistant_os.webhook_server.NOTION_WORK_TRASH_DB_ID see the correct
    value at call time.

    Request JSON:
    {
        "keywords": ["keyword1", "keyword2"],
        "delete_all": false,
        "delete_mode": "archive",
        "plan": {...}
    }
    """
    try:
        auth_error = handler._check_auth()
        if auth_error:
            status, error = auth_error
            handler._send_json_response(status, error)
            return

        result = handler._read_body()
        if result[1] is not None:
            status, error = result[1]
            handler._send_json_response(status, error)
            return

        body = result[0]

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError as e:
            status, error = _make_json_error(400, f"Invalid JSON: {e}", "InvalidJSON")
            handler._send_json_response(status, error)
            return

        keywords = data.get("keywords", [])
        delete_all = data.get("delete_all", False)
        delete_mode = data.get("delete_mode", "archive")

        if not keywords and not delete_all:
            status, error = _make_json_error(400, "Missing keywords or delete_all flag", "BadRequest")
            _log_webhook_event("/work/delete", remote, ok=False, event_type="work_delete")
            handler._send_json_response(status, error)
            return

        if not check_notion_available():
            notion_status = get_notion_status()
            error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
            handler._send_json_response(200, {
                "ok": False,
                "deleted_count": 0,
                "archived_count": 0,
                "pages": [],
                "error": error_msg
            })
            return

        delete_result = _execute_work_delete(
            keywords, delete_all, delete_mode, trash_db_id=trash_db_id
        )

        _log_webhook_event(
            "/work/delete",
            remote,
            ok=delete_result["ok"],
            event_type="work_delete",
        )

        handler._send_json_response(200, delete_result)

    except Exception as e:
        _log.error("handle_work_delete exception: %s", e, exc_info=True)
        _log_webhook_event("/work/delete", remote, ok=False, event_type="work_delete_error")
        handler._send_json_response(500, {
            "ok": False,
            "deleted_count": 0,
            "archived_count": 0,
            "pages": [],
            "error": str(e)
        })
