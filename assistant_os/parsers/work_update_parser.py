"""
Work Update Parser.

Parses natural language commands for task updates/modifications.
Supports patterns like:
- "pon la tarea de consultoría en NEXT"
- "cambia esta tarea a eiProta"
- "mueve esa tarea a THCyE"
- "cambia el proyecto de la tarea de tesis"

MVP Editable Fields:
- status (Status)
- domain (Domain)  
- project (Proyecto)
"""
import re
from typing import TypedDict, Optional, Any


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class TaskReference(TypedDict, total=False):
    """Reference to target task for update."""
    keywords: list[str]           # Keywords to search in title
    context_ref: Optional[str]    # "esta", "esa", "la anterior", etc.
    notion_page_id: Optional[str] # Direct page ID if resolved
    ambiguous: bool               # True if reference is unclear


class ResolutionHints(TypedDict, total=False):
    """
    Hints for resolving the target item.
    
    These are NOT changes to apply, but filters to help locate the item.
    Priority order for resolution: project > status > domain
    """
    project: Optional[str]        # Project name to filter by
    domain: Optional[str]         # Domain to use as context filter
    status: Optional[str]         # Status to filter by


class ProposedChange(TypedDict, total=False):
    """A proposed field change."""
    field: str                    # Field name: status, domain, project
    new_value: str                # Parsed new value (normalized if possible)
    raw_value: str                # Original value as written by user
    confidence: float             # 0-1 confidence in the extracted value


class UpdateParseResult(TypedDict):
    """Result of parsing update intent."""
    is_update: bool               # True if update intent detected
    target: TaskReference         # Reference to target task
    changes: list[ProposedChange] # List of proposed changes
    resolution_hints: ResolutionHints  # Hints for locating the target item
    validation_error: Optional[str]  # Error message if validation failed
    debug_info: dict[str, Any]    # Debug information


# ---------------------------------------------------------------------------
# Field Normalization Maps
# ---------------------------------------------------------------------------

# Status normalization (Spanish/English to canonical)
STATUS_ALIASES: dict[str, str] = {
    # INBOX
    "inbox": "INBOX", "entrada": "INBOX", "bandeja": "INBOX",
    "nuevo": "INBOX", "nueva": "INBOX", "pendiente": "INBOX",
    # NEXT
    "next": "NEXT", "siguiente": "NEXT", "ahora": "NEXT",
    "urgente": "NEXT", "prioritario": "NEXT",
    # SCHEDULED  
    "scheduled": "SCHEDULED", "programado": "SCHEDULED",
    "programada": "SCHEDULED", "agendado": "SCHEDULED",
    "agendada": "SCHEDULED", "calendarizado": "SCHEDULED",
    # WAITING
    "waiting": "WAITING", "esperando": "WAITING",
    "espera": "WAITING", "bloqueado": "WAITING",
    "bloqueada": "WAITING",
    # DONE
    "done": "DONE", "hecho": "DONE", "hecha": "DONE",
    "terminado": "DONE", "terminada": "DONE",
    "completado": "DONE", "completada": "DONE",
    "finished": "DONE", "completed": "DONE",
}

# Domain aliases (normalized names)
DOMAIN_ALIASES: dict[str, str] = {
    # WORK
    "work": "WORK", "trabajo": "WORK", "laboral": "WORK",
    # PRO_DIAG
    "pro_diag": "PRO_DIAG", "prodiag": "PRO_DIAG",
    "diagnóstico": "PRO_DIAG", "diagnostico": "PRO_DIAG",
    "consultoría": "PRO_DIAG", "consultoria": "PRO_DIAG",
    # FIN
    "fin": "FIN", "finanzas": "FIN", "dinero": "FIN",
    # REL
    "rel": "REL", "relaciones": "REL",
    # HEALTH
    "health": "HEALTH", "salud": "HEALTH",
    # EIPROTA
    "eiprota": "EIPROTA", "tti": "EIPROTA",
    "escritura": "EIPROTA", "arte": "EIPROTA",
    # ENERGY
    "energy": "ENERGY", "energía": "ENERGY", "energia": "ENERGY",
}

# Known project names (to be extended dynamically from Notion)
# These are used for fuzzy matching
PROJECT_ALIASES: dict[str, str] = {
    "thcye": "THCyE", "tesis": "THCyE",
    "cellab": "CELLAB", "laboratorio": "CELLAB",
    "eiprota": "eiProta",
}


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Context reference patterns (this/that task)
CONTEXT_REF_PATTERNS = [
    (re.compile(r"\b(esta|esa|la|eso|esto)\s+tarea\b", re.IGNORECASE), "context"),
    (re.compile(r"\b(la\s+)?anterior\b", re.IGNORECASE), "previous"),
    (re.compile(r"\b(la\s+)?última\b", re.IGNORECASE), "last"),
]

