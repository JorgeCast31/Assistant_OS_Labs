"""
Work Delete Parser.

Parses natural language commands for task deletion.
Supports patterns like:
- "elimina tareas que contengan: UI OR test"
- "borra tareas en WORK: UI Confirm OR Test Confirm"
- "elimina tareas de prueba"
- "wipe/reset tareas"
"""
import re
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class DeleteQuery(TypedDict, total=False):
    """Parsed query for delete operation."""
    keywords: list[str]           # Keywords to match (e.g., ["UI", "test"])
    op: str                       # Operator: "OR" | "AND"
    delete_all: bool              # True if user wants to delete ALL tasks
    target_db: str                # "work" | "work_test"
    include_next: bool            # True if explicitly including NEXT status tasks


class DeleteParseResult(TypedDict):
    """Result of parsing delete intent."""
    is_delete: bool               # True if delete intent detected
    query: Optional[DeleteQuery]  # Parsed query (None if no delete intent)
    validation_error: Optional[str]  # Error message if validation failed


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Delete intent verbs (must be at start or after common words)
_DELETE_VERBS_PATTERN = re.compile(
    r"\b(?:elimina|eliminar|borra|borrar|limpia|limpiar|wipe|borra|delete|remove|quita|quitar)\b",
    re.IGNORECASE
)

# Task reference patterns
_TASK_REF_PATTERN = re.compile(
    r"\b(?:tareas?|tasks?|items?)\b",
    re.IGNORECASE
)

# Test database indicators
_TEST_DB_PATTERN = re.compile(
    r"\b(?:prueba|pruebas|test|tests|testing|work_test|test\s*db)\b",
    re.IGNORECASE
)

# Production database indicators
_WORK_DB_PATTERN = re.compile(
    r"\b(?:en\s+work|work\s*db|produccion|production|principal)\b",
    re.IGNORECASE
)

# Keywords extraction patterns
# "que contengan:" / "contenga:" / "contienen:" / "que tenga:" / "que diga:" / "que digan:"
_KEYWORDS_PREFIX_PATTERN = re.compile(
    r"(?:que\s+)?(?:contengan?|contienen?|tenga[n]?|diga[n]?|con|matching|match|like)[\s:]+(.+)",
    re.IGNORECASE
)

# Alternative: "tareas X OR Y" / "tareas de X" pattern
_KEYWORDS_INLINE_PATTERN = re.compile(
    r"\btareas?\s+(?:de\s+)?(.+?)(?:\s*$|\.\s*$)",
    re.IGNORECASE
)

# Keyword separator patterns
# Supports: "OR", "y", "," 
_KEYWORD_SEPARATOR = re.compile(
    r"\s+(?:OR|Y|AND|\|)\s+|\s*,\s*|\s+o\s+",
    re.IGNORECASE
)

# "todas las tareas" / "all tasks" pattern
_ALL_TASKS_PATTERN = re.compile(
    r"\b(?:todas?\s+(?:las\s+)?tareas?|all\s+(?:the\s+)?tasks?|everything|todo)\b",
    re.IGNORECASE
)

# "incluye NEXT" / "include NEXT" pattern
_INCLUDE_NEXT_PATTERN = re.compile(
    r"\b(?:incluye?|include|incluyendo|including)\s+NEXT\b",
    re.IGNORECASE
)

