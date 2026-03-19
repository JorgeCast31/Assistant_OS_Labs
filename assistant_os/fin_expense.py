"""
FIN Expense Module - Extract structured expense data from natural language.

Extracts:
- fecha (date, default today)
- monto (float amount)
- moneda (USD if $, PAB if B/. or "balboa")
- descripcion (what was spent on)
- responsable (Ana/Jorge/eiProta/hogar)
- itbms (bool) + percentage if specified
- categoria (auto-categorized by keywords)
"""
import re
from datetime import date, datetime
from typing import TypedDict, Optional

from assistant_os.config import FIN_RESPONSIBLES


# ---------------------------------------------------------------------------
# TypedDicts for FIN Expense
# ---------------------------------------------------------------------------

class ExpenseOverride(TypedDict, total=False):
    """Optional overrides from user."""
    responsable: str
    fecha: str
    moneda: str
    itbms: bool
    metodo_pago: str


class ExpenseRequest(TypedDict, total=False):
    """Request body for POST /fin/expense."""
    text: str          # Required
    override: ExpenseOverride
    session_id: str


class ParsedExpense(TypedDict):
    """Structured expense data - parsed from text before storage."""
    fecha: str              # YYYY-MM-DD
    monto: Optional[float]  # None if not found
    moneda: str             # USD|PAB
    descripcion: str        # What was bought (cleaned)
    responsable: str        # Ana|Jorge|eiProta|Hogar|Conejos|Proyectos|unknown
    itbms: Optional[bool]   # Whether ITBMS applies (None if not mentioned)
    itbms_pct: Optional[float]  # ITBMS percentage if found (7% default)
    categoria: str          # Auto-categorized
    proveedor: str          # Vendor if found
    metodo_pago: str        # Payment method: yappy|efectivo|tarjeta|transferencia|ach|nequi|""
    raw_text: str           # Original text
    mes: str                # YYYY-MM derived from fecha
    factura: str            # Invoice/receipt ID (empty for text, filled for OCR)
    notas: str              # Additional notes
    fuente: str             # "chat"|"receipt" - source of expense
    link_archivo: str       # Link to receipt file (future: for OCR)


class ExpenseResponse(TypedDict):
    """Response for POST /fin/expense - includes parsing and storage status."""
    ok: bool
    expense: Optional[ParsedExpense]
    needs_confirmation: bool  # True if missing required fields
    missing_fields: list      # List of missing required field names
    ambiguous_responsables: list  # If multiple responsables detected
    message: str              # Human-readable status
    # Storage status fields
    stored: bool              # True if written to Sheets
    status: str               # "stored"|"needs_confirmation"|"sheets_unavailable"|"error"
    sheets_available: bool    # True if Sheets integration is working
    row_number: Optional[int] # Row number in Sheets (if stored)
    tab_name: str             # Sheets tab name
    sheets_error: Optional[dict]  # Error details if sheets failed


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Canonical responsables from config (case-sensitive canonical forms)
RESPONSABLES = [r.lower() for r in FIN_RESPONSIBLES]  # For matching
RESPONSABLES_CANONICAL = {r.lower(): r for r in FIN_RESPONSIBLES}  # lowercase -> canonical

# Alias mappings: variant -> canonical (lowercase key)
RESPONSABLE_ALIASES = {
    # Jorge aliases
    "yo": "Jorge",
    "mi": "Jorge",
    
    # Conejos aliases
    "conejo": "Conejos",
    "mascotas": "Conejos",
    "mascota": "Conejos",
    
    # Hogar aliases
    "casa": "Hogar",
    
    # Proyectos aliases
    "proyecto": "Proyectos",
    
    # eiProta aliases
    "ei prota": "eiProta",
    "prota": "eiProta",
}

