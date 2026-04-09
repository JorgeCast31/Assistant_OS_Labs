"""
WORK domain HTTP handlers.

Sprint 2 — Full Canonical Entry
--------------------------------
All three main handlers are pure HTTP adapters:

    HTTP body → normalize_request() → handle_request() → HTTP response

The orchestrator's structured path (req["metadata"]["action"] is set) bypasses
NL classification and builds the plan directly from req["filters"] +
req["metadata"], then dispatches to work_pipeline via the domain registry.

Handlers no longer call make_plan(), build_policy(), or pipeline.execute()
directly. orchestrator.handle_request() is the single canonical entry point.

Backward-compatibility note
----------------------------
HTTP response shapes are kept identical to the pre-sprint format except two new
fields (added non-breakingly in Sprint 1):
  - execution_id: plan_id from DomainResult (canonical trace anchor)
  - result_type:  RESULT_TYPE_* constant from DomainResult

LEGACY code
-----------
_execute_work_delete is preserved below because the smoke test imports it.
It is no longer called from the main handler flow.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..webhook_server import WebhookHandler

from ..webhook_utils import _make_json_error, _log_webhook_event
from ..contracts import (
    normalize_request,
    ACTION_WORK_QUERY,
    ACTION_WORK_CREATE,
    ACTION_WORK_DELETE,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
)
from ..core.orchestrator import handle_request as _handle_request


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_error_msg(dr: dict) -> str | None:
    """Extract a plain error string from a DomainResult for legacy response compat."""
    err = dr.get("error")
    if err and isinstance(err, dict):
        return err.get("message")
    return None


# ---------------------------------------------------------------------------
# WORK Query
# ---------------------------------------------------------------------------

def handle_work_query(handler: "WebhookHandler", remote: str) -> None:
    """
    Handle POST /work/query - Query WORK tasks from Notion (read-only).

    Canonical path: make_plan → build_policy → work_pipeline.execute → DomainResult

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

        # Pending session guard (unchanged)
        session_context = data.get("session_context", {})
        if session_context.get("pending"):
            handler._send_json_response(200, {
                "ok": False,
                "items": [],
                "total": 0,
                "formatted": "Tienes un flujo pendiente. Complétalo antes de consultar tareas.",
                "error": "pending_flow",
                "execution_id": None,
            })
            return

        # Extract and normalise filters
        text = data.get("text", "")
        filters: dict = data.get("filters", {})
        if text and not filters:
            from ..classifier import parse_work_query_filters
            filters = parse_work_query_filters(text)
        if "status" not in filters:
            from ..config import NOTION_WORK_ACTIVE_STATUSES
            filters["status"] = NOTION_WORK_ACTIVE_STATUSES

        # ── Canonical entry ──────────────────────────────────────────────
        req = normalize_request(
            text=text or "",
            filters=dict(filters),
            metadata={
                "action": ACTION_WORK_QUERY,
                "domain": "WORK",
                "risk_level": RISK_LOW,
                "requires_confirmation": False,
                "target": "work db query",
            },
        )
        dr = _handle_request(req)
        # ── End canonical entry ──────────────────────────────────────────

        data_out = dr.get("data", {})
        _log_webhook_event(
            "/work/query",
            remote,
            ok=dr["ok"],
            event_type="work_query",
        )

        handler._send_json_response(200, {
            "ok": dr["ok"],
            "items": data_out.get("items", []),
            "total": data_out.get("total", 0),
            "formatted": data_out.get("formatted", ""),
            "error": _extract_error_msg(dr),
            "query_filters": filters,
            # Canonical traceability (new, non-breaking)
            "execution_id": dr.get("plan_id"),
            "result_type": dr.get("result_type"),
        })

    except Exception as e:
        _log.error("handle_work_query exception: %s", e, exc_info=True)
        _log_webhook_event("/work/query", remote, ok=False, event_type="work_query_error")
        handler._send_json_response(500, {
            "ok": False,
            "items": [],
            "total": 0,
            "formatted": f"❌ Error interno: {e}",
            "error": str(e),
            "execution_id": None,
        })


# ---------------------------------------------------------------------------
# WORK Create
# ---------------------------------------------------------------------------

