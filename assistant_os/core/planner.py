"""
Kernel — Planner Layer

Responsibility: translate a classified intent dict into a structured Plan,
applying deterministic routing overrides and parsing action-specific filters.

This module is the authoritative owner of:
  - Intent-to-action routing override logic (_apply_routing_overrides)
  - Intent detection helpers (_has_create_intent, _has_test_intent, etc.)
  - Plan construction from intent (_create_plan_from_intent)

It imports from the parsers layer (work_create_parser, work_delete_parser,
work_update_parser, work_mutation_parser) and from classifier for query
helpers.  It has zero HTTP dependencies.

Previous location: assistant_os/webhook_server.py (functions were defined
there as an artifact of early development, prior to kernel/HTTP separation).
Extracted in M0.7B.
"""
from __future__ import annotations

import re
from typing import Optional

from ..contracts import (
    Plan,
    make_plan,
    # Operation constants
    OP_WORK_UPDATE,
    OP_CODE_EXPLAIN,
    OP_CODE_REVIEW,
    OP_CODE_FIX,
    OP_CODE_CREATE,
    # Action constants
    ACTION_WORK_QUERY,
    ACTION_WORK_CREATE,
    ACTION_WORK_CREATE_TEST,
    ACTION_WORK_TEST_RESET,
    ACTION_WORK_UPDATE,
    ACTION_WORK_DELETE,
    ACTION_WORK_DELETE_TEST,
    ACTION_FIN_EXPENSE,
    ACTION_CODE_EXPLAIN,
    ACTION_CODE_REVIEW,
    ACTION_CODE_FIX,
    ACTION_CODE_CREATE,
    ACTION_COMMAND,
    # Risk levels
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
    # Target DBs
    TARGET_DB_WORK,
    TARGET_DB_WORK_TEST,
    TARGET_DB_WORK_TRASH,
    # Delete modes
    DELETE_MODE_TRASH,
    DELETE_MODE_ARCHIVE,
)
from ..classifier import is_work_query, parse_work_query_filters
from ..parsers.work_create_parser import parse_work_create_fields
from ..parsers.work_delete_parser import (
    has_delete_intent,
    parse_work_delete_intent,
    generate_delete_preview,
    DeleteQuery,
)
from ..parsers.work_update_parser import (
    parse_work_update_intent,
    generate_update_preview,
)


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
    for pattern in _TEST_INTENT_PATTERNS:
        if pattern.search(text):
            return True

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


# ---------------------------------------------------------------------------
# Title Validation
# ---------------------------------------------------------------------------

# Invalid title patterns — titles that are just keywords or punctuation
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
# Create Intent Detection
# ---------------------------------------------------------------------------

_WORK_CREATE_INTENT_PATTERN = re.compile(
    r"\b(crea|crear|añade|añadir|agrega|agregar|insertar?|registrar?|mete|meter|nueva?)\b"
    r".*\btareas?\b",
    re.IGNORECASE,
)

# Alternative: tarea + creation verb (reversed order)
_WORK_CREATE_INTENT_REVERSED_PATTERN = re.compile(
    r"\btareas?\b.*\b(crea|crear|añade|añadir|agrega|agregar|insertar?|registrar?|mete|meter|nueva?)\b",
    re.IGNORECASE,
)


def _has_create_intent(text: str) -> bool:
    """
    Detect if text expresses intent to CREATE a task (vs query tasks).

    Creation verbs: crea, crear, añade, agrega, insertar, registrar, mete, nueva
    Must be combined with "tarea(s)".

    Returns:
        True if creation intent detected
    """
    return bool(
        _WORK_CREATE_INTENT_PATTERN.search(text)
        or _WORK_CREATE_INTENT_REVERSED_PATTERN.search(text)
    )


# ---------------------------------------------------------------------------
# Routing Override Table
# ---------------------------------------------------------------------------

# Patterns for WORK_QUERY override (route to WORK_QUERY regardless of domain)
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
        return ("", "")

    for pattern in _WORK_QUERY_OVERRIDE_PATTERNS:
        if pattern.search(text):
            return (ACTION_WORK_QUERY, f"Override: pattern '{pattern.pattern}' matched")

    return ("", "")


# ---------------------------------------------------------------------------
# Plan Construction
# ---------------------------------------------------------------------------

