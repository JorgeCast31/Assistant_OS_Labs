"""
Chaperón - Capa intermedia entre clasificador y backend.

El Chaperón se ejecuta DESPUÉS del clasificador primario y ANTES del backend ejecutor.

Responsabilidades:
1. Detectar múltiples montos/intents en un solo mensaje (multi-FIN)
2. Manejar fragmentos de continuación ("y 15 para los conejos")
3. Mantener contexto de sesión mínimo
4. Generar action_plans estructurados
5. Solicitar confirmación cuando hay ambigüedad

El Chaperón NO:
- Hace inferencias creativas
- Modifica el backend
- Ejecuta acciones directamente
"""
import re
from datetime import date
from typing import TypedDict, Optional, Literal

from .config import FIN_RESPONSIBLES


# ---------------------------------------------------------------------------
# TypedDicts for Chaperon
# ---------------------------------------------------------------------------

class FinItem(TypedDict):
    """Un item de gasto individual detectado."""
    monto: float
    moneda: str
    categoria: Optional[str]
    responsable: Optional[str]
    descripcion: Optional[str]
    raw_segment: str  # El fragmento de texto original


class SessionContext(TypedDict, total=False):
    """Contexto de sesión mínimo para continuación."""
    last_domain: Optional[str]       # Último dominio procesado
    last_moneda: Optional[str]       # Última moneda usada (USD/PAB)
    last_fecha: Optional[str]        # Última fecha (YYYY-MM-DD)
    last_action_type: Optional[str]  # Tipo de última acción
    

class ClarificationQuestion(TypedDict):
    """Pregunta de clarificación."""
    field: str          # Campo que necesita clarificación
    question: str       # Pregunta para el usuario
    options: list[str]  # Opciones válidas (si aplica)


class ActionPlan(TypedDict):
    """Plan de acción generado por el Chaperón."""
    type: Literal["single_fin", "multi_fin", "continuation", "ambiguous", "passthrough"]
    items: list[FinItem]
    requires_confirmation: bool
    clarification_questions: list[ClarificationQuestion]
    inherited_context: SessionContext
    summary_text: str  # Resumen legible para confirmación


class ChaperonResponse(TypedDict):
    """Respuesta completa del Chaperón."""
    action_plan: ActionPlan
    should_execute: bool  # False si requiere confirmación
    confirmation_message: Optional[str]  # Mensaje para usuario si necesita confirmar
    raw_text: str
    detected_domain: str


# ---------------------------------------------------------------------------
# Regex Patterns for Multi-Monto Detection
# ---------------------------------------------------------------------------

# Patrones para detectar montos con contexto
MONTO_PATTERNS = [
    # $25, $ 25, $25.50
    r"(\$\s*\d+(?:[.,]\d{1,2})?)",
    # 25$, 25 $ (dollar after number)
    r"(\d+(?:[.,]\d{1,2})?\s*\$)",
    # B/.25, B/. 25, B/.25.50
    r"(B/\.?\s*\d+(?:[.,]\d{1,2})?)",
    # 25 dólares/dolares
    r"(\d+(?:[.,]\d{1,2})?\s*d[oó]lare?s?)",
    # 25 balboas
    r"(\d+(?:[.,]\d{1,2})?\s*balboas?)",
    # USD 25, US$25
    r"(US[D$]\s*\d+(?:[.,]\d{1,2})?)",
]

# Patrones para segmentar múltiples gastos
SEGMENTATION_PATTERNS = [
    r"\by\s+\d",           # "y 15" - continuation
    r",\s*\d+\s*\$",       # ", 15$"
    r",\s*\$\s*\d+",       # ", $15"
    r"\by\s+\$",           # "y $15"
    r"\by\s+B/",           # "y B/."
    r"\bm[aá]s\s+\d",      # "más 15"
    r"\btambi[eé]n\s+\d",  # "también 15"
]

# Palabras clave de continuación
CONTINUATION_STARTERS = [
    r"^y\s+",              # "y 15 para..."
    r"^m[aá]s\s+",         # "más 15"
    r"^tambi[eé]n\s+",     # "también 15"
    r"^otro\s+",           # "otro gasto"
    r"^otra\s+",           # "otra compra"
]

