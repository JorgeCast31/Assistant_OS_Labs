"""
Work Mutation Parser

Parses bulk mutation commands into a structured dict (MutationPlan payload)
that gets packed into Plan.filters for WORK_UPDATE and WORK_DELETE operations.

Handles:
    "marca todas las tareas de consultoria como next"
        → bulk=True, filter_project="Consultoría", changes=[status→NEXT]

    "marca tareas de tesis inbox como next"
        → bulk=True, filter_project="Tesis", filter_status="INBOX", changes=[status→NEXT]

    "elimina todas las tareas done de consultoria"
        → bulk=True, filter_project="Consultoría", filter_status="DONE"

Design note
-----------
This parser is intentionally separate from work_update_parser.parse_work_update_intent()
which handles *single-task* updates ("pon la tarea de X en NEXT").
Bulk operations have different semantics: filters describe WHAT to find,
changes describe WHAT to apply to every match.
"""
from __future__ import annotations

import re
from typing import Optional

from .work_update_parser import (
    STATUS_ALIASES,
    PROJECT_ALIASES,
    _normalize_status,
    _normalize_project,
    ProposedChange,
)

# ---------------------------------------------------------------------------
# Bulk intent detection
# ---------------------------------------------------------------------------

# "marca todas las tareas …" or "marca las tareas de X …"
_BULK_UPDATE_PATTERNS = [
    re.compile(r"\bmarca[r]?\s+todas?\s+(?:las?\s+)?tareas?\b", re.IGNORECASE),
    re.compile(r"\bmarca[r]?\s+(?:las?\s+)?tareas?\s+(?:de|del?)\s+\w+", re.IGNORECASE),
]

# "elimina/borra/archiva todas las tareas …" or "… tareas de/con …"
_BULK_DELETE_PATTERNS = [
    re.compile(r"\b(?:elimina|borra|archiva)[r]?\s+todas?\s+(?:las?\s+)?tareas?\b", re.IGNORECASE),
    re.compile(r"\b(?:elimina|borra|archiva)[r]?\s+(?:las?\s+)?tareas?\s+(?:de|del?|con)\b", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

# "de consultoria" / "de tesis" / "del proyecto X"
_PROJECT_FILTER_PATTERN = re.compile(
    r"\b(?:del?\s+(?:proyecto\s+)?|en\s+(?:el\s+)?proyecto\s+)"
    r"([A-Za-záéíóúüñÁÉÍÓÚÜÑa-z0-9]+)\b"
    r"|"
    r"\bde\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑa-z0-9]+)\b",
    re.IGNORECASE,
)

# "como next" / "como done" → the target status (change to apply)
_COMO_STATUS_PATTERN = re.compile(r"\bcomo\s+([A-Za-z]+)\b", re.IGNORECASE)

# Inline status word appearing *before* "como" → filter criterion (find tasks in this status)
_INLINE_STATUS_WORDS = set(STATUS_ALIASES.keys()) | {
    "inbox", "next", "scheduled", "waiting", "done",
}

# Words that must never be treated as project names
_STOPWORDS = {
    "todas", "todos", "toda", "todo", "las", "los", "la", "el",
    "tareas", "tarea", "de", "del", "como", "con", "que", "en",
    "marca", "marcar", "elimina", "eliminar", "borra", "borrar",
    "archiva", "archivar", "mis", "sus", "hay", "son",
}


def is_bulk_update(text: str) -> bool:
    """Return True if *text* expresses a bulk-update intent."""
    for p in _BULK_UPDATE_PATTERNS:
        if p.search(text):
            return True
    return False


def is_bulk_delete(text: str) -> bool:
    """Return True if *text* expresses a bulk-delete intent."""
    for p in _BULK_DELETE_PATTERNS:
        if p.search(text):
            return True
    return False


def _extract_filter_project(text: str) -> Optional[str]:
    """
    Extract project filter from text.

    Tries "del proyecto X", "de X" patterns and normalizes against
    PROJECT_ALIASES. Returns None if no project match or if the token
    is a stopword / plain status word.
    """
    for match in _PROJECT_FILTER_PATTERN.finditer(text):
        raw = (match.group(1) or match.group(2) or "").strip()
        if not raw:
            continue
        raw_lower = raw.lower()
        if raw_lower in _STOPWORDS or raw_lower in _INLINE_STATUS_WORDS:
            continue
        # Skip bare status words like "done", "inbox"
        if raw_lower in STATUS_ALIASES:
            continue
        normalized, confidence = _normalize_project(raw)
        return normalized if confidence >= 0.7 else raw.capitalize()
    return None


def _extract_filter_status(text: str, como_start: Optional[int]) -> Optional[str]:
    """
    Extract inline status word from *text* that appears BEFORE the "como …"
    clause.  This is the *filter* (find tasks with this status), not the change.
    """
    search_text = text[:como_start] if como_start is not None else text
    for word in re.findall(r"\b[A-Za-z]+\b", search_text):
        word_lower = word.lower()
        if word_lower in STATUS_ALIASES:
            normalized = STATUS_ALIASES[word_lower]
            return normalized
    return None


def _extract_como_change(text: str) -> tuple[list[dict], Optional[int]]:
    """
    Extract "como STATUS" → ProposedChange.

    Returns (changes_list, position_of_como_match_start) so callers can
    strip the "como …" clause before looking for inline filter-status words.
    """
    match = _COMO_STATUS_PATTERN.search(text)
    if not match:
        return [], None

    raw_status = match.group(1).strip()
    normalized, confidence = _normalize_status(raw_status)
    if normalized not in ("INBOX", "NEXT", "SCHEDULED", "WAITING", "DONE"):
        return [], None

    change = ProposedChange(
        field="status",
        new_value=normalized,
        raw_value=raw_status,
        confidence=confidence,
    )
    return [dict(change)], match.start()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_mutation_intent(text: str) -> dict:
    """
    Parse a bulk mutation command into a MutationPlan-compatible dict.

    Suitable for direct use as Plan.filters for WORK_UPDATE (bulk) and
    WORK_DELETE operations.

    Returned keys
    -------------
    bulk          : True — signals that all matching items should be targeted
    filter_project: project to query (None = no project filter)
    filter_status : status to query (None = no status filter)
    changes       : list[ProposedChange dict] — what to apply to each match
    keywords      : [] — bulk mode uses structured filters, not keyword search
    hint_project  : alias for filter_project (backward compat with preview path)
    hint_status   : alias for filter_status
    hint_domain   : None
    ambiguous     : False
    """
    changes, como_pos = _extract_como_change(text)
    filter_project = _extract_filter_project(text)
    filter_status = _extract_filter_status(text, como_pos)

    return {
        "bulk": True,
        "filter_project": filter_project,
        "filter_status": filter_status,
        "changes": changes,
        "keywords": [],         # bulk mode: no keyword search
        "hint_project": filter_project,
        "hint_status": filter_status,
        "hint_domain": None,
        "ambiguous": False,
    }
