"""
Notion integration for WORK domain.

Supports read AND write operations:
- Read: query_work_db, get_work_item_by_id, search_work_items_by_title, etc.
- Write: create_work_item, update_work_item, archive_pages, move_pages_to_db

Uses Notion API v1 with internal integration token.
Requires:
- requests

Setup:
1. Create an internal integration at https://www.notion.so/my-integrations
2. Copy the Internal Integration Secret
3. Share the WORK database with the integration (with read AND write access for mutations)
4. Set NOTION_TOKEN environment variable (or in config.py)
5. Set NOTION_WORK_DB_ID environment variable (or in config.py)
"""
import json
from datetime import datetime, date
from typing import Optional, Any, TypedDict
import traceback

# Conditional import
REQUESTS_AVAILABLE = False
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None  # type: ignore

from ..config import (
    MEMORY_DIR,
    NOTION_TOKEN,
    NOTION_WORK_DB_ID,
    NOTION_WORK_PROPERTY_MAP,
    NOTION_WORK_ACTIVE_STATUSES,
)
from ..contracts import now_iso

# Test database ID (for mocking in tests)
NOTION_WORK_TEST_DB_ID: str | None = None  # Set via environment or config


# ---------------------------------------------------------------------------
# Type Definitions
# ---------------------------------------------------------------------------

class WorkItem(TypedDict, total=False):
    """A single work item from Notion."""
    notion_page_id: str
    title: str
    status: Optional[str]
    project: Optional[str]
    load: Optional[str]
    impact: Optional[str]
    due: Optional[str]  # ISO date string
    next_action: Optional[str]
    last_edited_time: str


class WorkQueryFilters(TypedDict, total=False):
    """Filters for work query."""
    status: list[str]           # e.g., ["NEXT", "SCHEDULED"]
    project: str                # e.g., "CELLAB"
    load: str                   # e.g., "Alta"
    date_range: dict[str, str]  # {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}


class WorkQueryRequest(TypedDict, total=False):
    """Request structure for work query."""
    filters: WorkQueryFilters
    limit: int
    sort: list[dict[str, str]]  # [{"field": "due", "dir": "asc"}]


class WorkQueryResult(TypedDict):
    """Result from work query."""
    ok: bool
    items: list[WorkItem]
    total: int
    error: str


class NotionError(TypedDict, total=False):
    """Error information for Notion status."""
    type: str       # missing_token | missing_db_id | api_error | network_error | unknown
    message: str
    traceback: str


# ---------------------------------------------------------------------------
# Global State
# ---------------------------------------------------------------------------

_NOTION_LAST_ERROR: Optional[NotionError] = None


def _set_notion_error(error_type: str, message: str, tb: Optional[str] = None) -> None:
    """Set the global Notion error."""
    global _NOTION_LAST_ERROR
    _NOTION_LAST_ERROR = NotionError(type=error_type, message=message)
    if tb:
        _NOTION_LAST_ERROR["traceback"] = tb


def _clear_notion_error() -> None:
    """Clear the global Notion error."""
    global _NOTION_LAST_ERROR
    _NOTION_LAST_ERROR = None


def get_notion_last_error() -> Optional[NotionError]:
    """Get the last Notion error."""
    return _NOTION_LAST_ERROR


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_notion_event(
    action: str,
    ok: bool,
    items_count: int = 0,
    error_message: str = "",
) -> None:
    """Log a Notion operation to log.ndjson."""
    from ..config import LOG_FILE
    
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    event: dict = {
        "ts": now_iso(),
        "type": "notion",
        "action": action,
        "ok": ok,
    }
    if items_count:
        event["items_count"] = items_count
    if error_message:
        event["error"] = error_message[:200]
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Don't fail on log errors


# ---------------------------------------------------------------------------
# Notion API Client
# ---------------------------------------------------------------------------

NOTION_API_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"


def _get_headers() -> dict[str, str]:
    """Get Notion API headers."""
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def check_notion_available() -> bool:
    """Check if Notion integration is available and configured."""
    if not REQUESTS_AVAILABLE:
        _set_notion_error("missing_requests", "requests library not installed")
        return False
    if not NOTION_TOKEN:
        _set_notion_error("missing_token", "NOTION_TOKEN not configured")
        return False
    if not NOTION_WORK_DB_ID:
        _set_notion_error("missing_db_id", "NOTION_WORK_DB_ID not configured")
        return False
    _clear_notion_error()
    return True


def get_notion_status() -> dict[str, Any]:
    """Get Notion integration status."""
    return {
        "available": check_notion_available(),
        "requests_installed": REQUESTS_AVAILABLE,
        "token_configured": bool(NOTION_TOKEN),
        "db_id_configured": bool(NOTION_WORK_DB_ID),
        "last_error": _NOTION_LAST_ERROR,
    }


# ---------------------------------------------------------------------------
# Database Schema Discovery
# ---------------------------------------------------------------------------

def get_database_schema() -> dict[str, Any]:
    """
    Retrieve database schema to discover property names and types.
    
    Returns:
        Dictionary with property names as keys and their types/options as values.
    """
    if not check_notion_available():
        return {"ok": False, "error": get_notion_last_error()}
    
    url = f"{NOTION_API_BASE}/databases/{NOTION_WORK_DB_ID}"
    
    try:
        response = requests.get(url, headers=_get_headers(), timeout=10)
        
        if response.status_code != 200:
            error_data = response.json()
            _set_notion_error(
                "api_error",
                f"Failed to get database schema: {error_data.get('message', response.status_code)}"
            )
            return {"ok": False, "error": get_notion_last_error()}
        
        data = response.json()
        properties = data.get("properties", {})
        
        schema = {}
        for prop_name, prop_info in properties.items():
            prop_type = prop_info.get("type", "unknown")
            schema[prop_name] = {
                "type": prop_type,
                "id": prop_info.get("id", ""),
            }
            
            # Include select options if available
            if prop_type == "select" and "select" in prop_info:
                options = prop_info["select"].get("options", [])
                schema[prop_name]["options"] = [opt.get("name", "") for opt in options]
            elif prop_type == "multi_select" and "multi_select" in prop_info:
                options = prop_info["multi_select"].get("options", [])
                schema[prop_name]["options"] = [opt.get("name", "") for opt in options]
            elif prop_type == "status" and "status" in prop_info:
                # Status properties have options nested under status.options
                options = prop_info["status"].get("options", [])
                schema[prop_name]["options"] = [opt.get("name", "") for opt in options]
        
        _clear_notion_error()
        return {"ok": True, "schema": schema, "title": data.get("title", [{}])[0].get("plain_text", "")}
    
    except requests.exceptions.RequestException as e:
        _set_notion_error("network_error", f"Network error: {str(e)}")
        return {"ok": False, "error": get_notion_last_error()}
    except Exception as e:
        _set_notion_error("unknown", f"Unknown error: {str(e)}", traceback.format_exc())
        return {"ok": False, "error": get_notion_last_error()}


