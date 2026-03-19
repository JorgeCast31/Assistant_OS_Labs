"""
FIN Plan Module - "Plan Always" Architecture.

Every FIN input goes through /fin/plan FIRST.
No direct execution from text → Sheets.
Number of forms = number of detected montos.

Flow:
1. POST /fin/plan → generates action_plan with N items
2. User confirms via UI
3. POST /fin/commit per item → stores each to Sheets
"""
import re
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import TypedDict, Optional

from .config import FIN_RESPONSIBLES


# ---------------------------------------------------------------------------
# TypedDicts for Plan Always
# ---------------------------------------------------------------------------

class DraftExpense(TypedDict):
    """Draft expense data before confirmation."""
    fecha: str              # YYYY-MM-DD
    monto: float            # Extracted amount
    moneda: str             # USD|PAB
    descripcion: str        # What was bought
    responsable: str        # Ana|Jorge|eiProta|Hogar|Conejos|Proyectos|unknown
    categoria: str          # Auto-categorized
    metodo_pago: str        # efectivo|tarjeta|yappy|transferencia|""
    itbms: bool             # Whether ITBMS applies


class PlanItem(TypedDict):
    """A single item in the action plan."""
    id: str                       # UUID for this item
    draft_expense: DraftExpense   # Pre-filled expense data
    missing_fields: list[str]     # Fields that need user input
    confidence: float             # 0-1 confidence score
    raw_segment: str              # Original text segment


class FinPlanResponse(TypedDict):
    """Response from POST /fin/plan."""
    ok: bool
    kind: str                     # "fin_plan" | "needs_clarification"
    mode: str                     # "single" | "multi"
    total_items: int              # Number of items detected
    message: str                  # Human-readable summary
    items: list[PlanItem]         # List of detected expense items
    needs_clarification: bool     # True if no montos found
    clarification_prompt: str     # Question to ask if needs clarification
    session_context: dict         # Context to preserve


class FinCommitRequest(TypedDict, total=False):
    """Request for POST /fin/commit."""
    expense: DraftExpense         # Complete expense to store
    session_id: str               # Session ID for logging


class FinCommitResponse(TypedDict):
    """Response from POST /fin/commit."""
    ok: bool
    stored: bool                  # True if written to Sheets
    row_number: Optional[int]     # Row number in Sheets
    sheet: str                    # Sheet tab name
    message: str                  # Human-readable status
    error: Optional[str]          # Error message if any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESPONSABLES_CANONICAL = {r.lower(): r for r in FIN_RESPONSIBLES}
RESPONSABLES_LOWER = {r.lower(): r for r in FIN_RESPONSIBLES}

RESPONSABLE_ALIASES = {
    "yo": "Jorge",
    "mi": "Jorge",
    "conejo": "Conejos",
    "mascotas": "Conejos",
    "mascota": "Conejos",
    "casa": "Hogar",
    "proyecto": "Proyectos",
    "prota": "eiProta",
}

CATEGORIAS = {
    "comida": [
        r"\bcomida\b", r"\bcena\b", r"\balmuerzo\b", r"\bdesayuno\b",
        r"\brestaurante\b", r"\bcafe\b", r"\bcafé\b", r"\bsnack[s]?\b",
    ],
    "supermercado": [
        r"\bsupermercado\b", r"\bsuper\b", r"\bmercado\b", r"\bvíveres\b",
    ],
    "transporte": [
        r"\btaxi\b", r"\buber\b", r"\bcabify\b", r"\bgas(olina)?\b",
        r"\bcombustible\b", r"\bparqueo\b", r"\bpeaje\b",
    ],
    "software": [
        r"\bsoftware\b", r"\bsuscripci[oó]n\b", r"\blicencia\b", r"\bapp\b",
    ],
    "salud": [
        r"\bfarmacia\b", r"\bmedicina\b", r"\bm[eé]dico\b", r"\bdoctor\b",
    ],
    "mascotas": [
        r"\bmascota[s]?\b", r"\bconejos?\b", r"\bperro\b", r"\bgato\b",
        r"\bveterinari",
    ],
    "hogar": [
        r"\balquiler\b", r"\brenta\b", r"\bmuebles?\b", r"\bcasa\b",
    ],
    "servicios": [
        r"\binternet\b", r"\bluz\b", r"\belectricidad\b", r"\bagua\b",
    ],
}