# Patterns to extract task reference by keywords
# "la tarea de X", "tarea de X", "la de X"
TASK_REF_KEYWORD_PATTERNS = [
    # "la tarea de consultoría" / "tarea de tesis"
    re.compile(r"\b(?:la\s+)?tarea\s+(?:de\s+)?(.+?)(?:\s+(?:en|a|al)\s+|\s*$)", re.IGNORECASE),
    # "la de consultoría"
    re.compile(r"\bla\s+de\s+(.+?)(?:\s+(?:en|a|al)\s+|\s*$)", re.IGNORECASE),
]

# Status change patterns
# "pon X en NEXT", "cambia a NEXT", "pasa a WAITING"
STATUS_CHANGE_PATTERNS = [
    # "pon/ponla/ponlo en NEXT"
    re.compile(r"\b(?:pon(?:la|lo|le|er)?)\s+.*?\b(?:en|a)\s+([A-Za-z]+)\b", re.IGNORECASE),
    # "cambia a NEXT" / "cámbiala a NEXT"
    re.compile(r"\bcambia(?:la|lo|r)?\s+.*?\b(?:a|al)\s+([A-Za-z]+)\b", re.IGNORECASE),
    # "muevela a NEXT"
    re.compile(r"\bmuev(?:e|a|o)(?:la|lo)?\s+.*?\b(?:a|al)\s+([A-Za-z]+)\b", re.IGNORECASE),
    # "pasa a WAITING"
    re.compile(r"\bpasa(?:la|lo|r)?\s+.*?\b(?:a|al)\s+([A-Za-z]+)\b", re.IGNORECASE),
    # "estado/status a X"
    re.compile(r"\b(?:estado|status)\s+(?:a|al|en)\s+([A-Za-z]+)\b", re.IGNORECASE),
    # "marca X como NEXT" / "como done" — bulk/singular idiom
    re.compile(r"\bcomo\s+([A-Za-z]+)\b", re.IGNORECASE),
]

# Project change patterns
# "cambia el proyecto a X", "pon proyecto X"
PROJECT_CHANGE_PATTERNS = [
    # "cambia el proyecto a THCyE"
    re.compile(r"\b(?:cambia|cambiar)\s+(?:el\s+)?proyecto\s+(?:a|al|de)?\s*([A-Za-z0-9_]+)\b", re.IGNORECASE),
    # "pon el proyecto X" / "proyecto a X"
    re.compile(r"\b(?:pon(?:er|la|lo)?|mueve?|pasa)\s+.*?\bproyecto\s+(?:a|al|en)?\s*([A-Za-z0-9_]+)\b", re.IGNORECASE),
    # "a proyecto X"
    re.compile(r"\ba\s+(?:el\s+)?proyecto\s+([A-Za-z0-9_]+)\b", re.IGNORECASE),
]

# Domain change patterns  
# "cambia el dominio a X", "mueve a dominio X"
DOMAIN_CHANGE_PATTERNS = [
    # "cambia el dominio a WORK"
    re.compile(r"\b(?:cambia|cambiar)\s+(?:el\s+)?(?:dominio|domain)\s+(?:a|al)?\s*([A-Za-z_]+)\b", re.IGNORECASE),
    # "mueve al dominio X"
    re.compile(r"\b(?:mueve?|pasa|pon)\s+.*?\b(?:dominio|domain)\s+(?:a|al|en)?\s*([A-Za-z_]+)\b", re.IGNORECASE),
    # "a dominio X"
    re.compile(r"\ba\s+(?:el\s+)?(?:dominio|domain)\s+([A-Za-z_]+)\b", re.IGNORECASE),
]

# Direct target value patterns (when the target value is known domain/project)
# "cambia a eiProta" / "ponla en THCyE"
DIRECT_TARGET_VALUE_PATTERNS = [
    # Known project names
    re.compile(r"\b(?:a|al|en)\s+(thcye|cellab|eiprota|assistant[\s_]*os)\b", re.IGNORECASE),
    # Known domain names
    re.compile(r"\b(?:a|al|en)\s+(work|pro_diag|fin|rel|health|eiprota|energy)\b", re.IGNORECASE),
]