# ---------------------------------------------------------------------------
# Property Value Extraction
# ---------------------------------------------------------------------------

def _extract_title(prop: dict) -> str:
    """Extract text from a title property."""
    title_arr = prop.get("title", [])
    if title_arr:
        return "".join(t.get("plain_text", "") for t in title_arr)
    return ""


def _extract_select(prop: dict) -> Optional[str]:
    """Extract value from a select property."""
    select = prop.get("select")
    if select:
        return select.get("name")
    return None


def _extract_text(prop: dict) -> Optional[str]:
    """Extract text from a rich_text property."""
    rich_text = prop.get("rich_text", [])
    if rich_text:
        return "".join(t.get("plain_text", "") for t in rich_text)
    return None


def _extract_date(prop: dict) -> Optional[str]:
    """Extract date string from a date property."""
    date_obj = prop.get("date")
    if date_obj:
        return date_obj.get("start")  # ISO format
    return None


def _extract_property_value(prop: dict) -> Optional[str]:
    """Extract value from any property type."""
    prop_type = prop.get("type", "")
    
    if prop_type == "title":
        return _extract_title(prop)
    elif prop_type == "select":
        return _extract_select(prop)
    elif prop_type == "multi_select":
        # Return first item from multi_select
        ms_items = prop.get("multi_select", [])
        if ms_items:
            return ms_items[0].get("name")
        return None
    elif prop_type == "rich_text":
        return _extract_text(prop)
    elif prop_type == "date":
        return _extract_date(prop)
    elif prop_type == "number":
        return str(prop.get("number", "")) if prop.get("number") is not None else None
    elif prop_type == "checkbox":
        return "Yes" if prop.get("checkbox") else "No"
    elif prop_type == "status":
        status = prop.get("status")
        if status:
            return status.get("name")
    
    return None


# ---------------------------------------------------------------------------
# Query Building
# ---------------------------------------------------------------------------

def _build_notion_filter(filters: WorkQueryFilters, schema: dict) -> Optional[dict]:
    """
    Build Notion API filter from WorkQueryFilters.
    
    Args:
        filters: User-provided filters
        schema: Database schema with property types
        
    Returns:
        Notion filter object or None if no filters
    """
    conditions = []
    
    # Get actual property names from schema
    status_prop = NOTION_WORK_PROPERTY_MAP.get("status", "Status")
    project_prop = NOTION_WORK_PROPERTY_MAP.get("project", "Project")
    load_prop = NOTION_WORK_PROPERTY_MAP.get("load", "Load")
    due_prop = NOTION_WORK_PROPERTY_MAP.get("due", "Due")
    
    # Status filter (OR of multiple values)
    status_values = filters.get("status", NOTION_WORK_ACTIVE_STATUSES)
    if status_values and status_prop in schema:
        prop_type = schema[status_prop].get("type", "select")
        status_conditions = []
        
        for status_val in status_values:
            if prop_type == "status":
                status_conditions.append({
                    "property": status_prop,
                    "status": {"equals": status_val}
                })
            else:  # select
                status_conditions.append({
                    "property": status_prop,
                    "select": {"equals": status_val}
                })
        
        if len(status_conditions) == 1:
            conditions.append(status_conditions[0])
        elif len(status_conditions) > 1:
            conditions.append({"or": status_conditions})
    
    # Project filter (Proyecto is multi_select in real schema)
    project_val = filters.get("project")
    if project_val and project_prop in schema:
        prop_type = schema[project_prop].get("type", "select")
        
        if prop_type == "multi_select":
            conditions.append({
                "property": project_prop,
                "multi_select": {"contains": project_val}
            })
        elif prop_type == "select":
            conditions.append({
                "property": project_prop,
                "select": {"equals": project_val}
            })
        elif prop_type == "rich_text":
            conditions.append({
                "property": project_prop,
                "rich_text": {"contains": project_val}
            })
    
    # Domain filter (Domain is select in real schema)
    domain_prop = NOTION_WORK_PROPERTY_MAP.get("domain", "Domain")
    domain_val = filters.get("domain")
    if domain_val and domain_prop in schema:
        prop_type = schema[domain_prop].get("type", "select")
        
        if prop_type == "multi_select":
            conditions.append({
                "property": domain_prop,
                "multi_select": {"contains": domain_val}
            })
        elif prop_type == "select":
            conditions.append({
                "property": domain_prop,
                "select": {"equals": domain_val}
            })
    
    # Load filter
    load_val = filters.get("load")
    if load_val and load_prop in schema:
        prop_type = schema[load_prop].get("type", "select")
        
        if prop_type == "select":
            conditions.append({
                "property": load_prop,
                "select": {"equals": load_val}
            })
    
    # Date range filter
    date_range = filters.get("date_range")
    if date_range and due_prop in schema:
        if "from" in date_range:
            conditions.append({
                "property": due_prop,
                "date": {"on_or_after": date_range["from"]}
            })
        if "to" in date_range:
            conditions.append({
                "property": due_prop,
                "date": {"on_or_before": date_range["to"]}
            })
    
    # Combine all conditions with AND
    if not conditions:
        return None
    elif len(conditions) == 1:
        return conditions[0]
    else:
        return {"and": conditions}