# Canonical mapping for categories
CATEGORIA_CANONICAL = {
    "comida": "Comida",
    "supermercado": "Comida",
    "transporte": "Transporte",
    "software": "Software",
    "salud": "Salud",
    "mascotas": "Mascotas",
    "hogar": "Hogar",
    "servicios": "Servicios",
}

METODOS_PAGO_PATTERNS = {
    "Efectivo": [r"\befectivo\b", r"\bcash\b"],
    "Tarjeta": [r"\btarjeta\b", r"\bcr[eé]dito\b", r"\bd[eé]bito\b"],
    "Yappy": [r"\byappy\b"],
    "Transferencia": [r"\btransferencia\b", r"\bach\b", r"\bnequi\b"],
}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _get_panama_date() -> date:
    """Get current date in Panama timezone (UTC-5)."""
    utc_now = datetime.now(timezone.utc)
    panama_tz = timezone(timedelta(hours=-5))
    return utc_now.astimezone(panama_tz).date()


def _extract_montos_with_positions(text: str) -> list[tuple[float, str, int, int]]:
    """
    Extract ALL amounts from text with positions.
    
    Returns:
        List of (monto, moneda, start_pos, end_pos)
    """
    results = []
    
    # USD: $25, $ 25
    for match in re.finditer(r"\$\s*(\d+(?:[.,]\d{1,2})?)", text):
        monto = float(match.group(1).replace(",", "."))
        results.append((monto, "USD", match.start(), match.end()))
    
    # USD: 25$ (dollar after number)
    for match in re.finditer(r"(\d+(?:[.,]\d{1,2})?)\s*\$", text):
        monto = float(match.group(1).replace(",", "."))
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "USD", match.start(), match.end()))
    
    # USD: US$25
    for match in re.finditer(r"US\$\s*(\d+(?:[.,]\d{1,2})?)", text, re.IGNORECASE):
        monto = float(match.group(1).replace(",", "."))
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "USD", match.start(), match.end()))
    
    # USD: N dólares
    for match in re.finditer(r"(\d+(?:[.,]\d{1,2})?)\s*d[oó]lare?s?", text, re.IGNORECASE):
        monto = float(match.group(1).replace(",", "."))
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "USD", match.start(), match.end()))
    
    # PAB: B/.25, B/. 25
    for match in re.finditer(r"B/\.?\s*(\d+(?:[.,]\d{1,2})?)", text):
        monto = float(match.group(1).replace(",", "."))
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "PAB", match.start(), match.end()))
    
    # PAB: N balboas
    for match in re.finditer(r"(\d+(?:[.,]\d{1,2})?)\s*balboas?", text, re.IGNORECASE):
        monto = float(match.group(1).replace(",", "."))
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "PAB", match.start(), match.end()))
    
    # Sort by position
    results.sort(key=lambda x: x[2])
    return results


# ---------------------------------------------------------------------------
# Structural count patterns - numbers that describe quantity of items, not amounts
# ---------------------------------------------------------------------------
STRUCTURAL_COUNT_PATTERNS = [
    # "3 gastos", "5 items", "2 cosas"
    r"\b(\d+)\s+(gasto|gastos|item|items|cosa|cosas|compra|compras|pago|pagos|transacci[oó]n|transacciones)\b",
    # "son 3", "son 5"
    r"\bson\s+(\d+)\b",
    # "tengo 3", "tengo 5"
    r"\btengo\s+(\d+)\b",
    # "fueron 3", "hay 4"
    r"\b(fueron|hay|hice|hicimos)\s+(\d+)\b",
]