# Responsables canónicos (para detección)
RESPONSABLES_LOWER = {r.lower(): r for r in FIN_RESPONSIBLES}
RESPONSABLES_ALIASES = {
    "yo": "Jorge",
    "mi": "Jorge",
    "conejo": "Conejos",
    "mascotas": "Conejos",
    "mascota": "Conejos",
    "casa": "Hogar",
    "proyecto": "Proyectos",
    "prota": "eiProta",
}

# Categorías por keywords
CATEGORIA_KEYWORDS = {
    "Comida": [r"\bcomida\b", r"\bcena\b", r"\balmuerzo\b", r"\brestaurante\b", r"\bsupermercado\b", r"\bsuper\b"],
    "Transporte": [r"\btaxi\b", r"\buber\b", r"\bgas\b", r"\bcombustible\b", r"\btransporte\b"],
    "Salud": [r"\bfarmacia\b", r"\bmedicina\b", r"\bm[eé]dico\b", r"\bdoctor\b"],
    "Mascotas": [r"\bconejos?\b", r"\bmascota[s]?\b", r"\bperro\b", r"\bgato\b", r"\bveterinari"],
    "Hogar": [r"\bcasa\b", r"\bhogar\b", r"\balquiler\b", r"\brenta\b", r"\bmuebles?\b"],
    "Software": [r"\bsoftware\b", r"\bsuscripci[oó]n\b", r"\blicencia\b", r"\bapp\b"],
    "Servicios": [r"\binternet\b", r"\bluz\b", r"\belectricidad\b", r"\bteléfono\b", r"\bagua\b"],
    "Entretenimiento": [r"\bcine\b", r"\bpel[ií]cula\b", r"\bjuego\b", r"\bconcierto\b"],
    "Educación": [r"\bcurso\b", r"\bclase\b", r"\blibro\b", r"\beducaci[oó]n\b"],
}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _extract_montos_with_positions(text: str) -> list[tuple[float, str, int, int]]:
    """
    Extrae TODOS los montos del texto con sus posiciones.
    
    Returns:
        Lista de (monto, moneda, start_pos, end_pos)
    """
    results = []
    
    # USD patterns - $ before number
    for match in re.finditer(r"\$\s*(\d+(?:[.,]\d{1,2})?)", text):
        monto = float(match.group(1).replace(",", "."))
        results.append((monto, "USD", match.start(), match.end()))
    
    # USD patterns - $ after number (25$)
    for match in re.finditer(r"(\d+(?:[.,]\d{1,2})?)\s*\$", text):
        monto = float(match.group(1).replace(",", "."))
        # Avoid duplicates from overlapping patterns
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "USD", match.start(), match.end()))
    
    for match in re.finditer(r"US\$\s*(\d+(?:[.,]\d{1,2})?)", text, re.IGNORECASE):
        monto = float(match.group(1).replace(",", "."))
        # Avoid duplicates from overlapping patterns
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "USD", match.start(), match.end()))
    
    for match in re.finditer(r"(\d+(?:[.,]\d{1,2})?)\s*d[oó]lare?s?", text, re.IGNORECASE):
        monto = float(match.group(1).replace(",", "."))
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "USD", match.start(), match.end()))
    
    # PAB patterns
    for match in re.finditer(r"B/\.?\s*(\d+(?:[.,]\d{1,2})?)", text):
        monto = float(match.group(1).replace(",", "."))
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "PAB", match.start(), match.end()))
    
    for match in re.finditer(r"(\d+(?:[.,]\d{1,2})?)\s*balboas?", text, re.IGNORECASE):
        monto = float(match.group(1).replace(",", "."))
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "PAB", match.start(), match.end()))

    # M26-A FIX: Bare numbers (no currency symbol) — USD assumed in FIN context.
    # This is checked last so the dedup guard prevents double-matching numbers
    # that were already captured by a currency-symbol pattern above.
    # Lookbehind excludes positions immediately after letters, digits, or
    # currency characters to avoid matching inside compound tokens (e.g. "v3.0",
    # "B/.50").  Lookahead excludes the same set plus "." to avoid version strings.
    for match in re.finditer(
        r"(?<![A-Za-z\d/$€£¥.])(\d+(?:[.,]\d{1,2})?)(?![A-Za-z\d/$€£¥.])",
        text,
    ):
        monto = float(match.group(1).replace(",", "."))
        if not any(r[2] <= match.start() < r[3] for r in results):
            results.append((monto, "USD", match.start(), match.end()))

    # Sort by position
    results.sort(key=lambda x: x[2])
    return [(m, c, s, e) for m, c, s, e in results]