def _build_notion_sorts(sort: Optional[list[dict[str, str]]], schema: dict) -> list[dict]:
    """
    Build Notion API sorts from user sort specification.
    
    Args:
        sort: User-provided sort list [{"field": "due", "dir": "asc"}]
        schema: Database schema
        
    Returns:
        Notion sorts array
    """
    notion_sorts = []
    due_prop = NOTION_WORK_PROPERTY_MAP.get("due", "Due")
    
    if sort:
        for s in sort:
            field = s.get("field", "")
            direction = "ascending" if s.get("dir", "asc") == "asc" else "descending"
            
            # Map internal field names to Notion property names
            prop_name = NOTION_WORK_PROPERTY_MAP.get(field, field)
            
            if prop_name in schema:
                notion_sorts.append({
                    "property": prop_name,
                    "direction": direction
                })
    
    # Default sort: due ascending, then last_edited_time descending
    if not notion_sorts:
        if due_prop in schema:
            notion_sorts.append({
                "property": due_prop,
                "direction": "ascending"
            })
        notion_sorts.append({
            "timestamp": "last_edited_time",
            "direction": "descending"
        })
    
    return notion_sorts


# ---------------------------------------------------------------------------
# Page Parsing
# ---------------------------------------------------------------------------

def _find_property(properties: dict, target: str) -> tuple[str, dict]:
    """
    Find property by name, ignoring trailing/leading whitespace.
    
    Args:
        properties: Dict of property_name -> property_value
        target: Target property name (normalized)
    
    Returns:
        (actual_key, property_value) or ("", {}) if not found
    """
    target_normalized = target.strip().lower()
    for key, value in properties.items():
        if key.strip().lower() == target_normalized:
            return key, value
    return "", {}


def _parse_page_to_work_item(page: dict, schema: dict) -> WorkItem:
    """
    Parse a Notion page into a WorkItem.
    
    Args:
        page: Notion page object from query results
        schema: Database schema for property type lookup
        
    Returns:
        WorkItem with extracted values
    """
    properties = page.get("properties", {})
    
    # Map internal names to schema property names (with whitespace-tolerant lookup)
    _, title_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("title", "Name"))
    _, status_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("status", "Status"))
    _, project_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("project", "Project"))
    _, load_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("load", "Load"))
    _, impact_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("impact", "Impact"))
    _, due_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("due", "Due"))
    _, next_action_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("next_action", "Next Action"))
    
    return WorkItem(
        notion_page_id=page.get("id", ""),
        title=_extract_title(title_val),
        status=_extract_property_value(status_val) or None,
        project=_extract_property_value(project_val) or None,
        load=_extract_property_value(load_val) or None,
        impact=_extract_property_value(impact_val) or None,
        due=_extract_date(due_val) or None,
        next_action=_extract_text(next_action_val) or None,
        last_edited_time=page.get("last_edited_time", ""),
    )


# ---------------------------------------------------------------------------
# Main Query Function
# ---------------------------------------------------------------------------

def query_work_db(
    filters: Optional[WorkQueryFilters] = None,
    limit: int = 20,
    sort: Optional[list[dict[str, str]]] = None,
) -> WorkQueryResult:
    """
    Query WORK database from Notion (read-only).
    
    Args:
        filters: Query filters (status, project, load, date_range)
        limit: Maximum items to return (default 20)
        sort: Sort specification [{"field": "due", "dir": "asc"}]
        
    Returns:
        WorkQueryResult with items or error
    """
    if not check_notion_available():
        error = get_notion_last_error()
        _log_notion_event("query", ok=False, error_message=error.get("message", "") if error else "Unknown")
        return WorkQueryResult(ok=False, items=[], total=0, error=error.get("message", "") if error else "Notion not available")
    
    # Get database schema first
    schema_result = get_database_schema()
    if not schema_result.get("ok"):
        error = schema_result.get("error", {})
        _log_notion_event("query", ok=False, error_message=error.get("message", "") if isinstance(error, dict) else str(error))
        return WorkQueryResult(ok=False, items=[], total=0, error=error.get("message", "") if isinstance(error, dict) else str(error))
    
    schema = schema_result.get("schema", {})
    
    # Build query body
    query_body: dict[str, Any] = {"page_size": min(limit, 100)}  # Notion max is 100
    
    # Build filter
    filters = filters or {}
    notion_filter = _build_notion_filter(filters, schema)
    if notion_filter:
        query_body["filter"] = notion_filter
    
    # Build sorts
    notion_sorts = _build_notion_sorts(sort, schema)
    if notion_sorts:
        query_body["sorts"] = notion_sorts
    
    url = f"{NOTION_API_BASE}/databases/{NOTION_WORK_DB_ID}/query"
    
    try:
        response = requests.post(
            url,
            headers=_get_headers(),
            json=query_body,
            timeout=15
        )
        
        if response.status_code != 200:
            error_data = response.json()
            error_msg = f"Query failed: {error_data.get('message', response.status_code)}"
            _set_notion_error("api_error", error_msg)
            _log_notion_event("query", ok=False, error_message=error_msg)
            return WorkQueryResult(ok=False, items=[], total=0, error=error_msg)
        
        data = response.json()
        results = data.get("results", [])
        
        # Parse pages to WorkItems
        items = [_parse_page_to_work_item(page, schema) for page in results]
        
        _clear_notion_error()
        _log_notion_event("query", ok=True, items_count=len(items))
        
        return WorkQueryResult(
            ok=True,
            items=items,
            total=len(items),  # Note: This is results returned, not total in DB
            error=""
        )
    
    except requests.exceptions.Timeout:
        _set_notion_error("timeout", "Notion API request timed out")
        _log_notion_event("query", ok=False, error_message="timeout")
        return WorkQueryResult(ok=False, items=[], total=0, error="Request timed out")
    
    except requests.exceptions.RequestException as e:
        _set_notion_error("network_error", f"Network error: {str(e)}")
        _log_notion_event("query", ok=False, error_message=str(e))
        return WorkQueryResult(ok=False, items=[], total=0, error=f"Network error: {str(e)}")
    
    except Exception as e:
        _set_notion_error("unknown", f"Unknown error: {str(e)}", traceback.format_exc())
        _log_notion_event("query", ok=False, error_message=str(e))
        return WorkQueryResult(ok=False, items=[], total=0, error=f"Error: {str(e)}")


# ---------------------------------------------------------------------------
# Response Formatter
# ---------------------------------------------------------------------------