CATEGORIAS = {
    "comida": [
        r"\bcomida\b", r"\bcena\b", r"\balmuerzo\b", r"\bdesayuno\b",
        r"\brestaurante\b", r"\bcafe\b", r"\bcafé\b", r"\bsnack[s]?\b",
        r"\bpizza\b", r"\bhamburguesa\b", r"\bcerveza\b", r"\btrago[s]?\b",
        r"\bbar\b", r"\btapas\b",
    ],
    "supermercado": [
        r"\bsupermercado\b", r"\bsuper\b", r"\bmercado\b", r"\bvíveres\b",
        r"\bcompras?\b", r"\bdespensa\b", r"\bsupplies\b",
    ],
    "transporte": [
        r"\btaxi\b", r"\buber\b", r"\bcabify\b", r"\bgas(olina)?\b",
        r"\bcombustible\b", r"\bparqueo\b", r"\bpeaje\b", r"\bmetro\b",
        r"\bbus\b", r"\btransporte\b", r"\bpassaje\b", r"\bpasaje\b",
    ],
    "software": [
        r"\bsoftware\b", r"\bsubscripci[oó]n\b", r"\bsuscripci[oó]n\b",
        r"\blicencia\b", r"\bapp\b", r"\baplicaci[oó]n\b", r"\bcloud\b",
        r"\bsaas\b", r"\bapi\b", r"\bhosting\b", r"\bdominio\b",
        r"\bcursor\b", r"\bgithub\b", r"\bopenai\b", r"\banthropic\b",
    ],
    "servicios": [
        r"\binternet\b", r"\btelefon[ío]a?\b", r"\bcelular\b", r"\bluz\b",
        r"\belectricidad\b", r"\bagua\b", r"\bgas\b", r"\bcable\b",
        r"\bstreaming\b", r"\bnetflix\b", r"\bspotify\b",
    ],
    "salud": [
        r"\bfarmacia\b", r"\bmedicina\b", r"\bmédico\b", r"\bmedico\b",
        r"\bdoctor\b", r"\bconsulta\b", r"\breceta\b", r"\bhospital\b",
        r"\bclínica\b", r"\bclinica\b", r"\bdentista\b", r"\bgym\b",
    ],
    "hogar": [
        r"\balquiler\b", r"\brenta\b", r"\bmuebles?\b", r"\belectrodom[eé]sticos?\b",
        r"\blimpieza\b", r"\bmantenimiento\b", r"\breparaci[oó]n\b",
    ],
    "entretenimiento": [
        r"\bcine\b", r"\bpelícula\b", r"\bpelicula\b", r"\bjuego[s]?\b",
        r"\bvideojuego\b", r"\bconcierto\b", r"\bteatro\b", r"\bevento\b",
    ],
    "ropa": [
        r"\bropa\b", r"\bzapatos?\b", r"\bcamisa\b", r"\bpantal[oó]n\b",
        r"\bvestido\b", r"\btienda\b", r"\bmoda\b",
    ],
    "educacion": [
        r"\bcurso\b", r"\bclase[s]?\b", r"\blibro[s]?\b", r"\beducaci[oó]n\b",
        r"\buniversidad\b", r"\bcapacitaci[oó]n\b", r"\btaller\b",
    ],
    "mascotas": [
        r"\bmascota[s]?\b", r"\bperro\b", r"\bgato\b", r"\bveterinari[oa]?\b",
        r"\bcomida\s+de\s+mascota\b", r"\bconejos?\b",
    ],
    "otros": [],  # Fallback
}

# Normalized payment method names (internal key, patterns)
# Each specific method maps to itself, not grouped
METODOS_PAGO = {
    "efectivo": [r"\befectivo\b", r"\bcash\b"],
    "tarjeta": [r"\btarjeta\b", r"\bcr[eé]dito\b", r"\bd[eé]bito\b", r"\bvisa\b", r"\bmastercard\b"],
    "transferencia": [r"\btransferencia\b", r"\bwire\b", r"\bach\b", r"\bnequi\b"],
    "yappy": [r"\byappy\b"],
}

# -----------------------------------------------------------
# CANONICAL MAPPINGS - Exact dropdown values in Google Sheets
# -----------------------------------------------------------