def _detect_responsable(text: str) -> Optional[str]:
    """Detecta responsable en un segmento de texto."""
    text_lower = text.lower()
    
    # Check "para X" pattern
    match = re.search(r"\bpara\s+(los?\s+)?(\w+)", text_lower)
    if match:
        word = match.group(2)
        if word in RESPONSABLES_LOWER:
            return RESPONSABLES_LOWER[word]
        if word in RESPONSABLES_ALIASES:
            return RESPONSABLES_ALIASES[word]
    
    # Check "responsable: X" pattern
    match = re.search(r"\bresponsable\s*:?\s*(\w+)", text_lower)
    if match:
        word = match.group(1)
        if word in RESPONSABLES_LOWER:
            return RESPONSABLES_LOWER[word]
        if word in RESPONSABLES_ALIASES:
            return RESPONSABLES_ALIASES[word]
    
    # Check direct mentions
    for alias, canonical in RESPONSABLES_ALIASES.items():
        if re.search(rf"\b{alias}\b", text_lower):
            return canonical
    
    for resp_lower, resp_canonical in RESPONSABLES_LOWER.items():
        if re.search(rf"\b{resp_lower}\b", text_lower):
            return resp_canonical
    
    return None


def _detect_categoria(text: str) -> Optional[str]:
    """Detecta categoría por keywords en un segmento de texto."""
    text_lower = text.lower()
    
    for categoria, patterns in CATEGORIA_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return categoria
    
    return None


def _is_continuation_fragment(text: str) -> bool:
    """Detecta si el texto es un fragmento de continuación."""
    text_lower = text.lower().strip()
    
    for pattern in CONTINUATION_STARTERS:
        if re.match(pattern, text_lower):
            return True
    
    # También es continuación si no tiene verbo pero sí monto
    # Check known currency patterns
    has_currency_monto = any(re.search(p, text) for p in MONTO_PATTERNS)
    
    # Also check for bare numbers at the start (e.g., "15 para conejos")
    has_bare_number = re.match(r"^\d+(?:[.,]\d{1,2})?\s+", text.strip())
    
    has_monto = has_currency_monto or has_bare_number
    has_verb = re.search(r"\b(gast[eéoó]|compr[eéoó]|pagu[eé]|costó|cost[oó]|pagando|comprar|gastar|pagar)\b", text_lower)
    
    if has_monto and not has_verb:
        return True
    
    return False


def _segment_multi_expense(text: str) -> list[str]:
    """
    Segmenta un texto con múltiples gastos en fragmentos individuales.
    
    Ejemplo:
        "25$ en comida y 15$ para los conejos"
        → ["25$ en comida", "15$ para los conejos"]
    """
    # Find all amount positions
    montos = _extract_montos_with_positions(text)
    
    if len(montos) <= 1:
        return [text]
    
    segments = []
    
    for i, (monto, moneda, start, end) in enumerate(montos):
        # Find segment boundaries
        if i == 0:
            seg_start = 0
        else:
            # Start from end of previous segment
            prev_end = montos[i-1][3]
            # Find connector between segments
            between = text[prev_end:start]
            # Look for "y", ",", "más", "también"
            connector_match = re.search(r"(,|\by\b|\bm[aá]s\b|\btambi[eé]n\b)", between, re.IGNORECASE)
            if connector_match:
                seg_start = prev_end + connector_match.end()
            else:
                seg_start = prev_end
        
        if i == len(montos) - 1:
            seg_end = len(text)
        else:
            # End before next connector
            next_start = montos[i+1][2]
            between = text[end:next_start]
            connector_match = re.search(r"(,|\by\b|\bm[aá]s\b|\btambi[eé]n\b)", between, re.IGNORECASE)
            if connector_match:
                seg_end = end + connector_match.start()
            else:
                seg_end = next_start
        
        segment = text[seg_start:seg_end].strip()
        if segment:
            segments.append(segment)
    
    return segments if segments else [text]