# "en WORK:" / "in WORK:" explicit target pattern
_EXPLICIT_TARGET_PATTERN = re.compile(
    r"\ben\s+(work|work_test|test|prueba)[:\s]",
    re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Core Parsing Functions
# ---------------------------------------------------------------------------

def _has_delete_intent(text: str) -> bool:
    """Check if text has delete intent."""
    has_verb = bool(_DELETE_VERBS_PATTERN.search(text))
    has_task_ref = bool(_TASK_REF_PATTERN.search(text))
    return has_verb and has_task_ref


def _extract_keywords(text: str) -> tuple[list[str], str]:
    """
    Extract keywords from text.
    
    Handles:
    1. Quoted keywords: "confirmar" or 'confirmar' => extracts exact content
    2. "que diga/digan/contenga/contengan:" patterns 
    3. Cleans up noise phrases like "del muro", "que", etc.
    
    Returns:
        Tuple of (keywords_list, operator)
        operator is "OR" by default, "AND" if explicitly specified
    """
    keywords: list[str] = []
    
    # STEP 1: Check for quoted keywords FIRST (highest priority)
    # Matches: que diga: "confirmar" or que contengan 'test'
    quoted_pattern = re.compile(r'["\']([^"\']+)["\']')
    quoted_matches = quoted_pattern.findall(text)
    if quoted_matches:
        # Use quoted content as exact keywords
        for kw in quoted_matches:
            kw = kw.strip()
            if kw:
                keywords.append(kw)
        # Determine operator from original text
        op = "OR"
        if re.search(r"\bAND\b", text, re.IGNORECASE):
            op = "AND"
        return (keywords, op)
    
    # STEP 2: Try explicit "que diga:", "que contengan:", etc. patterns
    # Pattern: que (diga|digan|contenga|contengan|tenga|tengan)[:] <keyword>
    keyword_trigger_pattern = re.compile(
        r"(?:que\s+)?(?:diga[n]?|contenga[n]?|tenga[n]?)[\s:]+(.+?)(?:\s*$)",
        re.IGNORECASE
    )
    match = keyword_trigger_pattern.search(text)
    if match:
        keyword_str = match.group(1).strip()
    else:
        # STEP 3: Try broader pattern for explicit prefix
        match = _KEYWORDS_PREFIX_PATTERN.search(text)
        if match:
            keyword_str = match.group(1).strip()
        else:
            # STEP 4: Try inline pattern "tareas <keywords>"
            match = _KEYWORDS_INLINE_PATTERN.search(text)
            if match:
                keyword_str = match.group(1).strip()
                # Filter out "de prueba", "de test", etc.
                keyword_str = re.sub(r"^de\s+", "", keyword_str, flags=re.IGNORECASE)
            else:
                return ([], "OR")
    
    # STEP 5: Clean up the extracted keyword string
    # Remove noise phrases that appear BEFORE the actual keyword
    noise_phrases = [
        r"del\s+muro\s+",  # "del muro"
        r"que\s+",         # "que"
        r"todas?\s+las?\s+",  # "todas las" / "toda la"
    ]
    for noise in noise_phrases:
        keyword_str = re.sub(noise, "", keyword_str, flags=re.IGNORECASE)
    
    # Remove trailing punctuation
    keyword_str = keyword_str.strip().rstrip(".,;:")
    
    # Determine operator
    op = "OR"
    if re.search(r"\bAND\b", keyword_str, re.IGNORECASE):
        op = "AND"
    elif re.search(r"\s+y\s+", keyword_str, re.IGNORECASE) and not re.search(r"\s+o\s+", keyword_str, re.IGNORECASE):
        # If only "y" (and) is used without "o" (or), assume AND
        op = "AND"
    
    # Split by separators
    raw_keywords = _KEYWORD_SEPARATOR.split(keyword_str)
    
    # Clean up keywords
    noise_words = {
        "de", "la", "las", "el", "los", "en", "a", "que", "",
        "contengan", "contenga", "contienen", "diga", "digan", "tenga", "tengan",
        "del", "muro", "todas", "toda", "los", "las"
    }
    
    for kw in raw_keywords:
        kw = kw.strip().strip('"').strip("'").strip()
        # Remove common noise words
        if kw.lower() in noise_words:
            continue
        if kw:
            keywords.append(kw)
    
    return (keywords, op)


def _detect_target_db(text: str) -> str:
    """
    Detect which database the delete should target.
    
    Returns:
        "work_test" if test indicators found, "work" otherwise
    """
    # Check explicit target pattern first
    match = _EXPLICIT_TARGET_PATTERN.search(text)
    if match:
        target = match.group(1).lower()
        if target in ("work_test", "test", "prueba"):
            return "work_test"
        return "work"
    
    # Check test indicators
    if _TEST_DB_PATTERN.search(text):
        return "work_test"
    
    # Default to production
    return "work"


def parse_work_delete_intent(text: str) -> DeleteParseResult:
    """
    Parse work delete intent from natural language text.
    
    Supports patterns:
    - "elimina|borra|borrar|eliminar|limpia|wipe" + ("tarea"|"tareas")
    - "que contengan:" / "contenga:" / "contienen:" / "que tenga:"
    - tokens separated by "OR", "y", comas
    - "UI OR test", "UI y test", "UI, test"
    - "todas las tareas" for delete all
    
    Args:
        text: Input text to parse
    
    Returns:
        DeleteParseResult with:
        - is_delete: True if delete intent detected
        - query: Parsed DeleteQuery or None
        - validation_error: Error message if validation failed
    """
    text = text.strip()
    
    # Check delete intent
    if not _has_delete_intent(text):
        return DeleteParseResult(
            is_delete=False,
            query=None,
            validation_error=None
        )
    
    # Check for "delete all" intent (preliminary)
    has_all_pattern = bool(_ALL_TASKS_PATTERN.search(text))
    
    # Extract keywords
    keywords, op = _extract_keywords(text)
    
    # CRITICAL FIX: delete_all=true ONLY when NO keywords/filters exist
    # If keywords are present, delete_all MUST be false (user wants filtered delete)
    delete_all = has_all_pattern and len(keywords) == 0
    
    # Detect target database
    target_db = _detect_target_db(text)
    
    # Check for "include NEXT" flag
    include_next = bool(_INCLUDE_NEXT_PATTERN.search(text))
    
    # Build query
    query = DeleteQuery(
        keywords=keywords,
        op=op,
        delete_all=delete_all,
        target_db=target_db,
        include_next=include_next
    )
    
    # Validate
    validation_error = None
    if not keywords and not delete_all:
        validation_error = "Debes especificar keywords o 'todas las tareas' para eliminar"
    
    return DeleteParseResult(
        is_delete=True,
        query=query,
        validation_error=validation_error
    )


def has_delete_intent(text: str) -> bool:
    """
    Quick check for delete intent without full parsing.
    
    Use this for routing override detection.
    
    Args:
        text: Input text to check
    
    Returns:
        True if text appears to have delete intent
    """
    return _has_delete_intent(text)


# ---------------------------------------------------------------------------
# Preview Generation
# ---------------------------------------------------------------------------

def generate_delete_preview(query: DeleteQuery, candidate_count: int = 0) -> str:
    """
    Generate human-readable preview of delete operation.
    
    Args:
        query: Parsed delete query
        candidate_count: Number of matching tasks (0 if not yet queried)
    
    Returns:
        Preview string describing what will be deleted
    """
    target = "TEST DB" if query.get("target_db") == "work_test" else "WORK"
    
    if query.get("delete_all"):
        return f"⚠️ Eliminar TODAS las tareas en {target}"
    
    keywords = query.get("keywords", [])
    if keywords:
        op = query.get("op", "OR")
        kw_str = f" {op} ".join(keywords)
        preview = f"Eliminar tareas en {target} que contengan: {kw_str}"
    else:
        preview = f"Eliminar tareas en {target}"
    
    if candidate_count > 0:
        preview += f" ({candidate_count} encontrada(s))"
    
    if query.get("include_next"):
        preview += " [incluye NEXT]"
    
    return preview