# Resolution hint patterns - to locate the task (not change it)
# "la tarea de eiProta" / "la tarea en WORK" / "la de consultoría"
RESOLUTION_PROJECT_HINT_PATTERNS = [
    # "la tarea de eiProta" / "tarea del proyecto eiProta"
    re.compile(r"\btarea\s+(?:del?\s+(?:proyecto\s+)?|en\s+)([A-Za-z0-9_]+)\b", re.IGNORECASE),
    # "la de eiProta" (short form)
    re.compile(r"\bla\s+de\s+([A-Za-z0-9_]+)\b", re.IGNORECASE),
    # "en el proyecto X" before the change verb
    re.compile(r"\ben\s+(?:el\s+)?proyecto\s+([A-Za-z0-9_]+)\b", re.IGNORECASE),
]

RESOLUTION_DOMAIN_HINT_PATTERNS = [
    # "la tarea de WORK" / "tarea en el dominio WORK"
    re.compile(r"\btarea\s+(?:del?\s+dominio\s+|en\s+el?\s*dominio\s+)([A-Za-z_]+)\b", re.IGNORECASE),
    # "en dominio X"
    re.compile(r"\ben\s+(?:el\s+)?dominio\s+([A-Za-z_]+)\b", re.IGNORECASE),
]

RESOLUTION_STATUS_HINT_PATTERNS = [
    # "la tarea en INBOX" / "la que está en NEXT"
    re.compile(r"\btarea\s+(?:en|que\s+(?:está|esta)\s+en)\s+(INBOX|NEXT|SCHEDULED|WAITING|DONE)\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Core Parsing Functions
# ---------------------------------------------------------------------------

def _normalize_status(value: str) -> tuple[str, float]:
    """
    Normalize a status value.
    
    Returns:
        Tuple of (normalized_value, confidence)
    """
    value_lower = value.lower().strip()
    
    # Direct match
    if value_lower in STATUS_ALIASES:
        return STATUS_ALIASES[value_lower], 1.0
    
    # Uppercase check
    value_upper = value.upper()
    if value_upper in ("INBOX", "NEXT", "SCHEDULED", "WAITING", "DONE"):
        return value_upper, 1.0
    
    return value, 0.5


def _normalize_domain(value: str) -> tuple[str, float]:
    """
    Normalize a domain value.
    
    Returns:
        Tuple of (normalized_value, confidence)
    """
    value_lower = value.lower().strip()
    
    # Direct match
    if value_lower in DOMAIN_ALIASES:
        return DOMAIN_ALIASES[value_lower], 1.0
    
    # Case-insensitive match for known domains
    value_upper = value.upper()
    if value_upper in ("WORK", "PRO_DIAG", "FIN", "REL", "HEALTH", "EIPROTA", "ENERGY"):
        return value_upper, 1.0
    
    return value, 0.5


def _normalize_project(value: str) -> tuple[str, float]:
    """
    Normalize a project value.
    
    Returns:
        Tuple of (normalized_value, confidence)
    """
    value_lower = value.lower().strip()
    
    # Direct match in aliases
    if value_lower in PROJECT_ALIASES:
        return PROJECT_ALIASES[value_lower], 1.0
    
    # Return as-is with medium confidence (needs validation against Notion)
    return value, 0.7


def _extract_context_reference(text: str) -> Optional[str]:
    """Extract context reference (esta, esa, anterior) from text."""
    for pattern, ref_type in CONTEXT_REF_PATTERNS:
        if pattern.search(text):
            return ref_type
    return None


def _extract_task_keywords(text: str) -> list[str]:
    """Extract task reference keywords from text."""
    for pattern in TASK_REF_KEYWORD_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_keywords = match.group(1).strip()
            # Clean up: remove trailing prepositions, punctuation
            raw_keywords = re.sub(r"\s+(en|a|al|de|del|para)$", "", raw_keywords, flags=re.IGNORECASE)
            raw_keywords = raw_keywords.strip(".,:")
            if raw_keywords:
                # Split on common separators
                keywords = re.split(r"\s+y\s+|\s+o\s+|,\s*", raw_keywords, flags=re.IGNORECASE)
                return [kw.strip() for kw in keywords if kw.strip()]
    return []


def _extract_status_change(text: str) -> Optional[ProposedChange]:
    """Extract status change from text."""
    for pattern in STATUS_CHANGE_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_value = match.group(1).strip()
            normalized, confidence = _normalize_status(raw_value)
            # Only accept if it normalizes to a known status
            if normalized in ("INBOX", "NEXT", "SCHEDULED", "WAITING", "DONE"):
                return ProposedChange(
                    field="status",
                    new_value=normalized,
                    raw_value=raw_value,
                    confidence=confidence,
                )
    return None


def _extract_project_change(text: str) -> Optional[ProposedChange]:
    """Extract project change from text."""
    for pattern in PROJECT_CHANGE_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_value = match.group(1).strip()
            normalized, confidence = _normalize_project(raw_value)
            return ProposedChange(
                field="project",
                new_value=normalized,
                raw_value=raw_value,
                confidence=confidence,
            )
    return None


def _extract_domain_change(text: str) -> Optional[ProposedChange]:
    """Extract domain change from text."""
    for pattern in DOMAIN_CHANGE_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_value = match.group(1).strip()
            normalized, confidence = _normalize_domain(raw_value)
            return ProposedChange(
                field="domain",
                new_value=normalized,
                raw_value=raw_value,
                confidence=confidence,
            )
    return None


def _extract_direct_target_change(text: str) -> Optional[ProposedChange]:
    """
    Extract change when target value is directly mentioned.
    
    E.g., "cambia a eiProta" - we know eiProta is a project.
    """
    text_lower = text.lower()
    
    # Check for known project names
    for pattern in DIRECT_TARGET_VALUE_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_value = match.group(1).strip()
            value_lower = raw_value.lower()
            
            # Check if it's a known project
            if value_lower in PROJECT_ALIASES or value_lower in ("thcye", "cellab", "eiprota"):
                normalized, confidence = _normalize_project(raw_value)
                return ProposedChange(
                    field="project",
                    new_value=normalized,
                    raw_value=raw_value,
                    confidence=confidence,
                )
            
            # Check if it's a known status
            if value_lower in STATUS_ALIASES:
                normalized, confidence = _normalize_status(raw_value)
                return ProposedChange(
                    field="status",
                    new_value=normalized,
                    raw_value=raw_value,
                    confidence=confidence,
                )
            
            # Check if it's a known domain
            if value_lower in DOMAIN_ALIASES or value_lower in ("work", "pro_diag", "fin", "rel", "health", "eiprota", "energy"):
                normalized, confidence = _normalize_domain(raw_value)
                return ProposedChange(
                    field="domain",
                    new_value=normalized,
                    raw_value=raw_value,
                    confidence=confidence,
                )
    
    return None


def _extract_resolution_hints(text: str, changes: list[ProposedChange]) -> ResolutionHints:
    """
    Extract hints for resolving the target item.
    
    These help locate the item but are NOT changes to apply.
    Uses project as primary anchor, domain as context filter.
    
    Args:
        text: User input text
        changes: Already extracted changes (to avoid duplicating)
        
    Returns:
        ResolutionHints with project/domain/status filters
    """
    hints = ResolutionHints(project=None, domain=None, status=None)
    
    # Track which values are already changes (don't use them as hints)
    change_values = {c.get("new_value", "").lower() for c in changes}
    
    # Extract project hint (primary anchor)
    for pattern in RESOLUTION_PROJECT_HINT_PATTERNS:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            value_lower = value.lower()
            # Normalize and check if it's a known project
            normalized, confidence = _normalize_project(value)
            if confidence >= 0.7 and normalized.lower() not in change_values:
                hints["project"] = normalized
                break
    
    # Also check if keywords match a known project alias
    # "la tarea de tesis" → project = THCyE
    for pattern in TASK_REF_KEYWORD_PATTERNS:
        match = pattern.search(text)
        if match:
            keyword = match.group(1).strip().lower()
            # Clean keyword
            keyword = re.sub(r"\s+(en|a|al|de|del|para)$", "", keyword, flags=re.IGNORECASE).strip()
            if keyword in PROJECT_ALIASES:
                resolved_project = PROJECT_ALIASES[keyword]
                if resolved_project.lower() not in change_values:
                    hints["project"] = resolved_project
                    break
    
    # Extract domain hint (context, not primary identifier)
    for pattern in RESOLUTION_DOMAIN_HINT_PATTERNS:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            normalized, confidence = _normalize_domain(value)
            if confidence >= 0.7 and normalized.lower() not in change_values:
                hints["domain"] = normalized
                break
    
    # Extract status hint
    for pattern in RESOLUTION_STATUS_HINT_PATTERNS:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            normalized, confidence = _normalize_status(value)
            if confidence >= 0.7 and normalized.lower() not in change_values:
                hints["status"] = normalized
                break
    
    return hints


# ---------------------------------------------------------------------------
# Main Parser Function
# ---------------------------------------------------------------------------

def parse_work_update_intent(text: str) -> UpdateParseResult:
    """
    Parse natural language text for work update intent.
    
    Args:
        text: User input text
    
    Returns:
        UpdateParseResult with parsed target, changes, and validation status
    """
    debug_info: dict[str, Any] = {"raw_text": text[:200]}
    changes: list[ProposedChange] = []
    validation_error: Optional[str] = None
    
    # 1. Extract task reference
    context_ref = _extract_context_reference(text)
    keywords = _extract_task_keywords(text)

    # Tokenize input and extract free text keywords for WORK_QUERY
    tokens = [t for t in re.split(r"\s+", text) if t]
    normalized_status = set(STATUS_ALIASES.keys())
    normalized_domain = set(DOMAIN_ALIASES.keys())
    normalized_project = set(PROJECT_ALIASES.keys())
    ignore_tokens = {
        # Articles / prepositions
        "tarea", "tareas", "que", "dame", "pon", "en", "a", "el", "la", "las", "los",
        "de", "del", "y", "o", "con", "para", "todas", "toda", "todos", "todo",
        "incluyan", "incluya",
        # Update-verb markers — these are grammatical operators, not task-title words
        "marca", "marcar", "pon", "poner", "cambia", "cambiar", "mueve", "mover",
        "pasa", "pasar", "actualiza", "actualizar",
        # Status-change connectors
        "como", "a", "al",
    }
    extra_keywords = []
    for token in tokens:
        token_lower = token.lower()
        if (token_lower not in normalized_status and
            token_lower not in normalized_domain and
            token_lower not in normalized_project and
            token_lower not in ignore_tokens):
            extra_keywords.append(token)
    # Merge keywords from patterns and free tokens
    all_keywords = list(set(keywords + extra_keywords))

    target = TaskReference(
        keywords=all_keywords,
        context_ref=context_ref,
        notion_page_id=None,
        ambiguous=not (context_ref or all_keywords),
    )

    debug_info["context_ref"] = context_ref
    debug_info["keywords"] = all_keywords
    
    # 2. Extract changes (in priority order)
    
    # Status change
    status_change = _extract_status_change(text)
    if status_change:
        changes.append(status_change)
        debug_info["status_change"] = dict(status_change)
    
    # Project change
    project_change = _extract_project_change(text)
    if project_change:
        changes.append(project_change)
        debug_info["project_change"] = dict(project_change)
    
    # Domain change
    domain_change = _extract_domain_change(text)
    if domain_change:
        changes.append(domain_change)
        debug_info["domain_change"] = dict(domain_change)
    
    # If no explicit field changes found, try direct target extraction
    if not changes:
        direct_change = _extract_direct_target_change(text)
        if direct_change:
            changes.append(direct_change)
            debug_info["direct_change"] = dict(direct_change)
    
    # 3. Extract resolution hints (project > status > domain priority)
    resolution_hints = _extract_resolution_hints(text, changes)
    debug_info["resolution_hints"] = dict(resolution_hints)
    
    # 4. Validate
    if target["ambiguous"] and not keywords:
        # If we have resolution hints, the target is less ambiguous
        if not any(resolution_hints.values()):
            validation_error = "No se pudo identificar la tarea a actualizar. Especifica el título o usa 'esta tarea'."
    
    if not changes:
        validation_error = validation_error or "No se detectaron cambios. Especifica qué campo deseas modificar (status, proyecto, dominio)."
    
    return UpdateParseResult(
        is_update=bool(changes),
        target=target,
        changes=changes,
        resolution_hints=resolution_hints,
        validation_error=validation_error,
        debug_info=debug_info,
    )


def has_update_intent(text: str) -> bool:
    """
    Quick check if text contains update intent.
    
    Args:
        text: User input text
    
    Returns:
        True if update intent patterns are detected
    """
    from ..classifier import OPERATIONAL_WORK_UPDATE_PATTERNS
    
    text_lower = text.lower()
    for pattern in OPERATIONAL_WORK_UPDATE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def generate_update_preview(
    changes: list[ProposedChange],
    target_title: str = "",
) -> str:
    """
    Generate a human-readable preview of proposed changes.
    
    Args:
        changes: List of proposed changes
        target_title: Title of target task (optional)
    
    Returns:
        Preview string for confirmation
    """
    if not changes:
        return "Sin cambios detectados"
    
    task_ref = f'"{target_title}"' if target_title else "tarea"
    
    change_desc = []
    for change in changes:
        field = change["field"]
        new_val = change["new_value"]
        
        if field == "status":
            change_desc.append(f"Status → {new_val}")
        elif field == "project":
            change_desc.append(f"Proyecto → {new_val}")
        elif field == "domain":
            change_desc.append(f"Dominio → {new_val}")
    
    changes_str = ", ".join(change_desc)
    
    return f"Actualizar {task_ref}: {changes_str}"