def _is_structural_count(text: str, num_start: int, num_end: int) -> bool:
    """
    Check if a number at the given position is a structural count (not a monetary amount).
    
    Examples of structural counts:
    - "3 gastos" → True
    - "son 5" → True
    - "tengo 2" → True
    
    Returns True if the number should be excluded from monetary clarification.
    """
    text_lower = text.lower()
    
    for pattern in STRUCTURAL_COUNT_PATTERNS:
        for match in re.finditer(pattern, text_lower, re.IGNORECASE):
            # Check if our number falls within this structural match
            if match.start() <= num_start < match.end() or match.start() < num_end <= match.end():
                return True
            # Also check if the number directly overlaps with any group in the match
            for group_idx in range(len(match.groups())):
                try:
                    g_start, g_end = match.span(group_idx + 1)
                    if g_start <= num_start < g_end or g_start < num_end <= g_end:
                        return True
                except:
                    pass
    
    return False


def _has_entity_association(text: str, num_start: int, num_end: int) -> bool:
    """
    Check if a number is associated with an entity name (potential responsable).
    
    Examples:
    - "15 ana" → True (should ask if it's a monto)
    - "25 los conejos" → True
    - "3 gastos" → False (structural)
    
    Returns True if the number is followed by capitalized words or likely entity names.
    """
    after_text = text[num_end:min(len(text), num_end + 30)].strip()
    
    # Check if followed by a capitalized word (potential name)
    if re.match(r"^\s*[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+", after_text):
        # Make sure it's not a structural word
        first_word = re.match(r"^\s*([A-Za-záéíóúñÁÉÍÓÚÑ]+)", after_text)
        if first_word:
            word = first_word.group(1).lower()
            structural_words = {
                'gasto', 'gastos', 'item', 'items', 'cosa', 'cosas',
                'compra', 'compras', 'pago', 'pagos', 'transaccion', 'transacciones'
            }
            if word not in structural_words:
                return True
    
    # Check for "para [entity]" or "[entity]" patterns
    if re.match(r"^\s*(?:para\s+)?(?:la|el|los|las)?\s*[A-Za-záéíóúñÁÉÍÓÚÑ]+", after_text, re.IGNORECASE):
        first_phrase = re.match(r"^\s*(?:para\s+)?(?:la|el|los|las)?\s*([A-Za-záéíóúñÁÉÍÓÚÑ]+)", after_text, re.IGNORECASE)
        if first_phrase:
            word = first_phrase.group(1).lower()
            structural_words = {
                'gasto', 'gastos', 'item', 'items', 'cosa', 'cosas',
                'compra', 'compras', 'pago', 'pagos', 'transaccion', 'transacciones',
                'de', 'en', 'por', 'con'
            }
            if word not in structural_words:
                return True
    
    return False


def _detect_unsymboled_numbers(
    text: str, 
    monto_positions: list[tuple[float, str, int, int]]
) -> list[dict]:
    """
    Detect numbers in text that are NOT part of detected monetary amounts.
    
    Excludes structural counts like "3 gastos", "son 5", "tengo 2".
    Includes numbers associated with entities like "15 ana", "25 los conejos".
    
    Returns a list of:
        { 'number': float, 'start': int, 'end': int, 'context': str, 
          'is_percentage': bool, 'has_entity': bool, 'classification': str }
    """
    # Find all numbers in text (including decimals)
    number_pattern = r"(\d+(?:[.,]\d{1,2})?)"
    results = []
    
    # Build set of positions consumed by montos
    consumed_ranges = []
    for _, _, start, end in monto_positions:
        consumed_ranges.append((start, end))
    
    for match in re.finditer(number_pattern, text):
        num_start = match.start()
        num_end = match.end()
        
        # Check if this number is already part of a monto
        is_consumed = any(
            start <= num_start < end or start < num_end <= end
            for start, end in consumed_ranges
        )
        if is_consumed:
            continue
        
        # Check if this is a structural count (exclude from clarification)
        if _is_structural_count(text, num_start, num_end):
            continue
        
        # Get context around the number (15 chars before and after)
        ctx_start = max(0, num_start - 15)
        ctx_end = min(len(text), num_end + 15)
        context = text[ctx_start:ctx_end].strip()
        
        # Check if it's a percentage (% immediately after)
        after_num = text[num_end:num_end + 5] if num_end < len(text) else ""
        is_percentage = bool(re.match(r"\s*%", after_num))
        
        # Check if associated with an entity
        has_entity = _has_entity_association(text, num_start, num_end)
        
        number_val = float(match.group(1).replace(",", "."))
        
        # Filter out likely non-monetary numbers (dates, times)
        before = text[max(0, num_start-3):num_start]
        after = text[num_end:min(len(text), num_end+3)]
        if re.search(r"[/\-]$", before) or re.search(r"^[/\-]", after):
            continue  # Likely a date
        
        # Skip times (e.g., "3:00")
        if re.search(r":$", before) or re.search(r"^:", after):
            continue
        
        # Determine classification
        if is_percentage:
            classification = "PERCENTAGE"
        elif has_entity:
            classification = "ENTITY_AMOUNT"
        else:
            classification = "AMBIGUOUS_NUMBER"
        
        results.append({
            'number': number_val,
            'start': num_start,
            'end': num_end,
            'context': context,
            'is_percentage': is_percentage,
            'has_entity': has_entity,
            'classification': classification,
            'raw': match.group(0),
        })
    
    return results