def format_work_query_response(result: WorkQueryResult) -> str:
    """
    Format WorkQueryResult into a human-readable response.
    
    Shows:
    - Summary with totals and status counts
    - Next 3 due dates
    - Top 5 items with details
    
    Args:
        result: Query result from query_work_db
        
    Returns:
        Formatted string for chat response
    """
    if not result["ok"]:
        return f"❌ Error consultando tareas: {result['error']}"
    
    items = result["items"]
    total = result["total"]
    
    if not items:
        return "No encontré tareas que coincidan con esos filtros."
    
    lines = []
    
    # --- Summary ---
    lines.append(f"📋 **{total} tarea(s) encontrada(s)**")
    
    # Count by status
    status_counts: dict[str, int] = {}
    for item in items:
        status = item.get("status") or "Sin estado"
        status_counts[status] = status_counts.get(status, 0) + 1
    
    status_parts = [f"{status}: {count}" for status, count in status_counts.items()]
    if status_parts:
        lines.append(f"Estados: {', '.join(status_parts)}")
    
    # Next 3 due dates
    items_with_due = [i for i in items if i.get("due")]
    items_with_due.sort(key=lambda x: x.get("due", "") or "9999")
    
    if items_with_due:
        lines.append("")
        lines.append("📅 **Próximos vencimientos:**")
        for item in items_with_due[:3]:
            due = item.get("due", "")
            title = item.get("title", "Sin título")[:40]
            lines.append(f"  • {due}: {title}")
    
    # --- Top 5 List ---
    lines.append("")
    showing = min(5, len(items))
    if total > showing:
        lines.append(f"**Top {showing} de {total}:**")
    else:
        lines.append(f"**Tareas:**")
    
    for item in items[:5]:
        status = item.get("status") or "?"
        due = item.get("due") or ""
        title = item.get("title") or "Sin título"
        project = item.get("project") or ""
        load = item.get("load") or ""
        next_action = item.get("next_action")
        
        # Format: [Status] (Due) Title — Project — Load
        parts = [f"[{status}]"]
        if due:
            parts.append(f"({due})")
        parts.append(title[:50])
        if project:
            parts.append(f"— {project}")
        if load:
            parts.append(f"— {load}")
        
        lines.append(f"  {' '.join(parts)}")
        
        if next_action:
            lines.append(f"    → {next_action[:60]}")
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Create Work Item (Write Operation)
# ---------------------------------------------------------------------------

class WorkCreateRequest(TypedDict, total=False):
    """Request structure for creating a work item."""
    title: str                      # Required: Task title
    project: Optional[str]          # Optional: Project name (multi-select)
    status: Optional[str]           # Optional: Status (default: INBOX)
    load: Optional[str]             # Optional: Carga (Alta/Media/Baja)
    due: Optional[str]              # Optional: Due date (ISO format YYYY-MM-DD)
    notes: Optional[str]            # Optional: Notes for page content


class WorkCreateResult(TypedDict):
    """Result from create work item operation."""
    ok: bool
    page_id: str                    # Notion page ID if created
    url: str                        # Notion page URL if created
    title: str                      # Title of created task
    error: str                      # Error message if failed


def create_work_item(request: WorkCreateRequest) -> WorkCreateResult:
    """
    Create a new work item (task) in Notion.
    
    Args:
        request: WorkCreateRequest with task fields
        
    Returns:
        WorkCreateResult with page_id/url on success, error on failure
    """
    if not check_notion_available():
        error = get_notion_last_error()
        _log_notion_event("create", ok=False, error_message=error.get("message", "") if error else "Unknown")
        return WorkCreateResult(
            ok=False, page_id="", url="", title="",
            error=error.get("message", "") if error else "Notion not available"
        )
    
    title = request.get("title", "").strip()
    if not title:
        _log_notion_event("create", ok=False, error_message="Title is required")
        return WorkCreateResult(ok=False, page_id="", url="", title="", error="Title is required")
    
    # Build properties for Notion page
    properties: dict[str, Any] = {}
    
    # Title property (required)
    title_prop = NOTION_WORK_PROPERTY_MAP.get("title", "Name")
    properties[title_prop] = {
        "title": [{"text": {"content": title}}]
    }
    
    # Status property (select)
    status = request.get("status", "INBOX")
    if status:
        status_prop = NOTION_WORK_PROPERTY_MAP.get("status", "Status")
        properties[status_prop] = {
            "status": {"name": status}
        }
    
    # Project property (multi-select)
    project = request.get("project")
    if project:
        project_prop = NOTION_WORK_PROPERTY_MAP.get("project", "Proyecto")
        properties[project_prop] = {
            "multi_select": [{"name": project}]
        }
    
    # Load/Carga property (select)
    load = request.get("load")
    if load:
        load_prop = NOTION_WORK_PROPERTY_MAP.get("load", "Carga")
        properties[load_prop] = {
            "select": {"name": load}
        }
    
    # Due date property (date)
    due = request.get("due")
    if due:
        due_prop = NOTION_WORK_PROPERTY_MAP.get("due", "Entrega")
        properties[due_prop] = {
            "date": {"start": due}
        }
    
    # Build page body
    page_body: dict[str, Any] = {
        "parent": {"database_id": NOTION_WORK_DB_ID},
        "properties": properties,
    }
    
    # Add notes as page content if provided
    notes = request.get("notes")
    if notes:
        page_body["children"] = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": notes}}]
                }
            }
        ]
    
    url = f"{NOTION_API_BASE}/pages"
    
    try:
        response = requests.post(
            url,
            headers=_get_headers(),
            json=page_body,
            timeout=15
        )
        
        if response.status_code not in (200, 201):
            error_data = response.json()
            error_msg = f"Create failed: {error_data.get('message', response.status_code)}"
            _set_notion_error("api_error", error_msg)
            _log_notion_event("create", ok=False, error_message=error_msg)
            return WorkCreateResult(ok=False, page_id="", url="", title=title, error=error_msg)
        
        data = response.json()
        page_id = data.get("id", "")
        page_url = data.get("url", "")
        
        _clear_notion_error()
        _log_notion_event("create", ok=True)
        
        return WorkCreateResult(
            ok=True,
            page_id=page_id,
            url=page_url,
            title=title,
            error=""
        )
    
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error: {str(e)}"
        _set_notion_error("network_error", error_msg)
        _log_notion_event("create", ok=False, error_message=error_msg)
        return WorkCreateResult(ok=False, page_id="", url="", title=title, error=error_msg)
    except Exception as e:
        error_msg = f"Unknown error: {str(e)}"
        _set_notion_error("unknown", error_msg, traceback.format_exc())
        _log_notion_event("create", ok=False, error_message=error_msg)
        return WorkCreateResult(ok=False, page_id="", url="", title=title, error=error_msg)