# Categoría dropdown: Comida, Transporte, Software, Salud, Hogar, Mascotas, Educación, Servicios, Entretenimiento, Otros
CATEGORIA_CANONICAL = {
    "comida": "Comida",
    "supermercado": "Comida",       # Map to Comida
    "transporte": "Transporte",
    "software": "Software",
    "servicios": "Servicios",
    "salud": "Salud",
    "hogar": "Hogar",
    "mascotas": "Mascotas",
    "entretenimiento": "Entretenimiento",
    "educacion": "Educación",
    "ropa": "Otros",                # Not in dropdown, map to Otros
    "otros": "Otros",
}

CATEGORIA_DEFAULT = "Otros"

# Método de Pago dropdown: Efectivo, Tarjeta, Transferencia, Yappy, Otro
METODO_PAGO_CANONICAL = {
    "efectivo": "Efectivo",
    "tarjeta": "Tarjeta",
    "transferencia": "Transferencia",
    "yappy": "Yappy",
    "": "",  # No method specified - keep empty
}

METODO_PAGO_DEFAULT = "Otro"


# ---------------------------------------------------------------------------
# Extraction Functions
# ---------------------------------------------------------------------------

def _extract_monto(text: str) -> tuple[Optional[float], str]:
    """
    Extract amount and currency from text.
    
    Patterns:
    - $50, $ 50, $50.00
    - B/.50, B/. 50, B/.50.00
    - 50 dólares / dolares
    - 50 balboas
    - USD 50, US$50
    
    Returns:
        (monto, moneda) - moneda is "USD" or "PAB"
    """
    text_lower = text.lower()
    
    # Pattern: $50 or $ 50 (USD)
    match = re.search(r"\$\s*(\d+(?:[.,]\d{1,2})?)", text)
    if match:
        monto_str = match.group(1).replace(",", ".")
        return float(monto_str), "USD"
    
    # Pattern: US$50
    match = re.search(r"US\$\s*(\d+(?:[.,]\d{1,2})?)", text, re.IGNORECASE)
    if match:
        monto_str = match.group(1).replace(",", ".")
        return float(monto_str), "USD"
    
    # Pattern: USD 50
    match = re.search(r"\bUSD?\s*(\d+(?:[.,]\d{1,2})?)", text, re.IGNORECASE)
    if match:
        monto_str = match.group(1).replace(",", ".")
        return float(monto_str), "USD"
    
    # Pattern: B/.50 or B/. 50 (PAB - Balboa)
    match = re.search(r"B/\.?\s*(\d+(?:[.,]\d{1,2})?)", text)
    if match:
        monto_str = match.group(1).replace(",", ".")
        return float(monto_str), "PAB"
    
    # Pattern: "50 dólares" or "50 dolares"
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*d[oó]lare?s?", text_lower)
    if match:
        monto_str = match.group(1).replace(",", ".")
        return float(monto_str), "USD"
    
    # Pattern: "50 balboas"
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*balboas?", text_lower)
    if match:
        monto_str = match.group(1).replace(",", ".")
        return float(monto_str), "PAB"
    
    # Fallback: any number (assume USD)
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", text)
    if match:
        monto_str = match.group(1).replace(",", ".")
        return float(monto_str), "USD"
    
    return None, "USD"


def _get_panama_date() -> date:
    """
    Get current date in America/Panama timezone.
    Panama is UTC-5 (no daylight saving).
    """
    from datetime import timezone, timedelta
    utc_now = datetime.now(timezone.utc)
    # Panama is UTC-5
    panama_tz = timezone(timedelta(hours=-5))
    panama_now = utc_now.astimezone(panama_tz)
    return panama_now.date()


def _extract_fecha(text: str) -> str:
    """
    Extract date from text.
    
    Patterns:
    - "hoy", "ayer"
    - "24/02/2026", "2026-02-24"
    - "24 de febrero"
    
    Returns:
        Date string in YYYY-MM-DD format, defaults to today (Panama timezone).
    """
    text_lower = text.lower()
    today = _get_panama_date()
    
    # "ayer"
    if re.search(r"\bayer\b", text_lower):
        from datetime import timedelta
        yesterday = today - timedelta(days=1)
        return yesterday.isoformat()
    
    # Pattern: DD/MM/YYYY
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            d = date(year, month, day)
            return d.isoformat()
        except ValueError:
            pass
    
    # Pattern: YYYY-MM-DD
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            d = date(year, month, day)
            return d.isoformat()
        except ValueError:
            pass
    
    # Default to today
    return today.isoformat()


