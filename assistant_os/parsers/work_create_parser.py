"""
Work Create Parser.

Parses semi-structured text for task creation fields.
Supports both normal WORK and TEST DB task formats.
"""
import re
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class WorkCreateFields(TypedDict, total=False):
    """Parsed fields for work task creation."""
    title: str
    project: Optional[str]
    status: str
    load: Optional[str]
    priority: Optional[str]
    due: Optional[str]
    notes: Optional[str]


class WorkCreateParseResult(TypedDict):
    """Result of parsing work create fields."""
    ok: bool
    fields: WorkCreateFields
    error: Optional[str]
    error_type: Optional[str]


# ---------------------------------------------------------------------------
# Field Patterns (compiled for performance)
# ---------------------------------------------------------------------------

# Pattern matchers for structured fields (key: value) with non-greedy capture
# Stop at next field marker (". Campo:") or end of string
_FIELD_PATTERNS = [
    # Title: stop at ". <next_field_name>:" pattern
    (re.compile(
        r"(?:t[ií]tulo|title)\s*:\s*(.+?)"
        r"(?=\.\s+(?:proyecto|project|status|estado|prioridad|priority|carga(?:\s+cognitiva)?|load|due|entrega|fecha|notas?|notes?)\s*:|\.\s*$|$)",
        re.IGNORECASE | re.DOTALL
    ), "title"),
    # Project: stop at next field or period+end
    (re.compile(
        r"(?:proyecto|project)\s*:\s*(.+?)"
        r"(?=\.\s+(?:status|estado|prioridad|priority|carga(?:\s+cognitiva)?|load|due|entrega|fecha|notas?|notes?)\s*:|\.\s*$|$)",
        re.IGNORECASE | re.DOTALL
    ), "project"),
    # Status: stop at next field or period+end
    (re.compile(
        r"(?:status|estado)\s*:\s*(.+?)"
        r"(?=\.\s+(?:prioridad|priority|carga(?:\s+cognitiva)?|load|due|entrega|fecha|notas?|notes?)\s*:|\.\s*$|$)",
        re.IGNORECASE | re.DOTALL
    ), "status"),
    # Priority: stop at next field (including "Carga cognitiva:")
    (re.compile(
        r"(?:prioridad|priority)\s*:\s*(.+?)"
        r"(?=\.\s+(?:carga(?:\s+cognitiva)?|load|due|entrega|fecha|notas?|notes?)\s*:|\.\s*$|$)",
        re.IGNORECASE | re.DOTALL
    ), "priority"),
    # Carga cognitiva or Carga: stop at next field or period+end
    (re.compile(
        r"(?:carga(?:\s+cognitiva)?|load)\s*:\s*(.+?)"
        r"(?=\.\s+(?:due|entrega|fecha|notas?|notes?)\s*:|\.\s*$|$)",
        re.IGNORECASE | re.DOTALL
    ), "load"),
    # Due: stop at next field or period+end
    (re.compile(
        r"(?:due|entrega|fecha)\s*:\s*(.+?)"
        r"(?=\.\s+(?:notas?|notes?)\s*:|\.\s*$|$)",
        re.IGNORECASE | re.DOTALL
    ), "due"),
    # Notes: everything remaining
    (re.compile(r"(?:notas?|notes?)\s*:\s*(.+?)$", re.IGNORECASE | re.DOTALL), "notes"),
]

# Test task patterns - "tarea de prueba:", "ui test:", "smoke test:"
_TEST_TASK_TITLE_PATTERN = re.compile(
    r"(?:tarea\s+de\s+prueba|ui\s*test|smoke\s*test)\s*:\s*"
    r"(.+?)(?=\.\s+(?:proyecto|project|status|estado|prioridad|priority|carga(?:\s+cognitiva)?|load|due|entrega|fecha|notas?|notes?)\s*:|$)",
    re.IGNORECASE | re.DOTALL
)