def handle_work_create(handler: "WebhookHandler", remote: str) -> None:
    """
    Handle POST /work/create - Create a WORK task in Notion.

    This endpoint is called AFTER user confirms the create action.

    Canonical path: make_plan → build_policy → work_pipeline.execute → DomainResult

    Request JSON:
    {
        "title": "Task title (required)",
        "project": "Project name (optional)",
        "status": "INBOX (optional, default)",
        "load": "Alta|Media|Baja (optional)",
        "due": "YYYY-MM-DD (optional)",
        "notes": "Additional notes (optional)"
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

        # ── Canonical entry ──────────────────────────────────────────────
        req = normalize_request(
            text=title,
            filters={
                "title": title,
                "project": data.get("project"),
                "status": data.get("status", "INBOX"),
                "load": data.get("load"),
                "due": data.get("due"),
                "notes": data.get("notes"),
            },
            metadata={
                "action": ACTION_WORK_CREATE,
                "domain": "WORK",
                "risk_level": RISK_MEDIUM,
                # Post-confirmation endpoint: requires_confirmation=False signals the
                # policy layer that this call is already approved by the user.
                "requires_confirmation": False,
                "target": title,
            },
        )
        dr = _handle_request(req)
        # ── End canonical entry ──────────────────────────────────────────

        data_out = dr.get("data", {})
        _log_webhook_event(
            "/work/create",
            remote,
            ok=dr["ok"],
            event_type="work_create",
        )

        handler._send_json_response(200, {
            "ok": dr["ok"],
            "page_id": data_out.get("page_id", ""),
            "url": data_out.get("url", ""),
            "title": data_out.get("title", title),
            "error": _extract_error_msg(dr),
            # Canonical traceability (new, non-breaking)
            "execution_id": dr.get("plan_id"),
            "result_type": dr.get("result_type"),
        })

    except Exception as e:
        _log.error("handle_work_create exception: %s", e, exc_info=True)
        _log_webhook_event("/work/create", remote, ok=False, event_type="work_create_error")
        handler._send_json_response(500, {
            "ok": False,
            "page_id": "",
            "url": "",
            "title": "",
            "error": str(e),
            "execution_id": None,
        })


# ---------------------------------------------------------------------------
# WORK Delete
# ---------------------------------------------------------------------------

def handle_work_delete(
    handler: "WebhookHandler",
    remote: str,
    *,
    trash_db_id: str | None = None,
) -> None:
    """
    Handle POST /work/delete - Delete/archive WORK tasks from Notion.

    Canonical path: make_plan → build_policy → work_pipeline.execute → DomainResult

    Known gap: trash_db_id (move-to-trash mode) is not yet supported in the
    pipeline; all deletes fall back to archive.  This is documented and
    acceptable for Sprint 1 scope.

    trash_db_id is still accepted in the signature so existing test patches on
    assistant_os.webhook_server.NOTION_WORK_TRASH_DB_ID continue to work.

    Request JSON:
    {
        "keywords": ["keyword1", "keyword2"],
        "delete_all": false,
        "delete_mode": "archive"
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

        # ── Canonical entry ──────────────────────────────────────────────
        req = normalize_request(
            text="",
            filters={
                "keywords": keywords,
                "delete_all": delete_all,
                "delete_mode": delete_mode,
                # trash_db_id is noted here for observability; pipeline uses archive.
                "trash_db_id": trash_db_id,
            },
            metadata={
                "action": ACTION_WORK_DELETE,
                "domain": "WORK",
                "risk_level": RISK_HIGH,
                # Post-confirmation endpoint: the caller has already confirmed.
                "requires_confirmation": False,
                "target": "work items",
            },
        )
        dr = _handle_request(req)
        # ── End canonical entry ──────────────────────────────────────────

        data_out = dr.get("data", {})
        _log_webhook_event(
            "/work/delete",
            remote,
            ok=dr["ok"],
            event_type="work_delete",
        )

        deleted_count = data_out.get("deleted_count", 0)
        handler._send_json_response(200, {
            "ok": dr["ok"],
            # Backward-compat: pipeline archives everything (no trash mode yet).
            # deleted_count = number of archived items; archived_count mirrors it.
            "deleted_count": deleted_count,
            "archived_count": deleted_count,
            "pages": [],
            "error": _extract_error_msg(dr),
            # Canonical traceability (new, non-breaking)
            "execution_id": dr.get("plan_id"),
            "result_type": dr.get("result_type"),
        })

    except Exception as e:
        _log.error("handle_work_delete exception: %s", e, exc_info=True)
        _log_webhook_event("/work/delete", remote, ok=False, event_type="work_delete_error")
        handler._send_json_response(500, {
            "ok": False,
            "deleted_count": 0,
            "archived_count": 0,
            "pages": [],
            "error": str(e),
            "execution_id": None,
        })


# ---------------------------------------------------------------------------
# LEGACY: _execute_work_delete
#
# This function is no longer called from the main handler flow.
# Preserved for test import compatibility (test_handlers_work_smoke.py).
# The canonical delete path is now: handle_work_delete → work_pipeline.execute.
#
# Known gap vs pipeline: supports trash_db_id / move_pages_to_db; the pipeline
# currently only archives.  Migration of trash mode is deferred to Sprint 2.
# ---------------------------------------------------------------------------

from ..integrations.notion import (
    check_notion_available,
    query_work_items_by_keywords,
    archive_pages,
)
from ..config import NOTION_WORK_DB_ID


def _execute_work_delete(
    keywords: list[str],
    delete_all: bool,
    delete_mode: str,
    trash_db_id: str | None = None,
) -> dict:
    """
    LEGACY — superseded by handle_work_delete → work_pipeline.execute canonical path.

    Kept for test import compatibility only.  Not called from any active handler.
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
