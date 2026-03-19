"""
Schema operations for WORK database in Notion.

Provides Plan Always pattern for adding options to select/multi_select properties.
v0: add options only (no rename/delete/merge).

Allowed properties:
- Proyecto (select)
- Tags (multi_select)
- Domain (select)
- Priority Level (select)
- Carga (select)
- Status (select)
"""
import json
from typing import Any, Optional, TypedDict
from datetime import datetime

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
)
from ..contracts import now_iso
from .notion import (
    NOTION_API_BASE,
    NOTION_API_VERSION,
    _get_headers,
    check_notion_available,
    get_database_schema,
    get_notion_status,
)


# ---------------------------------------------------------------------------
# Type Definitions
# ---------------------------------------------------------------------------

class SchemaChange(TypedDict):
    """A single schema change to apply."""
    property: str
    property_type: str  # "select" or "multi_select"
    action: str         # "add_option" only for v0
    option: str         # option name to add


class SchemaPlanRequest(TypedDict, total=False):
    """Request for schema plan."""
    changes: list[dict[str, Any]]  # [{property: "Proyecto", add_options: ["THCyE"]}]


class SchemaPlanResponse(TypedDict):
    """Response from schema plan."""
    ok: bool
    needs_confirmation: bool
    action_plan: list[SchemaChange]
    skipped: list[dict[str, str]]  # options that already exist
    errors: list[str]
    message: str


class SchemaCommitResponse(TypedDict):
    """Response from schema commit."""
    ok: bool
    applied: list[SchemaChange]
    errors: list[str]
    message: str


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Properties that can be modified (select/multi_select only)
# Note: "Status" property in Notion uses special "status" type, not "select"
# Status modifications require different API handling, excluded from v0
ALLOWED_PROPERTIES: dict[str, str] = {
    "Proyecto": "select",
    "Tags": "multi_select",       # May not exist in all DBs
    "Etiquetas": "multi_select",  # Spanish variant
    "Domain": "select",
    "Priority Level": "select",
    "Carga": "select",
    # "Status": "status",  # Excluded from v0 - requires special handling
}