def _build_clarification_prompt(num_info: dict, prefix: str = "") -> str:
    """
    Build a natural, clear clarification prompt for an ambiguous number.
    
    Different templates based on classification:
    - PERCENTAGE: Ask if it's a percentage or a monetary amount
    - ENTITY_AMOUNT: Ask if the number is an amount for that entity
    - AMBIGUOUS_NUMBER: Generic question about whether it's a monto
    
    Args:
        num_info: Dictionary with number info from _detect_unsymboled_numbers
        prefix: Optional prefix like "También " for secondary questions
    
    Returns:
        Natural language clarification prompt
    """
    number = num_info['number']
    raw = num_info['raw']
    context = num_info['context']
    classification = num_info.get('classification', 'AMBIGUOUS_NUMBER')
    
    # Clean prefix (lowercase if not starting)
    if prefix:
        start_word = prefix.strip().lower()
        if start_word.startswith("también"):
            prefix = "También "
        else:
            prefix = prefix.capitalize()
    
    if classification == "PERCENTAGE":
        # Percentage: always ask specifically
        return (
            f"{prefix}vi '{raw}%' en tu mensaje. "
            f"¿Es un porcentaje o quisiste decir ${number:.0f}? "
            "Si es un monto, indica con $ (ej: ${:.0f}).".format(number)
        )
    
    elif classification == "ENTITY_AMOUNT":
        # Entity-associated: likely a monto for someone
        return (
            f"{prefix}vi '{raw}' cerca de '{context}'. "
            f"¿Son ${number:.0f}?"
        )
    
    else:  # AMBIGUOUS_NUMBER
        # Generic ambiguous number
        return (
            f"{prefix}vi el número '{raw}' en tu mensaje. "
            f"¿Es un monto de ${number:.0f}?"
        )