# Explicit currency markers — if none present, a bare number was matched by the
# M26-A fallback with a default "USD" assignment that should be overridden by
# inherited_moneda when provided.
_EXPLICIT_CURRENCY_RE = re.compile(
    r"\$|US\$|B/\.?|\bd[oó]lares?\b|\bbalboas?\b",
    re.IGNORECASE,
)


def _build_fin_item(segment: str, inherited_moneda: Optional[str] = None) -> FinItem:
    """Construye un FinItem a partir de un segmento de texto."""
    montos = _extract_montos_with_positions(segment)

    if montos:
        monto, moneda, _, _ = montos[0]
        # M26-A assigns "USD" to bare numbers by default.  If no explicit currency
        # marker is present in the segment and inherited_moneda is provided, the
        # inherited value takes precedence over the fallback "USD".
        if inherited_moneda and not _EXPLICIT_CURRENCY_RE.search(segment):
            moneda = inherited_moneda
    else:
        # Try to extract just a number (for continuation fragments)
        match = re.search(r"(\d+(?:[.,]\d{1,2})?)", segment)
        monto = float(match.group(1).replace(",", ".")) if match else 0.0
        moneda = inherited_moneda or "USD"
    
    return FinItem(
        monto=monto,
        moneda=moneda,
        categoria=_detect_categoria(segment),
        responsable=_detect_responsable(segment),
        descripcion=None,  # Will be extracted by backend
        raw_segment=segment,
    )


def _generate_confirmation_message(items: list[FinItem]) -> str:
    """Genera mensaje de confirmación para múltiples items."""
    if not items:
        return ""
    
    lines = [f"Detecté {len(items)} gasto{'s' if len(items) > 1 else ''}:"]
    
    for i, item in enumerate(items, 1):
        cat = item["categoria"] or "?"
        resp = item["responsable"] or "?"
        lines.append(f"{i}) {item['moneda']} {item['monto']:.2f} | {cat} | {resp}")
    
    lines.append("")
    lines.append("¿Confirmar? (sí / editar / cancelar)")
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main Chaperon Function
# ---------------------------------------------------------------------------