# ---------------------------------------------------------------------------
# Delete/Archive Operations
# ---------------------------------------------------------------------------

def query_work_items_by_keywords(
    db_id: str,
    keywords: list[str],
    op: str = "OR",
    limit: int = 100,
) -> list[dict]:
    """
    Query work items by keywords in title.
    
    Args:
        db_id: Database ID to query
        keywords: List of keywords to search for
        op: "OR" or "AND" - how to combine keywords
        limit: Maximum number of results (default 100)
    
    Returns:
        List of matching items with id and title
    """
    if not REQUESTS_AVAILABLE or not NOTION_TOKEN:
        return []
    
    # Build filter for keywords
    keyword_filters = []
    for kw in keywords:
        keyword_filters.append({
            "property": "Name",
            "title": {
                "contains": kw
            }
        })
    
    # Combine filters based on operator
    if len(keyword_filters) == 0:
        filter_body = {}
    elif len(keyword_filters) == 1:
        filter_body = {"filter": keyword_filters[0]}
    elif op.upper() == "AND":
        filter_body = {"filter": {"and": keyword_filters}}
    else:
        filter_body = {"filter": {"or": keyword_filters}}
    
    filter_body["page_size"] = min(limit, 100)
    
    try:
        url = f"{NOTION_API_BASE}/databases/{db_id}/query"
        response = requests.post(url, headers=_get_headers(), json=filter_body)
        
        if response.status_code != 200:
            return []
        
        data = response.json()
        results = []
        
        for page in data.get("results", []):
            page_id = page.get("id", "")
            # Extract title from Name property
            name_prop = page.get("properties", {}).get("Name", {})
            title_data = name_prop.get("title", [])
            title = title_data[0].get("plain_text", "") if title_data else ""
            
            results.append({
                "id": page_id,
                "title": title,
            })
        
        return results
    
    except Exception:
        return []


def archive_pages(page_ids: list[str]) -> int:
    """
    Archive multiple pages in Notion.
    
    Args:
        page_ids: List of page IDs to archive
    
    Returns:
        Number of successfully archived pages
    """
    if not REQUESTS_AVAILABLE or not NOTION_TOKEN:
        return 0
    
    archived_count = 0
    
    for page_id in page_ids:
        try:
            url = f"{NOTION_API_BASE}/pages/{page_id}"
            response = requests.patch(
                url,
                headers=_get_headers(),
                json={"archived": True}
            )
            
            if response.status_code == 200:
                archived_count += 1
        except Exception:
            continue
    
    return archived_count


def move_pages_to_db(
    page_ids: list[str],
    target_db_id: str,
) -> int:
    """
    Move pages to a different database (copy + archive original).
    
    Note: Notion API doesn't support true "move", so we:
    1. Get page properties
    2. Create new page in target DB
    3. Archive original page
    
    Args:
        page_ids: List of page IDs to move
        target_db_id: ID of the target database
    
    Returns:
        Number of successfully moved pages
    """
    if not REQUESTS_AVAILABLE or not NOTION_TOKEN:
        return 0
    
    moved_count = 0
    
    for page_id in page_ids:
        try:
            # 1. Get original page
            get_url = f"{NOTION_API_BASE}/pages/{page_id}"
            get_response = requests.get(get_url, headers=_get_headers())
            
            if get_response.status_code != 200:
                continue
            
            page_data = get_response.json()
            properties = page_data.get("properties", {})
            
            # 2. Create in target DB (simplified - just copy Name)
            name_prop = properties.get("Name", {})
            create_body = {
                "parent": {"database_id": target_db_id},
                "properties": {
                    "Name": name_prop
                }
            }
            
            create_url = f"{NOTION_API_BASE}/pages"
            create_response = requests.post(
                create_url,
                headers=_get_headers(),
                json=create_body
            )
            
            if create_response.status_code not in (200, 201):
                continue
            
            # 3. Archive original
            archive_url = f"{NOTION_API_BASE}/pages/{page_id}"
            requests.patch(
                archive_url,
                headers=_get_headers(),
                json={"archived": True}
            )
            
            moved_count += 1
        except Exception:
            continue
    
    return moved_count


# ---------------------------------------------------------------------------
# Work Update Support (WORK_UPDATE Phase 1)
# ---------------------------------------------------------------------------

class WorkItemFull(TypedDict, total=False):
    """Full work item with all editable fields."""
    notion_page_id: str
    title: str
    status: Optional[str]
    project: Optional[str]
    domain: Optional[str]
    load: Optional[str]
    impact: Optional[str]
    due: Optional[str]
    next_action: Optional[str]
    last_edited_time: str
    url: str


class FieldOptions(TypedDict, total=False):
    """Options for select/multi-select fields from Notion schema."""
    status: list[str]
    project: list[str]
    domain: list[str]
    load: list[str]
    impact: list[str]


class WorkItemWithOptions(TypedDict):
    """Work item with field options for UI."""
    ok: bool
    item: Optional[WorkItemFull]
    options: FieldOptions
    error: str