def _segment_text_by_montos(text: str, montos: list[tuple[float, str, int, int]]) -> list[str]:
    """
    Segment text into parts, one per monto.
    
    Each segment contains text describing that specific expense.
    For multiple montos with a preface pattern (e.g., "Tengo 3 gastos:"), 
    the preface is excluded from item 1.
    """
    if not montos:
        return [text.strip()]
    
    if len(montos) == 1:
        # For single monto, use full text - _extract_descripcion will clean it
        return [text.strip()]
    
    segments = []
    first_monto_start = montos[0][2]
    
    # Check if there's a preface pattern before the first monto
    # Patterns: "Hoy tuve varios gastos, ...", "Tengo 3 gastos: ...", etc.
    preface_text = text[:first_monto_start]
    preface_end_offset = 0
    
    # Look for explicit separators like ":" or common preface patterns
    if ':' in preface_text:
        colon_pos = preface_text.rfind(':')
        preface_end_offset = colon_pos + 1
    else:
        # Look for preface patterns ANYWHERE in text before first monto
        # Pattern: "varios gastos," or "3 gastos," - find and skip past it
        pattern_match = re.search(r'\b(varios|algunos|unos|\d+)\s+gastos?,\s*', preface_text, re.IGNORECASE)
        if pattern_match:
            # Found preface pattern - first segment starts after this pattern
            # But we need to find the actual start of first item description
            # Look for comma just before the first monto position
            text_before_monto = text[:first_monto_start]
            # Find last comma before the first monto
            last_comma = text_before_monto.rfind(',')
            if last_comma > pattern_match.start():
                preface_end_offset = last_comma + 1
    
    for i, (monto, moneda, start, end) in enumerate(montos):
        # Find segment start
        if i == 0:
            # For first monto: start after preface if detected, else include from near monto
            if preface_end_offset > 0:
                seg_start = preface_end_offset
            else:
                # No clear preface - include text from beginning or find natural boundary
                seg_start = 0
        else:
            prev_end = montos[i-1][3]
            between = text[prev_end:start]
            # Find connector (", y ", ", ")
            match = re.search(r'(,\s*|\by\b|\bm[aá]s\b|\btambi[eé]n\b)\s*', between, re.IGNORECASE)
            if match:
                seg_start = prev_end + match.end()
            else:
                seg_start = prev_end
        
        # Segment end
        if i == len(montos) - 1:
            seg_end = len(text)
        else:
            next_start = montos[i+1][2]
            between = text[end:next_start]
            match = re.search(r'(,|\by\b|\bm[aá]s\b|\btambi[eé]n\b)', between, re.IGNORECASE)
            if match:
                seg_end = end + match.start()
            else:
                seg_end = next_start
        
        segment = text[seg_start:seg_end].strip()
        if segment:
            segments.append(segment)
    
    return segments if segments else [text.strip()]


def _detect_responsable(text: str) -> str:
    """Detect responsable from text segment."""
    text_lower = text.lower()
    
    # Check "para X" pattern
    match = re.search(r"\bpara\s+(los?\s+)?(\w+)", text_lower)
    if match:
        word = match.group(2)
        if word in RESPONSABLES_LOWER:
            return RESPONSABLES_LOWER[word]
        if word in RESPONSABLE_ALIASES:
            return RESPONSABLE_ALIASES[word]
    
    # Check "responsable: X" pattern  
    match = re.search(r"\bresponsable\s*:?\s*(\w+)", text_lower)
    if match:
        word = match.group(1)
        if word in RESPONSABLES_LOWER:
            return RESPONSABLES_LOWER[word]
        if word in RESPONSABLE_ALIASES:
            return RESPONSABLE_ALIASES[word]
    
    # Check aliases
    for alias, canonical in RESPONSABLE_ALIASES.items():
        if re.search(rf"\b{alias}\b", text_lower):
            return canonical
    
    # Check direct mentions
    for resp_lower, resp_canonical in RESPONSABLES_LOWER.items():
        if re.search(rf"\b{resp_lower}\b", text_lower):
            return resp_canonical
    
    return "Jorge"


def _detect_categoria(text: str) -> str:
    """Detect category from text segment."""
    text_lower = text.lower()
    
    for cat_key, patterns in CATEGORIAS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return CATEGORIA_CANONICAL.get(cat_key, "Otros")
    
    return "Otros"


def _detect_metodo_pago(text: str) -> str:
    """Detect payment method from text."""
    text_lower = text.lower()
    
    for canonical, patterns in METODOS_PAGO_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return canonical
    
    return ""


def _detect_itbms(text: str) -> bool:
    """Detect if ITBMS mentioned."""
    text_lower = text.lower()
    
    # Explicit no
    if re.search(r"\bitbms\s*:\s*no\b", text_lower):
        return False
    if re.search(r"\bsin\s+itbms\b", text_lower):
        return False
    
    # Explicit yes
    if re.search(r"\bitbms\s*:\s*s[ií]\b", text_lower):
        return True
    if re.search(r"\bcon\s+itbms\b", text_lower):
        return True
    
    # Default: false (not mentioned)
    return False