def _create_plan_from_intent(text: str, intent: dict) -> Plan:
    """
    Create a Plan from classified intent (Planner layer).

    Translates the classified intent into a structured Plan without
    performing any execution (no side effects, no IO).

    This function is the authoritative kernel-layer implementation.
    It was previously defined in webhook_server.py and extracted here
    (M0.7B) to break the inverted Kernel→HTTP dependency.

    Args:
        text: Original user input
        intent: Classified intent from classify_text()

    Returns:
        Plan ready for confirmation or execution
    """
    domain = intent.get("domain", "UNKNOWN")
    operation = intent.get("operation", "COMMAND")
    confidence = intent.get("confidence", 0.0)
    alternatives = intent.get("alternatives", [])

    # Apply override rules first
    action_override, override_reason = _apply_routing_overrides(text, intent)

    if action_override:
        action = action_override
        reason = override_reason
    else:
        # Map operation to action (classifier-based routing)
        if operation == "WORK_QUERY":
            action = ACTION_WORK_QUERY
            reason = f"Classifier: operation={operation}"
        elif operation == "WORK_CREATE":
            action = ACTION_WORK_CREATE
            reason = f"Classifier: operation={operation}"
        elif operation == "WORK_UPDATE":
            action = ACTION_WORK_UPDATE
            reason = f"Classifier: operation={operation}"
        elif operation == "WORK_DELETE":
            action = ACTION_WORK_DELETE
            reason = f"Classifier: operation={operation}"
        elif operation == "FIN_EXPENSE":
            action = ACTION_FIN_EXPENSE
            reason = f"Classifier: operation={operation}"
        elif operation == OP_CODE_EXPLAIN:
            action = ACTION_CODE_EXPLAIN
            reason = f"Classifier: operation={operation}"
        elif operation == OP_CODE_REVIEW:
            action = ACTION_CODE_REVIEW
            reason = f"Classifier: operation={operation}"
        elif operation == OP_CODE_FIX:
            action = ACTION_CODE_FIX
            reason = f"Classifier: operation={operation}"
        elif operation == OP_CODE_CREATE:
            action = ACTION_CODE_CREATE
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
        risk_level = RISK_LOW
        requires_confirmation = False
        target_db = TARGET_DB_WORK
    elif action == ACTION_WORK_CREATE:
        risk_level = RISK_MEDIUM
        requires_confirmation = True  # ALWAYS require confirmation for writes
        target_db = TARGET_DB_WORK
    elif action == ACTION_WORK_CREATE_TEST:
        risk_level = RISK_MEDIUM
        requires_confirmation = True
        target_db = TARGET_DB_WORK_TEST
    elif action == ACTION_WORK_TEST_RESET:
        risk_level = RISK_HIGH
        requires_confirmation = True
        target_db = TARGET_DB_WORK_TEST
    elif action == ACTION_WORK_DELETE:
        risk_level = RISK_MEDIUM  # Default; may be upgraded to HIGH for delete_all
        requires_confirmation = True
        target_db = TARGET_DB_WORK_TRASH
    elif action == ACTION_WORK_DELETE_TEST:
        risk_level = RISK_MEDIUM  # Default; may be upgraded to HIGH for delete_all
        requires_confirmation = True
        target_db = TARGET_DB_WORK_TEST
    elif action == ACTION_WORK_UPDATE:
        risk_level = RISK_LOW   # Phase 1 is read-only (preview only)
        requires_confirmation = False  # Returns preview directly
        target_db = TARGET_DB_WORK
    elif action == ACTION_FIN_EXPENSE:
        risk_level = RISK_MEDIUM
        requires_confirmation = False  # Single expense auto-executes
    elif action == ACTION_CODE_EXPLAIN:
        risk_level = RISK_LOW
        requires_confirmation = False  # Read-only: auto-execute
    elif action == ACTION_CODE_REVIEW:
        risk_level = RISK_LOW
        requires_confirmation = False  # Read-only: auto-execute
    elif action == ACTION_CODE_FIX:
        risk_level = RISK_MEDIUM
        requires_confirmation = True   # Mutating: preview → confirm → apply
    elif action == ACTION_CODE_CREATE:
        risk_level = RISK_MEDIUM
        requires_confirmation = True   # Mutating: preview → confirm → apply
    else:
        risk_level = RISK_MEDIUM
        requires_confirmation = False

    # Parse filters based on action type
    filters = {}
    if action == ACTION_WORK_QUERY:
        filters = parse_work_query_filters(text)
    elif action == ACTION_WORK_CREATE:
        filters = parse_work_create_fields(text)
        title = filters.get("title", "").strip()
        if not title or _is_invalid_title(title):
            validation_error = "Missing or invalid title: Debes especificar un título para la tarea"
    elif action == ACTION_WORK_CREATE_TEST:
        filters = parse_work_create_fields(text)
        title = filters.get("title", "").strip()
        if not title or _is_invalid_title(title):
            validation_error = "Missing or invalid title: Debes especificar un título para la tarea de prueba"
    elif action in (ACTION_WORK_DELETE, ACTION_WORK_DELETE_TEST):
        from ..parsers.work_mutation_parser import (
            is_bulk_delete,
            parse_mutation_intent as _parse_mutation,
        )
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
        if filters.get("delete_all"):
            risk_level = RISK_HIGH
    elif action == ACTION_WORK_TEST_RESET:
        filters = {"delete_all": True, "delete_mode": DELETE_MODE_ARCHIVE}
    elif action == ACTION_WORK_UPDATE:
        from ..parsers.work_mutation_parser import (
            is_bulk_update,
            parse_mutation_intent as _parse_mutation,
        )
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
        preview = "Consultar tareas" + (f" ({', '.join(filter_desc)})" if filter_desc else "")
    elif action == ACTION_WORK_CREATE:
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
        title = filters.get("title", "(sin título)")
        preview = f"[TEST] Crear tarea: \"{title}\""
    elif action == ACTION_WORK_TEST_RESET:
        preview = "⚠️ Resetear TODAS las tareas de prueba (TEST DB)"
    elif action in (ACTION_WORK_DELETE, ACTION_WORK_DELETE_TEST):
        query = DeleteQuery(
            keywords=filters.get("keywords", []),
            op=filters.get("op", "OR"),
            delete_all=filters.get("delete_all", False),
            target_db="work_test" if action == ACTION_WORK_DELETE_TEST else "work",
            include_next=filters.get("include_next", False),
        )
        preview = generate_delete_preview(query)
    elif action == ACTION_WORK_UPDATE:
        changes = filters.get("changes", [])
        preview = generate_update_preview(changes, "")
    elif action == ACTION_FIN_EXPENSE:
        preview = f"Registrar gasto: {text[:50]}..."
    elif action == ACTION_CODE_EXPLAIN:
        preview = f"Explicar código: {text[:50]}"
    elif action == ACTION_CODE_REVIEW:
        preview = f"Revisar código: {text[:50]}"
    elif action == ACTION_CODE_FIX:
        preview = f"Corregir código: {text[:50]}"
    elif action == ACTION_CODE_CREATE:
        preview = f"Crear código: {text[:50]}"
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