# Generic creation pattern - "Crea una tarea: <title>"
_GENERIC_CREATE_TITLE_PATTERN = re.compile(
    r"(?:crea|crear|añade|añadir|agrega|agregar|nueva?)\s+"
    r"(?:una?\s+)?tarea[s]?\s*(?:de|para|:)?\s*(.+?)(?:\n|$)",
    re.IGNORECASE
)

# Pattern to check if extracted text looks like explicit field prefix
_EXPLICIT_FIELD_PREFIX = re.compile(r"(?:t[ií]tulo|title|proyecto|project)\s*:", re.IGNORECASE)

# Cleanup patterns
_EN_WORK_PREFIX = re.compile(r"^(?:en\s+\w+|prueba)\s*:\s*", re.IGNORECASE)

# Null-like values
_NULL_VALUES = frozenset({"null", "none", "sin fecha", "n/a", "-", ""})

# Priority to load mapping
_PRIORITY_TO_LOAD = {
    "P1": "Alta", "P2": "Media", "P3": "Baja",
    "ALTA": "Alta", "MEDIA": "Media", "BAJA": "Baja",
}

# Load normalization
_LOAD_MAP = {
    "alta": "Alta", "high": "Alta", "urgente": "Alta",
    "media": "Media", "medium": "Media", "normal": "Media",
    "baja": "Baja", "low": "Baja",
}

# Status normalization — kept in sync with STATUS_ALIASES in work_update_parser.py
_STATUS_MAP = {
    # INBOX
    "inbox": "INBOX", "pendiente": "INBOX", "nuevo": "INBOX",
    "nueva": "INBOX", "entrada": "INBOX", "bandeja": "INBOX",
    # NEXT
    "next": "NEXT", "siguiente": "NEXT",
    "ahora": "NEXT", "urgente": "NEXT", "prioritario": "NEXT",
    # SCHEDULED
    "scheduled": "SCHEDULED", "programada": "SCHEDULED",
    "programado": "SCHEDULED", "agendado": "SCHEDULED",
    "agendada": "SCHEDULED", "calendarizado": "SCHEDULED",
    # WAITING
    "waiting": "WAITING", "esperando": "WAITING",
    "espera": "WAITING", "bloqueado": "WAITING", "bloqueada": "WAITING",
    # DONE
    "done": "DONE", "terminada": "DONE", "completada": "DONE",
    "hecho": "DONE", "hecha": "DONE", "terminado": "DONE",
    "completado": "DONE", "finished": "DONE", "completed": "DONE",
}


# ---------------------------------------------------------------------------
# Core Parsing Functions
# ---------------------------------------------------------------------------

def _extract_explicit_fields(text: str, fields: dict) -> None:
    """Extract fields from explicit "Field: value" patterns."""
    for pattern, field_name in _FIELD_PATTERNS:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip().rstrip('.')
            if value.lower() in _NULL_VALUES:
                fields[field_name] = None
            else:
                fields[field_name] = value


def _extract_test_task_title(text: str) -> Optional[str]:
    """Extract title from test task patterns (tarea de prueba:, ui test:, etc.)."""
    match = _TEST_TASK_TITLE_PATTERN.search(text)
    if match:
        extracted = match.group(1).strip().rstrip('.')
        if extracted:
            return extracted
    return None


def _extract_generic_title(text: str) -> Optional[str]:
    """Extract title from generic creation patterns (Crea una tarea: X)."""
    match = _GENERIC_CREATE_TITLE_PATTERN.search(text)
    if match:
        extracted = match.group(1).strip()
        # Don't use if it looks like prefix to explicit fields
        if not _EXPLICIT_FIELD_PREFIX.search(extracted):
            # Clean up any "en WORK:" prefix OR "prueba:" prefix
            cleaned = _EN_WORK_PREFIX.sub("", extracted)
            if cleaned:
                return cleaned
    return None