def get_work_item_by_id(page_id: str) -> WorkItemWithOptions:
    """
    Get a single work item by Notion page ID with field options.
    
    Args:
        page_id: Notion page ID
        
    Returns:
        WorkItemWithOptions with item data and available field options
    """
    if not check_notion_available():
        error = get_notion_last_error()
        return WorkItemWithOptions(
            ok=False,
            item=None,
            options=FieldOptions(),
            error=error.get("message", "") if error else "Notion not available"
        )
    
    # Get database schema for options
    schema_result = get_database_schema()
    if not schema_result.get("ok"):
        return WorkItemWithOptions(
            ok=False,
            item=None,
            options=FieldOptions(),
            error=schema_result.get("error", {}).get("message", "Failed to get schema")
        )
    
    schema = schema_result.get("schema", {})
    
    # Get the page
    url = f"{NOTION_API_BASE}/pages/{page_id}"
    
    try:
        response = requests.get(url, headers=_get_headers(), timeout=10)
        
        if response.status_code != 200:
            error_data = response.json()
            return WorkItemWithOptions(
                ok=False,
                item=None,
                options=FieldOptions(),
                error=f"Failed to get page: {error_data.get('message', response.status_code)}"
            )
        
        page = response.json()
        properties = page.get("properties", {})
        
        # Extract field values using property map
        _, title_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("title", "Name"))
        _, status_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("status", "Status"))
        _, project_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("project", "Proyecto"))
        _, domain_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("domain", "Domain"))
        _, load_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("load", "Carga"))
        _, impact_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("impact", "Impact"))
        _, due_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("due", "Entrega"))
        _, next_action_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("next_action", "Next Action"))
        
        # Extract project from select or multi-select
        project_extracted = None
        if project_val:
            project_type = project_val.get("type", "")
            if project_type == "multi_select":
                ms_items = project_val.get("multi_select", [])
                if ms_items:
                    project_extracted = ms_items[0].get("name")
            elif project_type == "select":
                select_val = project_val.get("select")
                if select_val:
                    project_extracted = select_val.get("name")
        
        # Extract domain from select or multi-select (symmetric with project)
        domain_extracted = None
        if domain_val:
            domain_type = domain_val.get("type", "")
            if domain_type == "multi_select":
                ms_items = domain_val.get("multi_select", [])
                if ms_items:
                    domain_extracted = ms_items[0].get("name")
            elif domain_type == "select":
                select_val = domain_val.get("select")
                if select_val:
                    domain_extracted = select_val.get("name")
        
        item = WorkItemFull(
            notion_page_id=page.get("id", ""),
            title=_extract_title(title_val),
            status=_extract_property_value(status_val),
            project=project_extracted,
            domain=domain_extracted,
            load=_extract_property_value(load_val),
            impact=_extract_property_value(impact_val),
            due=_extract_date(due_val),
            next_action=_extract_text(next_action_val),
            last_edited_time=page.get("last_edited_time", ""),
            url=page.get("url", ""),
        )
        
        # Extract field options from schema
        options = _extract_field_options(schema)
        
        _clear_notion_error()
        return WorkItemWithOptions(
            ok=True,
            item=item,
            options=options,
            error=""
        )
    
    except requests.exceptions.RequestException as e:
        return WorkItemWithOptions(
            ok=False,
            item=None,
            options=FieldOptions(),
            error=f"Network error: {str(e)}"
        )
    except Exception as e:
        return WorkItemWithOptions(
            ok=False,
            item=None,
            options=FieldOptions(),
            error=f"Error: {str(e)}"
        )


# ---------------------------------------------------------------------------
# Work Item Update
# ---------------------------------------------------------------------------

class WorkUpdateRequest(TypedDict, total=False):
    """Request to update a work item."""
    page_id: str                  # Required: Notion page ID
    status: Optional[str]         # New status value
    project: Optional[str]        # New project value
    domain: Optional[str]         # New domain value


class WorkUpdateResult(TypedDict):
    """Result of work item update."""
    ok: bool
    page_id: str
    changes_applied: list[dict]   # List of {field, from, to}
    error: str


def update_work_item(
    page_id: str,
    changes: dict[str, str],
    current_values: Optional[dict[str, str]] = None,
) -> WorkUpdateResult:
    """
    Update a work item in Notion.
    
    Args:
        page_id: Notion page ID to update
        changes: Dict of field -> new_value (only status, project, domain allowed)
        current_values: Optional current values for tracking changes
    
    Returns:
        WorkUpdateResult with success status and applied changes
    """
    if not check_notion_available():
        error = get_notion_last_error()
        return WorkUpdateResult(
            ok=False,
            page_id=page_id,
            changes_applied=[],
            error=error.get("message", "") if error else "Notion not available"
        )
    
    if not page_id:
        return WorkUpdateResult(
            ok=False,
            page_id="",
            changes_applied=[],
            error="page_id is required"
        )
    
    # Only allow specific fields
    allowed_fields = {"status", "project", "domain"}
    filtered_changes = {k: v for k, v in changes.items() if k in allowed_fields and v}
    
    if not filtered_changes:
        return WorkUpdateResult(
            ok=False,
            page_id=page_id,
            changes_applied=[],
            error="No valid changes provided"
        )
    
    # Get schema to determine correct property types
    schema_result = get_database_schema()
    if not schema_result.get("ok"):
        return WorkUpdateResult(
            ok=False,
            page_id=page_id,
            changes_applied=[],
            error="Failed to get database schema"
        )
    
    schema = schema_result.get("schema", {})
    
    # Build properties for Notion PATCH based on actual schema types
    properties: dict[str, Any] = {}
    
    for field, new_value in filtered_changes.items():
        if field == "status":
            # Status property - check if it's status type or select
            status_prop = NOTION_WORK_PROPERTY_MAP.get("status", "Status")
            prop_type = schema.get(status_prop, {}).get("type", "status")
            
            if prop_type == "status":
                properties[status_prop] = {"status": {"name": new_value}}
            else:  # select fallback
                properties[status_prop] = {"select": {"name": new_value}}
        
        elif field == "project":
            # Project property - check schema for select vs multi_select
            project_prop = NOTION_WORK_PROPERTY_MAP.get("project", "Proyecto")
            prop_type = schema.get(project_prop, {}).get("type", "multi_select")
            
            if prop_type == "multi_select":
                properties[project_prop] = {"multi_select": [{"name": new_value}]}
            else:  # select fallback
                properties[project_prop] = {"select": {"name": new_value}}
        
        elif field == "domain":
            # Domain property - check schema for select vs multi_select
            domain_prop = NOTION_WORK_PROPERTY_MAP.get("domain", "Domain")
            prop_type = schema.get(domain_prop, {}).get("type", "multi_select")
            
            if prop_type == "multi_select":
                properties[domain_prop] = {"multi_select": [{"name": new_value}]}
            else:  # select fallback
                properties[domain_prop] = {"select": {"name": new_value}}
    
    url = f"{NOTION_API_BASE}/pages/{page_id}"
    
    try:
        response = requests.patch(
            url,
            headers=_get_headers(),
            json={"properties": properties},
            timeout=15
        )
        
        if response.status_code != 200:
            error_data = response.json()
            error_msg = f"Update failed: {error_data.get('message', response.status_code)}"
            _set_notion_error("api_error", error_msg)
            _log_notion_event("update", ok=False, error_message=error_msg)
            return WorkUpdateResult(
                ok=False,
                page_id=page_id,
                changes_applied=[],
                error=error_msg
            )
        
        # Build changes_applied with from/to tracking
        changes_applied = []
        current = current_values or {}
        for field, new_value in filtered_changes.items():
            changes_applied.append({
                "field": field,
                "from": current.get(field),
                "to": new_value
            })
        
        _clear_notion_error()
        _log_notion_event("update", ok=True)
        
        return WorkUpdateResult(
            ok=True,
            page_id=page_id,
            changes_applied=changes_applied,
            error=""
        )
    
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error: {str(e)}"
        _set_notion_error("network_error", error_msg)
        return WorkUpdateResult(
            ok=False,
            page_id=page_id,
            changes_applied=[],
            error=error_msg
        )
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        return WorkUpdateResult(
            ok=False,
            page_id=page_id,
            changes_applied=[],
            error=error_msg
        )