def run_chaperon(
    text: str,
    domain: str,
    session_context: Optional[SessionContext] = None,
) -> ChaperonResponse:
    """
    Ejecuta el Chaperón sobre el texto clasificado.
    
    Args:
        text: Texto original del usuario
        domain: Dominio detectado por el clasificador
        session_context: Contexto de sesión previo (opcional)
    
    Returns:
        ChaperonResponse con action_plan y flags de confirmación
    """
    session = session_context or SessionContext()
    
    # If not FIN domain, passthrough
    if domain != "FIN":
        return ChaperonResponse(
            action_plan=ActionPlan(
                type="passthrough",
                items=[],
                requires_confirmation=False,
                clarification_questions=[],
                inherited_context=session,
                summary_text="",
            ),
            should_execute=True,
            confirmation_message=None,
            raw_text=text,
            detected_domain=domain,
        )
    
    # Check if this is a continuation fragment
    is_continuation = _is_continuation_fragment(text)
    
    # If continuation and we have previous FIN context
    if is_continuation and session.get("last_domain") == "FIN":
        inherited_moneda = session.get("last_moneda", "USD")
        item = _build_fin_item(text, inherited_moneda)
        
        # Update item with inherited context
        new_context = SessionContext(
            last_domain="FIN",
            last_moneda=item["moneda"],
            last_fecha=session.get("last_fecha"),
            last_action_type="continuation",
        )
        
        # Check if we have enough info
        questions: list[ClarificationQuestion] = []
        if not item["responsable"]:
            questions.append(ClarificationQuestion(
                field="responsable",
                question="¿Quién es el responsable de este gasto?",
                options=list(FIN_RESPONSIBLES),
            ))
        
        return ChaperonResponse(
            action_plan=ActionPlan(
                type="continuation",
                items=[item],
                requires_confirmation=len(questions) > 0,
                clarification_questions=questions,
                inherited_context=new_context,
                summary_text=_generate_confirmation_message([item]) if len(questions) > 0 else "",
            ),
            should_execute=len(questions) == 0,
            confirmation_message=_generate_confirmation_message([item]) if len(questions) > 0 else None,
            raw_text=text,
            detected_domain="FIN",
        )
    
    # Check for multiple amounts
    montos = _extract_montos_with_positions(text)
    
    if len(montos) > 1:
        # Multi-expense detected
        segments = _segment_multi_expense(text)
        items = [_build_fin_item(seg) for seg in segments]
        
        # Always require confirmation for multi-expense
        new_context = SessionContext(
            last_domain="FIN",
            last_moneda=items[0]["moneda"] if items else "USD",
            last_fecha=None,
            last_action_type="multi_fin",
        )
        
        return ChaperonResponse(
            action_plan=ActionPlan(
                type="multi_fin",
                items=items,
                requires_confirmation=True,
                clarification_questions=[],
                inherited_context=new_context,
                summary_text=_generate_confirmation_message(items),
            ),
            should_execute=False,
            confirmation_message=_generate_confirmation_message(items),
            raw_text=text,
            detected_domain="FIN",
        )
    
    # Single expense - passthrough to backend
    if len(montos) == 1:
        item = _build_fin_item(text)
        
        new_context = SessionContext(
            last_domain="FIN",
            last_moneda=item["moneda"],
            last_fecha=None,
            last_action_type="single_fin",
        )
        
        return ChaperonResponse(
            action_plan=ActionPlan(
                type="single_fin",
                items=[item],
                requires_confirmation=False,
                clarification_questions=[],
                inherited_context=new_context,
                summary_text="",
            ),
            should_execute=True,
            confirmation_message=None,
            raw_text=text,
            detected_domain="FIN",
        )
    
    # No monto found - ambiguous or passthrough
    return ChaperonResponse(
        action_plan=ActionPlan(
            type="passthrough",
            items=[],
            requires_confirmation=False,
            clarification_questions=[],
            inherited_context=session,
            summary_text="",
        ),
        should_execute=True,
        confirmation_message=None,
        raw_text=text,
        detected_domain=domain,
    )


def confirm_action_plan(
    action_plan: ActionPlan,
    confirmations: dict[str, str],
) -> ActionPlan:
    """
    Actualiza un action_plan con las confirmaciones del usuario.
    
    Args:
        action_plan: Plan original
        confirmations: Dict con campo -> valor confirmado
    
    Returns:
        ActionPlan actualizado
    """
    updated_items = []
    
    for i, item in enumerate(action_plan["items"]):
        new_item = dict(item)
        
        # Apply confirmations
        if f"responsable_{i}" in confirmations:
            new_item["responsable"] = confirmations[f"responsable_{i}"]
        if f"categoria_{i}" in confirmations:
            new_item["categoria"] = confirmations[f"categoria_{i}"]
        
        updated_items.append(FinItem(**new_item))
    
    return ActionPlan(
        type=action_plan["type"],
        items=updated_items,
        requires_confirmation=False,  # Already confirmed
        clarification_questions=[],   # Cleared
        inherited_context=action_plan["inherited_context"],
        summary_text="",
    )


def update_session_context(
    current: Optional[SessionContext],
    chaperon_response: ChaperonResponse,
) -> SessionContext:
    """
    Actualiza el contexto de sesión después de procesar un mensaje.
    
    Solo guarda información mínima estructurada, no texto libre.
    """
    new_context = chaperon_response["action_plan"]["inherited_context"]
    
    # Merge with current if exists
    if current:
        if not new_context.get("last_fecha"):
            new_context["last_fecha"] = current.get("last_fecha")
    
    return new_context