def _extract_fecha(text: str) -> str:
    """Extract date from text, default to today."""
    text_lower = text.lower()
    today = _get_panama_date()
    
    # "ayer"
    if re.search(r"\bayer\b", text_lower):
        return (today - timedelta(days=1)).isoformat()
    
    # DD/MM/YYYY
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass
    
    # YYYY-MM-DD
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass
    
    return today.isoformat()


def _extract_descripcion(text: str) -> str:
    """Extract description from text segment."""
    # Remove currency patterns
    desc = re.sub(r"\$\s*\d+(?:[.,]\d{1,2})?", "", text)
    desc = re.sub(r"\d+\s*\$", "", desc)
    desc = re.sub(r"B/\.?\s*\d+(?:[.,]\d{1,2})?", "", desc)
    desc = re.sub(r"\d+\s*d[oó]lare?s?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\d+\s*balboas?", "", desc, flags=re.IGNORECASE)
    
    # Remove metadata
    desc = re.sub(r"\bresponsable\s*:\s*\w+", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bmoneda\s*:\s*\w+", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bitbms\s*:\s*\w+", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bm[eé]todo\s*:\s*\w+", "", desc, flags=re.IGNORECASE)
    
    # Strip leading whitespace before verb removal so that currency-pattern
    # removal (which can leave a leading space) does not prevent the ^ anchor
    # from matching.  Example: "$25 compré café" → " compré café" after currency
    # strip; without this strip, ^compr[eé] would fail to match.
    desc = desc.strip()

    # Remove leading transaction verbs ("compré café" → "café", "gasté en taxi" → "taxi").
    # Pattern covers: compré/compre, compró/compro, compramos; gasté/gaste/gasto; pagué/pague
    desc = re.sub(r"^compr(?:amos|[eéóo])\s+", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"^gast[oóeé]\s+(en\s+)?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"^pagu[eé]\s+(en\s+)?", "", desc, flags=re.IGNORECASE)

    # Remove payment method phrases so they don't bleed into the description.
    # Examples: "almuerzo con tarjeta" → "almuerzo",
    #           "cena pagada con tarjeta" → "cena",
    #           "café en efectivo" → "café".
    # Require leading whitespace (\s+) so we never strip the expense noun itself.
    desc = re.sub(r"\s+pagad[ao]s?\s+(?:con|en|por)\s+(?:la\s+)?(?:tarjeta|efectivo|yappy|transferencia|cr[eé]dito|d[eé]bito)\b", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+(?:con|en|por|de|via)\s+(?:la\s+)?tarjeta(?:\s+de\s+(?:cr[eé]dito|d[eé]bito))?\b", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+(?:con|en|de)\s+efectivo\b", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+(?:con|en|de)\s+cash\b", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+(?:con|por|v[ií]a?)\s+yappy\b", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+(?:por|v[ií]a?|con)\s+transferencia\b", "", desc, flags=re.IGNORECASE)

    # Clean up
    desc = re.sub(r"[,\.]+$", "", desc.strip())
    desc = " ".join(desc.split())
    
    return desc or "Gasto"


def _calculate_confidence(draft: DraftExpense, missing: list[str]) -> float:
    """Calculate confidence score for draft expense."""
    score = 1.0
    
    # Deduct for missing fields
    if "monto" in missing:
        score -= 0.4
    if "responsable" in missing or draft["responsable"] == "unknown":
        score -= 0.2
    if "categoria" in missing or draft["categoria"] == "Otros":
        score -= 0.1
    if not draft["descripcion"] or draft["descripcion"] == "Gasto":
        score -= 0.1
    
    return max(0.0, min(1.0, score))


def _build_plan_item(segment: str, monto: float, moneda: str) -> PlanItem:
    """Build a PlanItem from a text segment and extracted monto."""
    fecha = _extract_fecha(segment)
    responsable = _detect_responsable(segment)
    categoria = _detect_categoria(segment)
    metodo_pago = _detect_metodo_pago(segment)
    itbms = _detect_itbms(segment)
    descripcion = _extract_descripcion(segment)
    
    draft = DraftExpense(
        fecha=fecha,
        monto=monto,
        moneda=moneda,
        descripcion=descripcion,
        responsable=responsable,
        categoria=categoria,
        metodo_pago=metodo_pago,
        itbms=itbms,
    )
    
    # Determine missing fields
    missing: list[str] = []
    if monto == 0:
        missing.append("monto")
    if responsable == "unknown":
        missing.append("responsable")
    
    confidence = _calculate_confidence(draft, missing)
    
    return PlanItem(
        id=str(uuid.uuid4()),
        draft_expense=draft,
        missing_fields=missing,
        confidence=confidence,
        raw_segment=segment,
    )


# ---------------------------------------------------------------------------
# Main Functions
# ---------------------------------------------------------------------------

def generate_fin_plan(text: str, session_context: Optional[dict] = None) -> FinPlanResponse:
    """
    Generate a FIN plan from text.
    
    This is the ONLY entry point for FIN domain.
    Always returns a plan, never executes directly.
    
    Args:
        text: User input text
        session_context: Previous session context (for continuations)
    
    Returns:
        FinPlanResponse with action plan
    """
    session = session_context or {}
    text = text.strip()
    
    if not text:
        return FinPlanResponse(
            ok=False,
            kind="error",
            mode="single",
            total_items=0,
            message="No se proporcionó texto.",
            items=[],
            needs_clarification=False,
            clarification_prompt="",
            session_context=session,
        )
    
    # Extract all montos
    montos = _extract_montos_with_positions(text)

    # Detect numbers without monetary symbols (potential ambiguous amounts)
    unsymboled_numbers = _detect_unsymboled_numbers(text, montos)

    # Loop-prevention: skip candidate-amount clarification if caller already resolved one
    skip_candidate = session.get("skip_candidate_clarification", False)

    # No montos found → needs clarification
    if not montos:
        # Check if there are unsymboled numbers we could ask about
        if unsymboled_numbers and not skip_candidate:
            # Single non-percentage candidate → high-confidence suggestion
            non_pct = [n for n in unsymboled_numbers if not n["is_percentage"]]
            if len(non_pct) == 1:
                cand = non_pct[0]
                cand_amount = cand["number"]
                message = f"Vi un posible monto: ${cand_amount:.0f}. ¿Quieres usar ese monto?"
                clarification = _build_clarification_prompt(cand)
                pending_clarification: dict = {
                    "kind": "unsymboled_numbers",
                    "numbers": unsymboled_numbers,
                    "original_text": text,
                    "candidate_amount": cand_amount,   # single clear candidate
                }
            else:
                prompts = []
                for num_info in unsymboled_numbers[:3]:  # Limit to 3
                    prompts.append(_build_clarification_prompt(num_info))
                clarification = "\n".join(prompts)
                message = "No detecté montos con símbolo ($, B/.). Vi algunos números que podrían ser montos."
                pending_clarification = {
                    "kind": "unsymboled_numbers",
                    "numbers": unsymboled_numbers,
                    "original_text": text,
                }
            return FinPlanResponse(
                ok=True,
                kind="needs_clarification",
                mode="single",
                total_items=0,
                message=message,
                items=[],
                needs_clarification=True,
                clarification_prompt=clarification,
                session_context={
                    **session,
                    "pending_clarification": pending_clarification,
                },
            )
        
        return FinPlanResponse(
            ok=True,
            kind="needs_clarification",
            mode="single",
            total_items=0,
            message="No detecté ningún monto en el mensaje.",
            items=[],
            needs_clarification=True,
            clarification_prompt="¿Cuál es el monto del gasto?",
            session_context={
                **session,
                "pending_clarification": {
                    "kind": "missing_amount",
                    "original_text": text,
                },
            },
        )
    
    # Segment text by montos
    segments = _segment_text_by_montos(text, montos)
    
    # Build plan items
    items: list[PlanItem] = []
    for i, (monto, moneda, _, _) in enumerate(montos):
        segment = segments[i] if i < len(segments) else text
        item = _build_plan_item(segment, monto, moneda)
        items.append(item)
    
    # Check for unsymboled numbers that might require clarification
    clarification_needed = False
    clarification_prompts = []
    
    if unsymboled_numbers:
        for num_info in unsymboled_numbers:
            # Only ask about numbers that look like they could be amounts (> 1)
            if num_info['number'] >= 1:
                clarification_needed = True
                clarification_prompts.append(_build_clarification_prompt(num_info, prefix="También "))
    
    # Generate message - chaperon style
    if len(items) == 1:
        item = items[0]
        draft = item["draft_expense"]
        message = f"Capté 1 gasto: {draft['moneda']} {draft['monto']:.2f} - {draft['descripcion']}."
    else:
        lines = [f"Capté {len(items)} gastos:"]
        for i, item in enumerate(items, 1):
            draft = item["draft_expense"]
            lines.append(f"  {i}) {draft['moneda']} {draft['monto']:.2f} - {draft['descripcion']} ({draft['responsable']})")
        message = "\n".join(lines)
    
    # Add clarification question if needed
    if clarification_needed:
        message += "\n\n" + "\n".join(clarification_prompts)
        message += "\n\nSi los números adicionales no son montos, escribe 'confirmar' para guardar los gastos detectados."
    else:
        message += "\n\n¿Confirmo?"
    
    # Determine mode
    mode = "single" if len(items) == 1 else "multi"
    
    # Update session context
    new_context = {
        "last_domain": "FIN",
        "last_currency": items[0]["draft_expense"]["moneda"] if items else "USD",
        "last_date": items[0]["draft_expense"]["fecha"] if items else _get_panama_date().isoformat(),
        "last_fin_plan_id": items[0]["id"] if items else None,
    }
    
    # Add pending clarification info if needed
    if clarification_needed:
        new_context["pending_clarification"] = {
            "kind": "unsymboled_numbers",
            "numbers": unsymboled_numbers,
            "original_text": text,
        }
    
    return FinPlanResponse(
        ok=True,
        kind="fin_plan",
        mode=mode,
        total_items=len(items),
        message=message,
        items=items,
        needs_clarification=clarification_needed,
        clarification_prompt="\n".join(clarification_prompts) if clarification_prompts else "",
        session_context=new_context,
    )


def add_to_plan(text: str, existing_plan: FinPlanResponse) -> FinPlanResponse:
    """
    Add new items to an existing plan (for continuations like "y 15 para conejos").
    
    Args:
        text: Continuation text
        existing_plan: Current plan to extend
    
    Returns:
        Updated FinPlanResponse with new items added
    """
    # Generate plan for new text
    new_plan = generate_fin_plan(text, existing_plan.get("session_context"))
    
    if not new_plan["ok"] or new_plan["needs_clarification"]:
        return new_plan
    
    # Combine items
    combined_items = list(existing_plan.get("items", [])) + new_plan["items"]
    
    # Generate combined message - chaperon style
    if len(combined_items) == 1:
        draft = combined_items[0]["draft_expense"]
        message = f"Capté 1 gasto: {draft['moneda']} {draft['monto']:.2f} - {draft['descripcion']}. ¿Confirmo?"
    else:
        lines = [f"Capté {len(combined_items)} gastos:"]
        for i, item in enumerate(combined_items, 1):
            draft = item["draft_expense"]
            lines.append(f"  {i}) {draft['moneda']} {draft['monto']:.2f} - {draft['descripcion']} ({draft['responsable']})")
        lines.append("\n¿Confirmo?")
        message = "\n".join(lines)
    
    # Determine mode
    mode = "single" if len(combined_items) == 1 else "multi"
    
    return FinPlanResponse(
        ok=True,
        kind="fin_plan",
        mode=mode,
        total_items=len(combined_items),
        message=message,
        items=combined_items,
        needs_clarification=False,
        clarification_prompt="",
        session_context=new_plan["session_context"],
    )