def _normalize_fields(fields: dict) -> None:
    """Normalize field values (priority->load, status mapping)."""
    # Map priority values to load if load not already set
    if fields.get("priority") and not fields.get("load"):
        priority_val = fields["priority"].upper()
        fields["load"] = _PRIORITY_TO_LOAD.get(priority_val, "Media")
    
    # Normalize load values
    if fields.get("load"):
        load_val = fields["load"].lower()
        fields["load"] = _LOAD_MAP.get(load_val, fields["load"])
    
    # Map common status values
    if fields.get("status"):
        status_val = fields["status"].lower().strip()
        fields["status"] = _STATUS_MAP.get(status_val, fields["status"].upper())
    
    # Default status to INBOX if not specified
    if not fields.get("status"):
        fields["status"] = "INBOX"


def parse_work_create_fields(text: str) -> WorkCreateFields:
    """
    Parse semi-structured text to extract task creation fields (normal WORK DB).
    
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
    
    Args:
        text: Input text to parse
    
    Returns:
        WorkCreateFields dict with extracted fields
    """
    fields: dict = {
        "title": "",
        "project": None,
        "status": None,
        "load": None,
        "priority": None,
        "due": None,
        "notes": None,
    }
    
    text = text.strip()
    
    # 1. Parse explicit field patterns (Título:, Proyecto:, etc.)
    _extract_explicit_fields(text, fields)
    
    # 2. If no title from explicit fields, try generic creation pattern
    if not fields["title"]:
        generic_title = _extract_generic_title(text)
        if generic_title:
            fields["title"] = generic_title
    
    # 3. Normalize fields
    _normalize_fields(fields)
    
    return fields  # type: ignore


def parse_work_create_test_fields(text: str) -> WorkCreateFields:
    """
    Parse semi-structured text for TEST DB task creation.
    
    Gives priority to test-specific patterns:
    - "tarea de prueba: <title>"
    - "ui test: <title>"
    - "smoke test: <title>"
    
    Falls back to normal parsing for other fields.
    
    Args:
        text: Input text to parse
    
    Returns:
        WorkCreateFields dict with extracted fields
    """
    fields: dict = {
        "title": "",
        "project": None,
        "status": None,
        "load": None,
        "priority": None,
        "due": None,
        "notes": None,
    }
    
    text = text.strip()
    
    # 1. Parse explicit field patterns (for all non-title fields)
    _extract_explicit_fields(text, fields)
    
    # 2. PRIORITY for test: try test task title pattern first
    if not fields["title"]:
        test_title = _extract_test_task_title(text)
        if test_title:
            fields["title"] = test_title
    
    # 3. Fallback: try generic creation pattern
    if not fields["title"]:
        generic_title = _extract_generic_title(text)
        if generic_title:
            fields["title"] = generic_title
    
    # 4. Normalize fields
    _normalize_fields(fields)
    
    return fields  # type: ignore


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_work_create_fields(fields: WorkCreateFields) -> WorkCreateParseResult:
    """
    Validate parsed work create fields.
    
    Args:
        fields: Parsed fields to validate
    
    Returns:
        WorkCreateParseResult with ok=True if valid, or error details if invalid
    """
    title = fields.get("title", "")
    
    # Title is required and must be non-empty
    if not title or not title.strip():
        return WorkCreateParseResult(
            ok=False,
            fields=fields,
            error="Missing required field: title",
            error_type="validation_error",
        )
    
    # Additional validations can be added here
    # e.g., title length, project validation, status enum check
    
    return WorkCreateParseResult(
        ok=True,
        fields=fields,
        error=None,
        error_type=None,
    )


# ---------------------------------------------------------------------------
# Combined Parse + Validate (convenience)
# ---------------------------------------------------------------------------

def parse_and_validate_work_create(text: str, is_test: bool = False) -> WorkCreateParseResult:
    """
    Parse and validate work create fields in one call.
    
    Args:
        text: Input text to parse
        is_test: If True, use test-specific parsing (tarea de prueba, etc.)
    
    Returns:
        WorkCreateParseResult with ok=True if valid, or error details
    """
    if is_test:
        fields = parse_work_create_test_fields(text)
    else:
        fields = parse_work_create_fields(text)
    
    return validate_work_create_fields(fields)