LOG_FILE = MEMORY_DIR / "schema_ops.ndjson"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_schema_event(
    action: str,
    ok: bool,
    changes: list[dict] = None,
    error: str = "",
) -> None:
    """Log schema operation event."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    event = {
        "ts": now_iso(),
        "type": "schema_ops",
        "action": action,
        "ok": ok,
    }
    if changes:
        event["changes"] = changes
    if error:
        event["error"] = error[:500]
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------

def _normalize_option(opt: str) -> str:
    """Normalize option for case-insensitive comparison."""
    return opt.strip().lower()


def _get_existing_options(schema: dict, prop_name: str) -> set[str]:
    """Get normalized existing options for a property."""
    prop_info = schema.get(prop_name, {})
    options = prop_info.get("options", [])
    return {_normalize_option(opt) for opt in options}


def _validate_property(prop_name: str, schema: dict) -> tuple[bool, str, str]:
    """
    Validate property exists and has correct type.
    
    Returns: (is_valid, prop_type, error_message)
    """
    if prop_name not in ALLOWED_PROPERTIES:
        return False, "", f"Property '{prop_name}' is not allowed for schema ops. Allowed: {list(ALLOWED_PROPERTIES.keys())}"
    
    if prop_name not in schema:
        return False, "", f"Property '{prop_name}' does not exist in database schema"
    
    expected_type = ALLOWED_PROPERTIES[prop_name]
    actual_type = schema[prop_name].get("type", "")
    
    if actual_type != expected_type:
        return False, actual_type, f"Property '{prop_name}' has type '{actual_type}', expected '{expected_type}'"
    
    return True, expected_type, ""


# ---------------------------------------------------------------------------
# Plan Generation
# ---------------------------------------------------------------------------

def generate_schema_plan(request: SchemaPlanRequest) -> SchemaPlanResponse:
    """
    Generate an action plan for schema changes.
    
    Request format:
    {
        "changes": [
            {"property": "Proyecto", "add_options": ["THCyE", "NewProject"]},
            {"property": "Tags", "add_options": ["davinci", "urgent"]}
        ]
    }
    
    Returns plan with needs_confirmation=true if there are valid changes.
    """
    # Check Notion availability
    if not check_notion_available():
        status = get_notion_status()
        error_msg = status.get("last_error", {}).get("message", "Notion not configured")
        return SchemaPlanResponse(
            ok=False,
            needs_confirmation=False,
            action_plan=[],
            skipped=[],
            errors=[error_msg],
            message=f"❌ Notion no disponible: {error_msg}"
        )
    
    # Get current schema
    schema_result = get_database_schema()
    if not schema_result.get("ok"):
        error = schema_result.get("error", {}).get("message", "Failed to get schema")
        return SchemaPlanResponse(
            ok=False,
            needs_confirmation=False,
            action_plan=[],
            skipped=[],
            errors=[error],
            message=f"❌ Error obteniendo schema: {error}"
        )
    
    schema = schema_result.get("schema", {})
    
    changes_input = request.get("changes", [])
    if not changes_input:
        return SchemaPlanResponse(
            ok=False,
            needs_confirmation=False,
            action_plan=[],
            skipped=[],
            errors=["No changes provided"],
            message="❌ No se proporcionaron cambios"
        )
    
    action_plan: list[SchemaChange] = []
    skipped: list[dict[str, str]] = []
    errors: list[str] = []
    
    for change in changes_input:
        prop_name = change.get("property", "")
        add_options = change.get("add_options", [])
        
        if not prop_name:
            errors.append("Missing 'property' in change")
            continue
        
        if not add_options:
            errors.append(f"No 'add_options' specified for property '{prop_name}'")
            continue
        
        # Validate property
        is_valid, prop_type, error = _validate_property(prop_name, schema)
        if not is_valid:
            errors.append(error)
            continue
        
        # Get existing options
        existing = _get_existing_options(schema, prop_name)
        
        for opt in add_options:
            opt_str = str(opt).strip()
            if not opt_str:
                errors.append(f"Empty option value for property '{prop_name}'")
                continue
            
            # Check if already exists (case-insensitive)
            if _normalize_option(opt_str) in existing:
                skipped.append({
                    "property": prop_name,
                    "option": opt_str,
                    "reason": "already_exists"
                })
            else:
                action_plan.append(SchemaChange(
                    property=prop_name,
                    property_type=prop_type,
                    action="add_option",
                    option=opt_str
                ))
    
    if errors and not action_plan:
        return SchemaPlanResponse(
            ok=False,
            needs_confirmation=False,
            action_plan=[],
            skipped=skipped,
            errors=errors,
            message=f"❌ Errores de validación: {'; '.join(errors)}"
        )
    
    if not action_plan:
        msg = "No hay cambios nuevos que aplicar"
        if skipped:
            msg += f" ({len(skipped)} opción(es) ya existen)"
        return SchemaPlanResponse(
            ok=True,
            needs_confirmation=False,
            action_plan=[],
            skipped=skipped,
            errors=errors,
            message=f"✓ {msg}"
        )
    
    # Build summary message
    summary_parts = []
    for change in action_plan:
        summary_parts.append(f"  + {change['property']}: \"{change['option']}\"")
    
    message = f"📋 **Plan de cambios ({len(action_plan)} adición(es)):**\n"
    message += "\n".join(summary_parts)
    if skipped:
        message += f"\n\n⏭️ {len(skipped)} opción(es) omitidas (ya existen)"
    if errors:
        message += f"\n\n⚠️ {len(errors)} advertencia(s)"
    message += "\n\n¿Confirmar cambios? Envía a /work/schema/commit con el mismo payload."
    
    _log_schema_event("plan", True, changes=[dict(c) for c in action_plan])
    
    return SchemaPlanResponse(
        ok=True,
        needs_confirmation=True,
        action_plan=action_plan,
        skipped=skipped,
        errors=errors,
        message=message
    )


# ---------------------------------------------------------------------------
# Commit Changes
# ---------------------------------------------------------------------------

def _update_database_property_options(
    prop_name: str,
    prop_type: str,
    new_options: list[str],
    existing_options: list[str],
) -> tuple[bool, str]:
    """
    Update database property to add new options.
    
    Uses PATCH /databases/{db_id} to update property options.
    
    Returns: (success, error_message)
    """
    if not REQUESTS_AVAILABLE:
        return False, "requests library not installed"
    
    # Merge existing + new options
    all_options = [{"name": opt} for opt in existing_options]
    for opt in new_options:
        all_options.append({"name": opt})
    
    # Build update payload
    if prop_type == "select":
        properties_update = {
            prop_name: {
                "select": {
                    "options": all_options
                }
            }
        }
    elif prop_type == "multi_select":
        properties_update = {
            prop_name: {
                "multi_select": {
                    "options": all_options
                }
            }
        }
    else:
        return False, f"Unsupported property type: {prop_type}"
    
    url = f"{NOTION_API_BASE}/databases/{NOTION_WORK_DB_ID}"
    payload = {"properties": properties_update}
    
    try:
        response = requests.patch(
            url,
            headers=_get_headers(),
            json=payload,
            timeout=15
        )
        
        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get("message", f"HTTP {response.status_code}")
            return False, f"Notion API error: {error_msg}"
        
        return True, ""
    
    except requests.exceptions.RequestException as e:
        return False, f"Network error: {str(e)}"
    except Exception as e:
        return False, f"Unknown error: {str(e)}"


def commit_schema_changes(request: SchemaPlanRequest) -> SchemaCommitResponse:
    """
    Apply schema changes to Notion database.
    
    Re-validates and applies changes atomically per property.
    """
    # First generate plan to validate
    plan_result = generate_schema_plan(request)
    
    if not plan_result["ok"]:
        return SchemaCommitResponse(
            ok=False,
            applied=[],
            errors=plan_result["errors"],
            message=plan_result["message"]
        )
    
    if not plan_result["needs_confirmation"]:
        return SchemaCommitResponse(
            ok=True,
            applied=[],
            errors=[],
            message=plan_result["message"]
        )
    
    action_plan = plan_result["action_plan"]
    
    # Get current schema for existing options
    schema_result = get_database_schema()
    if not schema_result.get("ok"):
        error = schema_result.get("error", {}).get("message", "Failed to get schema")
        return SchemaCommitResponse(
            ok=False,
            applied=[],
            errors=[f"Error refreshing schema: {error}"],
            message=f"❌ Error obteniendo schema: {error}"
        )
    
    schema = schema_result.get("schema", {})
    
    # Group changes by property
    changes_by_prop: dict[str, list[SchemaChange]] = {}
    for change in action_plan:
        prop = change["property"]
        if prop not in changes_by_prop:
            changes_by_prop[prop] = []
        changes_by_prop[prop].append(change)
    
    applied: list[SchemaChange] = []
    errors: list[str] = []
    
    # Apply changes per property
    for prop_name, changes in changes_by_prop.items():
        prop_info = schema.get(prop_name, {})
        prop_type = prop_info.get("type", "")
        existing_options = prop_info.get("options", [])
        new_options = [c["option"] for c in changes]
        
        success, error = _update_database_property_options(
            prop_name, prop_type, new_options, existing_options
        )
        
        if success:
            applied.extend(changes)
        else:
            errors.append(f"{prop_name}: {error}")
    
    # Log result
    _log_schema_event(
        "commit",
        ok=len(errors) == 0,
        changes=[dict(c) for c in applied],
        error="; ".join(errors) if errors else ""
    )
    
    if errors:
        if applied:
            message = f"⚠️ Cambios parciales: {len(applied)} aplicado(s), {len(errors)} error(es)"
        else:
            message = f"❌ Error aplicando cambios: {'; '.join(errors)}"
        return SchemaCommitResponse(
            ok=len(errors) == 0,
            applied=applied,
            errors=errors,
            message=message
        )
    
    # Build success message
    summary_parts = []
    for change in applied:
        summary_parts.append(f"  ✓ {change['property']}: \"{change['option']}\"")
    
    message = f"✅ **{len(applied)} cambio(s) aplicado(s):**\n"
    message += "\n".join(summary_parts)
    
    return SchemaCommitResponse(
        ok=True,
        applied=applied,
        errors=[],
        message=message
    )