def _extract_field_options(schema: dict) -> FieldOptions:
    """
    Extract available options for editable fields from database schema.
    
    Args:
        schema: Database schema from get_database_schema()
    
    Returns:
        FieldOptions with available values for each field
    """
    options = FieldOptions(
        status=[],
        project=[],
        domain=[],
        load=[],
        impact=[],
    )
    
    # Status
    status_prop = NOTION_WORK_PROPERTY_MAP.get("status", "Status")
    if status_prop in schema:
        prop_info = schema[status_prop]
        if "options" in prop_info:
            options["status"] = prop_info["options"]
    
    # Project
    project_prop = NOTION_WORK_PROPERTY_MAP.get("project", "Proyecto")
    if project_prop in schema:
        prop_info = schema[project_prop]
        if "options" in prop_info:
            options["project"] = prop_info["options"]
    
    # Domain
    domain_prop = NOTION_WORK_PROPERTY_MAP.get("domain", "Domain")
    if domain_prop in schema:
        prop_info = schema[domain_prop]
        if "options" in prop_info:
            options["domain"] = prop_info["options"]
    
    # Load/Carga
    load_prop = NOTION_WORK_PROPERTY_MAP.get("load", "Carga")
    if load_prop in schema:
        prop_info = schema[load_prop]
        if "options" in prop_info:
            options["load"] = prop_info["options"]
    
    # Impact
    impact_prop = NOTION_WORK_PROPERTY_MAP.get("impact", "Impact")
    if impact_prop in schema:
        prop_info = schema[impact_prop]
        if "options" in prop_info:
            options["impact"] = prop_info["options"]
    
    return options


def get_editable_field_options() -> dict[str, Any]:
    """
    Get available options for all editable fields.
    
    Returns:
        Dict with ok status and options for status, project, domain
    """
    if not check_notion_available():
        error = get_notion_last_error()
        return {
            "ok": False,
            "options": {},
            "error": error.get("message", "") if error else "Notion not available"
        }
    
    schema_result = get_database_schema()
    if not schema_result.get("ok"):
        return {
            "ok": False,
            "options": {},
            "error": schema_result.get("error", {}).get("message", "Failed to get schema")
        }
    
    schema = schema_result.get("schema", {})
    options = _extract_field_options(schema)
    
    return {
        "ok": True,
        "options": dict(options),
        "error": ""
    }


class SearchResult(TypedDict):
    """Result from work item search."""
    ok: bool
    items: list[WorkItemFull]
    total: int
    error: str


def search_work_items_by_title(
    keywords: list[str],
    op: str = "OR",
    limit: int = 10,
) -> SearchResult:
    """
    Search work items by title keywords.
    
    Args:
        keywords: List of keywords to search for in title
        op: "OR" or "AND" - how to combine keywords
        limit: Maximum results to return
        
    Returns:
        SearchResult with matching items
    """
    if not check_notion_available():
        error = get_notion_last_error()
        return SearchResult(
            ok=False,
            items=[],
            total=0,
            error=error.get("message", "") if error else "Notion not available"
        )
    
    if not keywords:
        return SearchResult(ok=True, items=[], total=0, error="")
    
    # Get schema for property names
    schema_result = get_database_schema()
    if not schema_result.get("ok"):
        return SearchResult(
            ok=False,
            items=[],
            total=0,
            error="Failed to get schema"
        )
    
    schema = schema_result.get("schema", {})
    title_prop = NOTION_WORK_PROPERTY_MAP.get("title", "Name")
    
    # Build filter for keywords
    keyword_filters = []
    for kw in keywords:
        keyword_filters.append({
            "property": title_prop,
            "title": {"contains": kw}
        })
    
    # Combine filters
    if len(keyword_filters) == 0:
        filter_body: dict = {}
    elif len(keyword_filters) == 1:
        filter_body = {"filter": keyword_filters[0]}
    elif op.upper() == "AND":
        filter_body = {"filter": {"and": keyword_filters}}
    else:
        filter_body = {"filter": {"or": keyword_filters}}
    
    filter_body["page_size"] = min(limit, 100)
    
    # Add sort by last_edited_time descending
    filter_body["sorts"] = [
        {"timestamp": "last_edited_time", "direction": "descending"}
    ]
    
    url = f"{NOTION_API_BASE}/databases/{NOTION_WORK_DB_ID}/query"
    
    try:
        response = requests.post(
            url,
            headers=_get_headers(),
            json=filter_body,
            timeout=15
        )
        
        if response.status_code != 200:
            error_data = response.json()
            return SearchResult(
                ok=False,
                items=[],
                total=0,
                error=f"Search failed: {error_data.get('message', response.status_code)}"
            )
        
        data = response.json()
        results = data.get("results", [])
        
        # Parse pages to WorkItemFull
        items: list[WorkItemFull] = []
        for page in results:
            properties = page.get("properties", {})
            
            _, title_val = _find_property(properties, title_prop)
            _, status_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("status", "Status"))
            _, project_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("project", "Proyecto"))
            _, domain_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("domain", "Domain"))
            _, load_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("load", "Carga"))
            
            # Extract project from multi-select
            project_extracted = None
            if project_val:
                project_type = project_val.get("type", "")
                if project_type == "multi_select":
                    ms_items = project_val.get("multi_select", [])
                    if ms_items:
                        project_extracted = ms_items[0].get("name")
                elif project_type == "select":
                    select_val = project_val.get("select")
                    if select_val:
                        project_extracted = select_val.get("name")
            
            items.append(WorkItemFull(
                notion_page_id=page.get("id", ""),
                title=_extract_title(title_val),
                status=_extract_property_value(status_val),
                project=project_extracted,
                domain=_extract_property_value(domain_val),
                load=_extract_property_value(load_val),
                last_edited_time=page.get("last_edited_time", ""),
                url=page.get("url", ""),
            ))
        
        return SearchResult(
            ok=True,
            items=items,
            total=len(items),
            error=""
        )
    
    except requests.exceptions.RequestException as e:
        return SearchResult(
            ok=False,
            items=[],
            total=0,
            error=f"Network error: {str(e)}"
        )
    except Exception as e:
        return SearchResult(
            ok=False,
            items=[],
            total=0,
            error=f"Error: {str(e)}"
        )