def _extract_responsable(text: str) -> tuple[str, list[str]]:
    """
    Extract responsable from text with alias normalization.
    
    Supports:
    - Direct names: Ana, Conejos, Jorge, eiProta, Proyectos, Hogar
    - Aliases: yo→Jorge, conejos/conejo/mascotas→Conejos, casa→Hogar, etc.
    
    Returns:
        (canonical_name, all_matches) where:
        - canonical_name is the normalized form or "unknown" if none
        - all_matches is the list of all detected responsables (for ambiguity)
    """
    text_lower = text.lower()
    found: list[str] = []
    
    # 1. Check for direct canonical names (case-insensitive)
    for resp_lower, resp_canonical in RESPONSABLES_CANONICAL.items():
        # Handle "eiProta" which becomes "eiprota" in lowercase
        pattern = rf"\b{re.escape(resp_lower)}\b"
        if re.search(pattern, text_lower):
            if resp_canonical not in found:
                found.append(resp_canonical)
    
    # 2. Check for aliases
    for alias, canonical in RESPONSABLE_ALIASES.items():
        pattern = rf"\b{re.escape(alias)}\b"
        if re.search(pattern, text_lower):
            if canonical not in found:
                found.append(canonical)
    
    if len(found) == 0:
        return "unknown", []
    elif len(found) == 1:
        return found[0], found
    else:
        # Multiple responsables detected - ambiguous
        # Return first but include all for caller to handle
        return found[0], found


def _extract_itbms(text: str) -> tuple[Optional[bool], Optional[float]]:
    """
    Extract ITBMS (Panama tax) info.
    
    Patterns for NO ITBMS:
    - "itbms: no", "itbms: no.", "itbms no"
    - "sin itbms", "no itbms"
    
    Patterns for ITBMS:
    - "itbms si", "itbms: si", "con itbms", "itbms 7%"
    
    Returns:
        (itbms_bool_or_none, itbms_percentage_or_none)
        Returns (None, None) if ITBMS not mentioned at all.
    """
    text_lower = text.lower()
    
    # Check for explicit "no itbms", "sin itbms", or "itbms: no" / "itbms no"
    # Added colon and optional period support
    if re.search(r"\b(sin\s+itbms|itbms\s*:\s*no\.?|itbms\s+no|no\s+itbms)\b", text_lower):
        return False, None
    
    # Check for "itbms" presence (si, con, or percentage)
    if re.search(r"\b(con\s+itbms|itbms\s*:\s*s[ií]\.?|itbms\s+s[ií])\b", text_lower):
        # Try to find percentage
        match = re.search(r"itbms\s*(\d+(?:\.\d+)?)\s*%?", text_lower)
        if match:
            return True, float(match.group(1))
        return True, 7.0  # Default Panama ITBMS
    
    # Check for percentage pattern
    match = re.search(r"itbms\s*(\d+(?:\.\d+)?)\s*%", text_lower)
    if match:
        return True, float(match.group(1))
    
    # ITBMS not mentioned at all - return None
    return None, None


def _extract_categoria(text: str) -> str:
    """
    Auto-categorize expense based on keywords.
    Returns the CANONICAL category name matching dropdown.
    """
    text_lower = text.lower()
    
    for categoria_key, patterns in CATEGORIAS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                # Convert to canonical form for dropdown
                return CATEGORIA_CANONICAL.get(categoria_key, CATEGORIA_DEFAULT)
    
    return CATEGORIA_DEFAULT


def _extract_descripcion(text: str) -> str:
    """
    Extract description - what was the expense for.
    
    Heuristic: Remove known entities (amount, responsable, date, itbms, metadata labels)
    and return cleaned text.
    """
    # Start with original text
    desc = text
    
    # Remove money patterns
    desc = re.sub(r"\$\s*\d+(?:[.,]\d{1,2})?", "", desc)
    desc = re.sub(r"US\$\s*\d+(?:[.,]\d{1,2})?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bUSD?\s*\d+(?:[.,]\d{1,2})?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"B/\.?\s*\d+(?:[.,]\d{1,2})?", "", desc)
    desc = re.sub(r"\d+(?:[.,]\d{1,2})?\s*d[oó]lare?s?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\d+(?:[.,]\d{1,2})?\s*balboas?", "", desc, flags=re.IGNORECASE)
    
    # Remove metadata labels with their values (Responsable: X, Moneda: X, ITBMS: X, Método: X)
    # These patterns match "Label: value" or "Label value" where value is a single word
    desc = re.sub(r"\bResponsable\s*:?\s*\S+\.?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bMoneda\s*:?\s*(PAB|USD|pab|usd)\.?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bITBMS\s*:\s*\S+\.?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bM[eé]todo\s*:\s*\S+\.?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bM[eé]todo\s+de\s+[Pp]ago\s*:\s*\S+\.?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bFecha\s*:\s*\S+\.?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bCategor[ií]a\s*:\s*\S+\.?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bFuente\s*:\s*\S+\.?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bNotas?\s*:\s*\S+\.?", "", desc, flags=re.IGNORECASE)
    
    # Remove responsable mentions (standalone names without label)
    for resp in RESPONSABLES:
        # Remove "del RESPONSABLE" pattern (e.g., "del hogar")
        desc = re.sub(rf"\bdel\s+{resp}\b", "", desc, flags=re.IGNORECASE)
        # Remove standalone responsable
        desc = re.sub(rf"\b{resp}\b", "", desc, flags=re.IGNORECASE)
    
    # Remove ITBMS mentions (standalone, various formats)
    desc = re.sub(r"\b(con\s+)?itbms(\s*:\s*\S+|\s+s[ií]|\s+no|\s+\d+%?)?\b\.?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bsin\s+itbms\b", "", desc, flags=re.IGNORECASE)
    
    # Remove common verbs
    desc = re.sub(r"^(pagu[eé]|gast[eéoó]|compr[eéoó]|ped[ií])\s*", "", desc, flags=re.IGNORECASE)
    
    # Remove "en", "del", "de la" at start
    desc = re.sub(r"^(en|del|de\s+la)\s+", "", desc, flags=re.IGNORECASE)
    
    # Clean up whitespace and punctuation
    desc = re.sub(r"\s*[,;]\s*", " ", desc)
    desc = re.sub(r"\s+", " ", desc).strip()
    # Remove trailing punctuation
    desc = re.sub(r"[.,;:]+$", "", desc).strip()
    # Remove orphan prepositions left from responsable removal
    desc = re.sub(r"\b(del|de\s+la|de)\s+(en|de|del)\b", "", desc, flags=re.IGNORECASE)
    # Remove leading "en" or "del" again after cleanup
    desc = re.sub(r"^(en|del|de\s+la)\s+", "", desc, flags=re.IGNORECASE).strip()
    
    return desc if desc else "Gasto sin descripción"


def _extract_proveedor(text: str) -> str:
    """
    Try to extract vendor/provider name.
    Very basic - looks for capitalized words or known vendors.
    """
    # Known vendors
    known_vendors = [
        "uber", "cabify", "didi", "netflix", "spotify", "amazon",
        "github", "openai", "anthropic", "cursor", "vercel",
        "mcdonalds", "wendys", "kfc", "starbucks", "pizzahut",
    ]
    
    text_lower = text.lower()
    for vendor in known_vendors:
        if vendor in text_lower:
            return vendor.capitalize()
    
    return ""


def _extract_metodo_pago(text: str) -> str:
    """Extract payment method if mentioned und return CANONICAL form for dropdown."""
    text_lower = text.lower()
    
    for metodo_key, patterns in METODOS_PAGO.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                # Convert to canonical form for dropdown
                return METODO_PAGO_CANONICAL.get(metodo_key, METODO_PAGO_DEFAULT)
    
    return ""  # No method specified


# ---------------------------------------------------------------------------
# Main Parsing Function
# ---------------------------------------------------------------------------

def parse_expense(request: ExpenseRequest) -> ExpenseResponse:
    """
    Parse natural language expense into structured data.
    
    Args:
        request: ExpenseRequest with 'text' and optional 'override'
    
    Returns:
        ExpenseResponse with parsed expense and confirmation status
    """
    text = request.get("text", "")
    override = request.get("override", {})
    
    if not text.strip():
        return ExpenseResponse(
            ok=False,
            expense=None,
            needs_confirmation=False,
            missing_fields=["text"],
            ambiguous_responsables=[],
            message="No text provided",
            stored=False,
            status="error",
            sheets_available=False,
            row_number=None,
            tab_name="",
            sheets_error=None,
        )
    
    # Extract all fields
    monto, moneda = _extract_monto(text)
    fecha = _extract_fecha(text)
    responsable, all_responsables = _extract_responsable(text)
    itbms, itbms_pct = _extract_itbms(text)
    categoria = _extract_categoria(text)
    descripcion = _extract_descripcion(text)
    proveedor = _extract_proveedor(text)
    metodo_pago = _extract_metodo_pago(text)
    
    # Track ambiguity
    ambiguous_responsables: list[str] = []
    if len(all_responsables) > 1:
        ambiguous_responsables = all_responsables
    
    # Apply overrides
    if override.get("responsable"):
        # Normalize override to canonical form
        override_resp = override["responsable"]
        override_lower = override_resp.lower()
        if override_lower in RESPONSABLES_CANONICAL:
            responsable = RESPONSABLES_CANONICAL[override_lower]
        else:
            responsable = override_resp  # Keep as-is if not recognized
        ambiguous_responsables = []  # Clear ambiguity on explicit override
    if override.get("fecha"):
        fecha = override["fecha"]
    if override.get("moneda"):
        moneda = override["moneda"].upper()
    if "itbms" in override:
        itbms = override["itbms"]
    if override.get("metodo_pago"):
        # Normalize override to canonical form
        metodo_lower = override["metodo_pago"].lower()
        metodo_pago = METODO_PAGO_CANONICAL.get(metodo_lower, METODO_PAGO_DEFAULT)
    
    # Derive mes from fecha (YYYY-MM)
    mes = fecha[:7] if len(fecha) >= 7 else ""
    
    # Build parsed expense with all fields
    expense = ParsedExpense(
        fecha=fecha,
        monto=monto,
        moneda=moneda,
        descripcion=descripcion,
        responsable=responsable,
        itbms=itbms,
        itbms_pct=itbms_pct,
        categoria=categoria,
        proveedor=proveedor,
        metodo_pago=metodo_pago,
        raw_text=text,
        mes=mes,
        factura="",           # Empty for text-based expenses (future: OCR)
        notas="",             # Empty unless provided
        fuente="chat",        # Text-based input
        link_archivo="",      # Empty (future: receipt file link)
    )
    
    # Determine missing required fields
    missing_fields = []
    if monto is None:
        missing_fields.append("monto")
    if responsable == "unknown":
        missing_fields.append("responsable")
    if itbms is None:
        missing_fields.append("itbms")
    
    # Need confirmation if missing fields OR ambiguous responsable
    needs_confirmation = len(missing_fields) > 0 or len(ambiguous_responsables) > 1
    
    # Build message
    if len(ambiguous_responsables) > 1:
        message = f"Múltiples responsables detectados: {', '.join(ambiguous_responsables)}. Por favor selecciona uno."
    elif needs_confirmation:
        message = f"Faltan campos requeridos: {', '.join(missing_fields)}"
    else:
        message = f"Gasto de {moneda} {monto:.2f} en {descripcion} ({categoria})"
    
    # Return response - storage fields will be added by webhook handler
    return ExpenseResponse(
        ok=True,
        expense=expense,
        needs_confirmation=needs_confirmation,
        missing_fields=missing_fields,
        ambiguous_responsables=ambiguous_responsables,
        message=message,
        # Placeholder storage fields - will be updated by webhook after storage attempt
        stored=False,
        status="needs_confirmation" if needs_confirmation else "pending",
        sheets_available=False,  # Will be updated by webhook
        row_number=None,
        tab_name="",
        sheets_error=None,
    )