def search_work_items_with_filters(
    keywords: list[str] | None = None,
    project: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> SearchResult:
    """
    Search work items with keyword and property filters.
    
    Resolution priority (applied as AND filters):
    1. project - primary anchor for item resolution
    2. status - secondary filter
    3. domain - context filter (not primary identifier)
    4. keywords - title search (OR combined)
    
    Args:
        keywords: Optional list of keywords to search in title (OR combined)
        project: Optional project name to filter by
        domain: Optional domain name to filter by
        status: Optional status to filter by
        limit: Maximum results to return
        
    Returns:
        SearchResult with matching items
    """
    if not check_notion_available():
        error = get_notion_last_error()
        return SearchResult(
            ok=False,
            items=[],
            total=0,
            error=error.get("message", "") if error else "Notion not available"
        )
    
    # Get schema for property names
    schema_result = get_database_schema()
    if not schema_result.get("ok"):
        return SearchResult(
            ok=False,
            items=[],
            total=0,
            error="Failed to get schema"
        )
    
    schema = schema_result.get("schema", {})
    title_prop = NOTION_WORK_PROPERTY_MAP.get("title", "Name")
    status_prop = NOTION_WORK_PROPERTY_MAP.get("status", "Status")
    project_prop = NOTION_WORK_PROPERTY_MAP.get("project", "Proyecto")
    domain_prop = NOTION_WORK_PROPERTY_MAP.get("domain", "Domain")
    
    # Build compound filter with AND logic for structured filters
    and_filters: list[dict] = []
    
    # Project filter (primary anchor)
    if project:
        prop_type = schema.get(project_prop, {}).get("type", "multi_select")
        if prop_type == "multi_select":
            and_filters.append({
                "property": project_prop,
                "multi_select": {"contains": project}
            })
        else:
            and_filters.append({
                "property": project_prop,
                "select": {"equals": project}
            })
    
    # Status filter
    if status:
        prop_type = schema.get(status_prop, {}).get("type", "status")
        if prop_type == "status":
            and_filters.append({
                "property": status_prop,
                "status": {"equals": status}
            })
        else:
            and_filters.append({
                "property": status_prop,
                "select": {"equals": status}
            })
    
    # Domain filter (context, not primary) - schema-aware like project
    if domain:
        prop_type = schema.get(domain_prop, {}).get("type", "select")
        if prop_type == "multi_select":
            and_filters.append({
                "property": domain_prop,
                "multi_select": {"contains": domain}
            })
        else:
            and_filters.append({
                "property": domain_prop,
                "select": {"equals": domain}
            })
    
    # Keywords filter (OR combined within, AND with structured filters)
    if keywords:
        if len(keywords) == 1:
            keyword_filter = {
                "property": title_prop,
                "title": {"contains": keywords[0]}
            }
        else:
            keyword_filter = {
                "or": [
                    {"property": title_prop, "title": {"contains": kw}}
                    for kw in keywords
                ]
            }
        and_filters.append(keyword_filter)
    
    # Build final filter
    if not and_filters:
        # No filters - return empty to avoid fetching entire database
        return SearchResult(ok=True, items=[], total=0, error="")
    elif len(and_filters) == 1:
        filter_body: dict = {"filter": and_filters[0]}
    else:
        filter_body = {"filter": {"and": and_filters}}
    
    filter_body["page_size"] = min(limit, 100)
    filter_body["sorts"] = [
        {"timestamp": "last_edited_time", "direction": "descending"}
    ]
    
    url = f"{NOTION_API_BASE}/databases/{NOTION_WORK_DB_ID}/query"
    
    try:
        response = requests.post(
            url,
            headers=_get_headers(),
            json=filter_body,
            timeout=15
        )
        
        if response.status_code != 200:
            error_data = response.json()
            return SearchResult(
                ok=False,
                items=[],
                total=0,
                error=f"Search failed: {error_data.get('message', response.status_code)}"
            )
        
        data = response.json()
        results = data.get("results", [])
        
        # Parse pages to WorkItemFull
        items: list[WorkItemFull] = []
        for page in results:
            properties = page.get("properties", {})
            
            _, title_val = _find_property(properties, title_prop)
            _, status_val = _find_property(properties, status_prop)
            _, project_val = _find_property(properties, project_prop)
            _, domain_val = _find_property(properties, domain_prop)
            _, load_val = _find_property(properties, NOTION_WORK_PROPERTY_MAP.get("load", "Carga"))
            
            # Extract project from multi-select
            project_extracted = None
            if project_val:
                project_type = project_val.get("type", "")
                if project_type == "multi_select":
                    ms_items = project_val.get("multi_select", [])
                    if ms_items:
                        project_extracted = ms_items[0].get("name")
                elif project_type == "select":
                    select_val = project_val.get("select")
                    if select_val:
                        project_extracted = select_val.get("name")
            
            items.append(WorkItemFull(
                notion_page_id=page.get("id", ""),
                title=_extract_title(title_val),
                status=_extract_property_value(status_val),
                project=project_extracted,
                domain=_extract_property_value(domain_val),
                load=_extract_property_value(load_val),
                last_edited_time=page.get("last_edited_time", ""),
                url=page.get("url", ""),
            ))
        
        return SearchResult(
            ok=True,
            items=items,
            total=len(items),
            error=""
        )
    
    except requests.exceptions.RequestException as e:
        return SearchResult(
            ok=False,
            items=[],
            total=0,
            error=f"Network error: {str(e)}"
        )
    except Exception as e:
        return SearchResult(
            ok=False,
            items=[],
            total=0,
            error=f"Error: {str(e)}"
        )