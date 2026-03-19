"""
Clasificador determinista (sin LLM) para enrutar mensajes naturales.

DOMINIOS:
- WORK: trabajo institucional formal
- PRO_DIAG: proyecto diagnóstico empresarial independiente
- FIN: dinero personal
- REL: vínculos humanos
- HEALTH: salud física/mental
- EIPROTA: TTI, filosofía, arte, escritura, producción creativa profunda
- ENERGY: meta-sistema, frentes abiertos, carga cognitiva, foco, entropía
"""
import re
from typing import Any

from .contracts import (
    ClassifyRequest, Intent, IntentAlternative,
    OP_WORK_QUERY, OP_WORK_CREATE, OP_WORK_UPDATE, OP_WORK_DELETE, OP_FIN_EXPENSE, OP_COMMAND,
    OP_CODE_EXPLAIN, OP_CODE_REVIEW, OP_CODE_FIX, OP_CODE_CREATE,
)


# ---------------------------------------------------------------------------
# Domain Constants
# ---------------------------------------------------------------------------

DOMAIN_WORK = "WORK"
DOMAIN_PRO_DIAG = "PRO_DIAG"
DOMAIN_FIN = "FIN"
DOMAIN_REL = "REL"
DOMAIN_HEALTH = "HEALTH"
DOMAIN_EIPROTA = "EIPROTA"
DOMAIN_ENERGY = "ENERGY"
DOMAIN_CODE = "CODE"

ALL_DOMAINS = [
    DOMAIN_WORK,
    DOMAIN_PRO_DIAG,
    DOMAIN_FIN,
    DOMAIN_REL,
    DOMAIN_HEALTH,
    DOMAIN_EIPROTA,
    DOMAIN_ENERGY,
    DOMAIN_CODE,
]

# ---------------------------------------------------------------------------
# Type/Impact/CognitiveLoad Constants
# ---------------------------------------------------------------------------

TYPE_IDEA = "Idea"
TYPE_TAREA = "Tarea"
TYPE_REFLEXION = "Reflexión"
TYPE_PROYECTO = "Proyecto"
TYPE_AJUSTE = "Ajuste"

IMPACT_ESTRUCTURAL = "Estructural"
IMPACT_ECONOMICO = "Económico"
IMPACT_EMOCIONAL = "Emocional"
IMPACT_INTELECTUAL = "Intelectual"
IMPACT_OPERATIVO = "Operativo"

COGNITIVE_ALTA = "Alta"
COGNITIVE_MEDIA = "Media"
COGNITIVE_BAJA = "Baja"


# ---------------------------------------------------------------------------
# Keyword Banks with Weights
# ---------------------------------------------------------------------------

# Keywords and weights per domain
# Higher weight = stronger indicator
DOMAIN_KEYWORDS: dict[str, list[tuple[str, float]]] = {
    DOMAIN_WORK: [
        # Strong indicators (3.0+)
        (r"\bincubadora[s]?\b", 3.5),
        (r"\bPOE\b", 4.0),
        (r"\bSOP\b", 3.5),
        (r"\bauditor[ií]a\b", 3.0),
        (r"\bcalibraci[oó]n\b", 3.0),
        (r"\bCELLAB\b", 4.0),
        (r"\bQC\b", 3.0),
        (r"\bISO\b", 3.0),
        (r"\blaboratorio\b", 2.5),
        (r"\bjefe\b", 2.5),
        (r"\boficina\b", 2.0),
        (r"\btrabajo institucional\b", 3.5),
        (r"\bequipo de trabajo\b", 2.5),
        (r"\breport[ea]r\b", 2.0),
        (r"\bproyecto laboral\b", 2.5),
        (r"\bcompañer[oa]s?\b", 2.0),
    ],
    DOMAIN_PRO_DIAG: [
        # Strong indicators
        (r"\bcliente[s]?\b", 3.0),
        (r"\bpropuesta[s]?\b", 2.5),
        (r"\bpricing\b", 3.5),
        (r"\bSaaS\b", 4.0),
        (r"\bdiagn[oó]stico empresarial\b", 4.0),
        (r"\bdiagn[oó]stico\b", 2.5),
        (r"\bconsultor[ií]a\b", 3.5),
        (r"\bentregable[s]?\b", 2.5),
        (r"\bcontrato[s]?\b", 2.5),
        (r"\bfactura[rs]?\b", 2.0),
        (r"\bproyecto independiente\b", 3.0),
        (r"\bfreelance\b", 2.5),
        (r"\bempresa\b", 2.0),
        (r"\bcotizaci[oó]n\b", 2.5),
    ],
    DOMAIN_FIN: [
        # Strong indicators
        (r"\$\s*\d+", 4.0),  # $25, $ 100
        (r"\bgast[oéeaó][s]?\b", 3.5),
        (r"\bd[oó]lar(es)?\b", 3.5),
        (r"\bsaldo\b", 3.0),
        (r"\bpresupuesto\b", 3.5),
        (r"\bdeuda[s]?\b", 3.0),
        (r"\bahorro[s]?\b", 3.0),
        (r"\binversi[oó]n(es)?\b", 2.5),
        (r"\bsalario[s]?\b", 2.5),
        (r"\bdinero\b", 2.5),
        (r"\bpago[s]?\b", 2.0),
        (r"\btarjeta\b", 2.0),
        (r"\bcuenta bancaria\b", 2.5),
        (r"\bproyecci[oó]n(es)?\b", 2.0),
        (r"\bfinanzas\b", 3.0),
        (r"\bingreso[s]?\b", 2.0),
        (r"\begreso[s]?\b", 2.0),
        (r"\bpesos\b", 2.5),
    ],
    DOMAIN_REL: [
        # Strong indicators
        (r"\bAna\b", 4.0),
        (r"\bnovia\b", 3.5),
        (r"\bpareja\b", 3.5),
        (r"\bmam[aá]\b", 3.5),
        (r"\bpap[aá]\b", 3.5),
        (r"\bhermano[sa]?\b", 3.0),
        (r"\bamigo[sa]?\b", 3.0),
        (r"\bfamilia\b", 3.0),
        (r"\bfamiliar(es)?\b", 3.0),
        (r"\bllamar\b", 2.0),
        (r"\bmensaje\b", 2.0),
        (r"\brelaci[oó]n\b", 2.5),
        (r"\bvínculo[s]?\b", 2.5),
        (r"\bnetworking\b", 2.0),
        (r"\bconversar\b", 2.0),
        (r"\bhablar con\b", 2.5),
        (r"\bcita\b", 2.0),
        (r"\bvisitar\b", 2.0),
    ],
    DOMAIN_HEALTH: [
        # Strong indicators
        (r"\bsueño\b", 3.0),
        (r"\bdorm[ií]\b", 3.0),
        (r"\bgym\b", 3.5),
        (r"\bgimnasio\b", 3.0),
        (r"\bcansancio\b", 3.0),
        (r"\bansiedad\b", 3.5),
        (r"\bterapia\b", 3.5),
        (r"\bestr[eé]s\b", 3.0),
        (r"\bsalud\b", 2.5),
        (r"\bejercicio\b", 2.5),
        (r"\brutina\b", 2.0),
        (r"\bh[aá]bito[s]?\b", 2.5),
        (r"\bmeditaci[oó]n\b", 2.5),
        (r"\bdescanso\b", 2.5),
        (r"\benerg[ií]a [fíi]sica\b", 3.0),
        (r"\bfisiol[oó]gic[oa]\b", 2.5),
        (r"\bmental\b", 2.0),
        (r"\bcuerpo\b", 2.0),
    ],
    DOMAIN_EIPROTA: [
        # Strong indicators
        (r"\bTTI\b", 5.0),
        (r"\btensores?\b", 4.0),
        (r"\bcampo\b", 2.0),
        (r"\bontol[oó]gic[oa]\b", 4.0),
        (r"\bfilosof[ií]a\b", 3.5),
        (r"\bobras?\b", 2.5),  # singular and plural
        (r"\bverso[s]?\b", 2.5),
        (r"\bEiProta\b", 5.0),
        (r"\bartístic[oa]\b", 2.5),
        (r"\barte\b", 2.0),
        (r"\bescritura\b", 2.5),
        (r"\bcreaci[oó]n\b", 2.0),
        (r"\bmodelado\b", 2.5),
        (r"\bmodelo\b", 1.5),
        (r"\bensayo\b", 2.0),
        (r"\bproducci[oó]n creativa\b", 3.0),
        (r"\bteor[ií]a\b", 2.0),
        (r"\babstract[oa]?\b", 2.0),
        (r"\bprofund[oa]\b", 1.5),
        (r"\bintelectual\b", 2.0),
    ],
    DOMAIN_ENERGY: [
        # Strong indicators
        (r"\bprioridad(es)?\b", 3.0),
        (r"\bentrop[ií]a\b", 4.0),
        (r"\bfoco\b", 2.5),
        (r"\bcarga cognitiva\b", 4.0),
        (r"\bcarga\b", 2.0),
        (r"\bsaturad[oa]\b", 3.5),
        (r"\bmodo bajo\b", 4.0),
        (r"\bmodo alto\b", 3.5),
        (r"\bfrentes abiertos\b", 4.5),
        (r"\bsistema\b", 2.5),
        (r"\borquestador\b", 4.0),
        (r"\bclasificador\b", 3.5),
        (r"\bmeta-sistema\b", 4.5),
        (r"\bmeta sistema\b", 4.5),
        (r"\bpriorizaci[oó]n\b", 3.0),
        (r"\benfocar\b", 2.5),
        (r"\borganizar tareas\b", 2.5),
        (r"\breducir frentes\b", 3.5),
    ],
}

# Tie-breaker keywords: if present, domain wins over others
TIEBREAKER_KEYWORDS: dict[str, list[str]] = {
    DOMAIN_ENERGY: [
        r"\bsistema\b",
        r"\borquestador\b",
        r"\bclasificador\b",
        r"\bmodo\b",
        r"\bentrop[ií]a\b",
        r"\bmeta-sistema\b",
        r"\bfrentes abiertos\b",
    ],
    DOMAIN_EIPROTA: [
        r"\bTTI\b",
        r"\bartístic[oa]\b",
        r"\bobras?\b",  # singular and plural
        r"\bmis\s+obras\b",  # strong indicator: "mis obras"
        r"\bmodelado\b",
        r"\btensores?\b",
    ],
    DOMAIN_FIN: [
        r"\$\s*\d+",
        r"\bgast[oéeaó]\b",
    ],
}


# ---------------------------------------------------------------------------
# Type Detection Keywords
# ---------------------------------------------------------------------------

# Verbs that indicate a task
TASK_VERBS = [
    r"^haz\b",
    r"^crear?\b",
    r"^generar?\b",
    r"^revisar?\b",
    r"^subir?\b",
    r"^organizar?\b",
    r"^enviar?\b",
    r"^actualizar?\b",
    r"^completar?\b",
    r"^terminar?\b",
    r"^escribir?\b",
    r"^llamar?\b",
    r"^registrar?\b",
    r"^hacer\b",
    r"^agend[ae]r?\b",
    r"^comprar?\b",
    r"^pagar?\b",
    r"^gast[eéaó]\b",  # gasté, gasta, gasto
    r"^program[ae]r?\b",
    r"^prepar[ae]r?\b",
    r"^mejorar?\b",
    r"^continuar?\b",
    r"^salir?\b",
    r"^ir\b",
    r"^planear?\b",
]

PROJECT_KEYWORDS = [
    r"\bproyecto\b",
    r"\bfase[s]?\b",
    r"\broadmap\b",
    r"\bplan\b",
    r"\bplanificaci[oó]n\b",
]

ADJUST_KEYWORDS = [
    r"\bajuste[s]?\b",
    r"\bcambia?r?\b",
    r"\bmodifica?r?\b",
    r"\bmodificar regla\b",
    r"\bajustar\b",
]

REFLECTION_KEYWORDS = [
    r"\bpienso\b",
    r"\breflexio?n[oa]?r?\b",
    r"\bme pregunto\b",
    r"\bcreo que\b",
    r"\bsiento que\b",
]


# ---------------------------------------------------------------------------
# Next Action Templates
# ---------------------------------------------------------------------------

NEXT_ACTIONS: dict[str, str] = {
    DOMAIN_WORK: "Crear tarea en backlog laboral",
    DOMAIN_PRO_DIAG: "Agregar a pipeline de clientes",
    DOMAIN_FIN: "Registrar en tracker financiero",
    DOMAIN_REL: "Agendar recordatorio de contacto",
    DOMAIN_HEALTH: "Añadir a rutina de hábitos",
    DOMAIN_EIPROTA: "Convertir en brief TTI",
    DOMAIN_ENERGY: "Reducir frentes: elegir 1 acción",
}


# ---------------------------------------------------------------------------
# Impact Mapping
# ---------------------------------------------------------------------------

DOMAIN_DEFAULT_IMPACT: dict[str, str] = {
    DOMAIN_WORK: IMPACT_OPERATIVO,
    DOMAIN_PRO_DIAG: IMPACT_ECONOMICO,
    DOMAIN_FIN: IMPACT_ECONOMICO,
    DOMAIN_REL: IMPACT_EMOCIONAL,
    DOMAIN_HEALTH: IMPACT_EMOCIONAL,
    DOMAIN_EIPROTA: IMPACT_INTELECTUAL,
    DOMAIN_ENERGY: IMPACT_ESTRUCTURAL,
}


# ---------------------------------------------------------------------------
# Override Detection Patterns
# ---------------------------------------------------------------------------

# Monetary indicators for FIN override
MONEY_PATTERNS = [
    r"\$\s*\d+",              # $25, $ 100
    r"\d+\s*\$",              # 25$
    r"\bB/\.?\s*\d+",         # B/.50, B/ 50 (Balboa)
    r"\bUSD?\s*\d+",          # USD50, US 50
    r"\bUS\$\s*\d+",          # US$50
    r"\bd[oó]lar(es)?\b",     # dólar, dólares
    r"\bbalboa[s]?\b",        # balboa, balboas
]

# Code/terminal contexts to exclude from FIN override
CODE_EXCLUSIONS = [
    r"\$PATH\b",
    r"\$env:",
    r"\$[A-Z_]+\b",           # $VAR shell variables
    r"\bbash\b",
    r"\bshell\b",
    r"\bPowerShell\b",
    r"\bexport\s+\$",
    r"\becho\s+\$",
    r"\bterminal\b",
    r"\bconsola?\b",
    r"#!/",                    # shebang
]

# TTI/EIPROTA attractor keywords
TTI_ATTRACTOR_KEYWORDS = [
    r"\bTTI\b",
    r"\btensores?\b",
    r"\bcampos?\s+ontol[oó]gic[oa]s?\b",
    r"\bontolog[ií]a\b",
    r"\bEiProta\b",
    r"\bTensor\s+de\s+Intenci[oó]n\b",
    r"\bmodelo\s+(?:de\s+)?tensores?\b",
    r"\bespacio\s+tensorial\b",
]


def _has_money_indicators(text: str) -> bool:
    """Check if text contains monetary indicators."""
    text_lower = text.lower()
    
    # First check for exclusions
    for pattern in CODE_EXCLUSIONS:
        if re.search(pattern, text, re.IGNORECASE):
            return False
    
    # Then check for money patterns
    for pattern in MONEY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    
    return False


def _has_tti_indicators(text: str) -> bool:
    """Check if text contains TTI/EIPROTA attractor keywords."""
    for pattern in TTI_ATTRACTOR_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# ---------------------------------------------------------------------------
# Classification Logic
# ---------------------------------------------------------------------------

def _calculate_domain_scores(text: str) -> dict[str, float]:
    """Calculate scores for each domain based on keyword matches."""
    text_lower = text.lower()
    scores: dict[str, float] = {d: 0.0 for d in ALL_DOMAINS}
    
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for pattern, weight in keywords:
            if re.search(pattern, text_lower, re.IGNORECASE):
                scores[domain] += weight
    
    return scores


def _apply_tiebreakers(text: str, scores: dict[str, float]) -> str | None:
    """Apply tiebreaker rules. Returns winning domain or None."""
    text_lower = text.lower()
    
    # ENERGY wins if meta-system words present
    for pattern in TIEBREAKER_KEYWORDS.get(DOMAIN_ENERGY, []):
        if re.search(pattern, text_lower, re.IGNORECASE):
            # Check if it's really about meta-system, not just "sistema digestivo"
            if re.search(r"\b(meta-?sistema|orquestador|clasificador|entrop|frentes abiertos|modo (bajo|alto))\b", text_lower, re.IGNORECASE):
                return DOMAIN_ENERGY
    
    # EIPROTA wins for TTI/art unless it's meta-system
    for pattern in TIEBREAKER_KEYWORDS.get(DOMAIN_EIPROTA, []):
        if re.search(pattern, text_lower, re.IGNORECASE):
            # Don't override if clearly ENERGY
            if not re.search(r"\b(meta-?sistema|orquestador|clasificador|prioriza)\b", text_lower, re.IGNORECASE):
                return DOMAIN_EIPROTA
    
    # FIN wins if money amounts present (unless just emotional reference)
    for pattern in TIEBREAKER_KEYWORDS.get(DOMAIN_FIN, []):
        if re.search(pattern, text_lower, re.IGNORECASE):
            # Unless it's purely emotional without amounts
            if not (re.search(r"\bme siento\b", text_lower, re.IGNORECASE) and not re.search(r"\$\s*\d+", text_lower)):
                return DOMAIN_FIN
    
    return None


def _get_winner_and_alternatives(scores: dict[str, float]) -> tuple[str, float, list[IntentAlternative]]:
    """Get winning domain, confidence, and alternatives."""
    # Sort by score descending
    sorted_domains = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    # If all scores are 0, default to ENERGY (meta-reflection about system)
    total_score = sum(scores.values())
    if total_score == 0:
        return DOMAIN_ENERGY, 0.5, []
    
    winner = sorted_domains[0][0]
    winner_score = sorted_domains[0][1]
    
    # Calculate confidence using softmax-like normalization
    # confidence = winner_score / sum(top3 scores)
    top3_sum = sum(s for _, s in sorted_domains[:3]) if len(sorted_domains) >= 3 else total_score
    confidence = winner_score / top3_sum if top3_sum > 0 else 0.5
    
    # Cap at 0.99
    confidence = min(confidence, 0.99)
    
    # If winner score is very high (>5.0), boost confidence
    if winner_score >= 5.0:
        confidence = max(confidence, 0.85)
    if winner_score >= 8.0:
        confidence = max(confidence, 0.92)
    
    # Generate alternatives (top 2 others with non-zero scores)
    alternatives: list[IntentAlternative] = []
    for domain, score in sorted_domains[1:3]:
        if score > 0:
            alt_conf = score / top3_sum if top3_sum > 0 else 0.0
            alternatives.append(IntentAlternative(domain=domain, confidence=round(alt_conf, 3)))
    
    return winner, round(confidence, 3), alternatives


def _detect_type(text: str) -> str:
    """Detect message type (Tarea, Proyecto, Ajuste, Reflexión, Idea)."""
    text_lower = text.lower().strip()
    
    # Check for project keywords FIRST (before task verbs)
    for pattern in PROJECT_KEYWORDS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return TYPE_PROYECTO
    
    # Check for task verbs at the start
    for pattern in TASK_VERBS:
        if re.match(pattern, text_lower, re.IGNORECASE):
            return TYPE_TAREA
    
    # Check for adjust keywords
    for pattern in ADJUST_KEYWORDS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return TYPE_AJUSTE
    
    # Check for reflection keywords
    for pattern in REFLECTION_KEYWORDS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return TYPE_REFLEXION
    
    # Default to Idea
    return TYPE_IDEA


def _detect_cognitive_load(text: str, domain: str) -> str:
    """Detect cognitive load (Alta, Media, Baja)."""
    text_lower = text.lower()
    text_len = len(text)
    
    # EIPROTA and ENERGY tend to Alta for complex content
    high_complexity_keywords = [
        r"\bmodelo\b",
        r"\btensores?\b",
        r"\bontol[oó]gic[oa]\b",
        r"\bpresupuesto anual\b",
        r"\breestructurar\b",
        r"\bcambiar rutina completa\b",
        r"\bplan(ificar|eaci[oó]n) (grande|completa|total)\b",
    ]
    
    for pattern in high_complexity_keywords:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return COGNITIVE_ALTA
    
    # Long texts with complex domains tend to Alta
    if domain in (DOMAIN_EIPROTA, DOMAIN_ENERGY) and text_len > 100:
        return COGNITIVE_ALTA
    
    # FIN/REL/HEALTH usually Baja/Media
    if domain in (DOMAIN_FIN, DOMAIN_REL, DOMAIN_HEALTH):
        if text_len < 50:
            return COGNITIVE_BAJA
        return COGNITIVE_MEDIA
    
    # Medium length = Media
    if text_len < 80:
        return COGNITIVE_BAJA
    elif text_len < 200:
        return COGNITIVE_MEDIA
    
    return COGNITIVE_ALTA


def _detect_impact(domain: str, text: str) -> str:
    """Detect impact based on domain and content."""
    text_lower = text.lower()
    
    # HEALTH can be Operativo if it's about routine
    if domain == DOMAIN_HEALTH:
        if re.search(r"\brutina\b", text_lower, re.IGNORECASE):
            return IMPACT_OPERATIVO
    
    # WORK can be Estructural if it's about process
    if domain == DOMAIN_WORK:
        if re.search(r"\bproceso\b|\bPOE\b|\bSOP\b|\breestructur", text_lower, re.IGNORECASE):
            return IMPACT_ESTRUCTURAL
    
    # PRO_DIAG can be Estructural if it involves architecture
    if domain == DOMAIN_PRO_DIAG:
        if re.search(r"\barquitectura\b|\bestructura\b|\bsistema\b", text_lower, re.IGNORECASE):
            return IMPACT_ESTRUCTURAL
    
    # Default mapping
    return DOMAIN_DEFAULT_IMPACT.get(domain, IMPACT_OPERATIVO)


def _generate_next_action(domain: str, msg_type: str, text: str) -> str:
    """Generate a short actionable next step."""
    base_action = NEXT_ACTIONS.get(domain, "Procesar y categorizar")
    
    # Customize based on type
    if msg_type == TYPE_TAREA:
        return base_action
    elif msg_type == TYPE_PROYECTO:
        return f"Definir scope del proyecto y {base_action.lower()}"
    elif msg_type == TYPE_REFLEXION:
        return f"Capturar reflexión y revisar más tarde"
    elif msg_type == TYPE_AJUSTE:
        return f"Aplicar ajuste en sistema"
    
    return base_action


def _needs_confirmation(confidence: float, alternatives: list[IntentAlternative]) -> bool:
    """Determine if classification needs user confirmation."""
    # Needs confirmation if confidence < 0.70
    if confidence < 0.70:
        return True
    
    # Needs confirmation if top2 are very close (diff < 0.15)
    if alternatives and len(alternatives) >= 1:
        diff = confidence - alternatives[0]["confidence"]
        if diff < 0.15:
            return True
    
    return False


def classify_text(request: ClassifyRequest) -> Intent:
    """
    Classify text into domain with metadata.
    
    Args:
        request: ClassifyRequest with text and optional mode/context
    
    Returns:
        Intent with domain, type, cognitive_load, impact, next_action, 
        confidence, alternatives, needs_confirmation, and reason
    """
    text = request.get("text", "")
    
    # =========================================================================
    # OVERRIDE 1: Monetary indicators => FIN (priority over TTI)
    # =========================================================================
    money_override = _has_money_indicators(text)
    tti_override = _has_tti_indicators(text) if not money_override else False
    
    # Calculate domain scores
    scores = _calculate_domain_scores(text)
    
    # Get initial winner
    winner, confidence, alternatives = _get_winner_and_alternatives(scores)
    
    # Track reason parts
    reason_parts = []
    
    # =========================================================================
    # Apply overrides (priority: FIN > EIPROTA > regular tiebreakers)
    # =========================================================================
    if money_override:
        # Force FIN with high confidence
        if winner != DOMAIN_FIN:
            old_winner = winner
            winner = DOMAIN_FIN
            alternatives = [a for a in alternatives if a["domain"] != DOMAIN_FIN]
            alternatives.insert(0, IntentAlternative(domain=old_winner, confidence=round(confidence * 0.5, 3)))
            alternatives = alternatives[:2]
        confidence = max(0.95, confidence)
        reason_parts.append("override:money->FIN")
    
    elif tti_override:
        # Force EIPROTA with high confidence
        if winner != DOMAIN_EIPROTA:
            old_winner = winner
            winner = DOMAIN_EIPROTA
            alternatives = [a for a in alternatives if a["domain"] != DOMAIN_EIPROTA]
            alternatives.insert(0, IntentAlternative(domain=old_winner, confidence=round(confidence * 0.5, 3)))
            alternatives = alternatives[:2]
        confidence = max(0.90, confidence)
        reason_parts.append("override:tti->EIPROTA")
    
    else:
        # Apply regular tiebreakers
        tiebreaker_winner = _apply_tiebreakers(text, scores)
        if tiebreaker_winner:
            # Recalculate with tiebreaker
            old_winner = winner
            winner = tiebreaker_winner
            confidence = max(confidence, 0.80)  # Boost confidence for tiebreaker wins
            reason_parts.append("tiebreaker")
            
            # Update alternatives if needed
            if alternatives:
                alternatives = [a for a in alternatives if a["domain"] != winner]
                # Add old winner to alternatives if it was different
                if old_winner != winner:
                    old_score = scores.get(old_winner, 0)
                    total = sum(scores.values()) or 1
                    alternatives.insert(0, IntentAlternative(
                        domain=old_winner,
                        confidence=round(old_score / total, 3)
                    ))
                    alternatives = alternatives[:2]
    
    # Detect metadata
    msg_type = _detect_type(text)
    cognitive_load = _detect_cognitive_load(text, winner)
    impact = _detect_impact(winner, text)
    next_action = _generate_next_action(winner, msg_type, text)
    
    # Check if needs confirmation
    needs_conf = _needs_confirmation(confidence, alternatives)
    
    # =========================================================================
    # Detect operational intent (priority-based routing)
    # =========================================================================
    operation = detect_operational_intent(text)

    # FIN_EXPENSE operation overrides domain to FIN (purchase verbs without
    # currency symbols are valid FIN inputs — e.g. "compré café en efectivo")
    if operation == OP_FIN_EXPENSE and winner != DOMAIN_FIN:
        alternatives = [a for a in alternatives if a["domain"] != DOMAIN_FIN]
        alternatives.insert(0, IntentAlternative(domain=winner, confidence=round(confidence * 0.6, 3)))
        alternatives = alternatives[:2]
        winner = DOMAIN_FIN
        confidence = max(confidence, 0.90)
        needs_conf = False
        reason_parts.append("override:fin_op->FIN")

    # CODE operation overrides domain to CODE (code-specific verbs/nouns detected)
    elif operation in _CODE_OPERATIONS and winner != DOMAIN_CODE:
        alternatives = [a for a in alternatives if a["domain"] != DOMAIN_CODE]
        alternatives.insert(0, IntentAlternative(domain=winner, confidence=round(confidence * 0.6, 3)))
        alternatives = alternatives[:2]
        winner = DOMAIN_CODE
        confidence = max(confidence, 0.90)
        needs_conf = False
        reason_parts.append("override:code_op->CODE")

    # Complete reason for debugging
    if scores[winner] > 0 and not any("override" in r or "tiebreaker" in r for r in reason_parts):
        reason_parts.append(f"keywords:{winner}={scores[winner]:.1f}")
    if needs_conf:
        reason_parts.append("low_conf")
    if operation != OP_COMMAND:
        reason_parts.append(f"op:{operation}")
    reason = ",".join(reason_parts) if reason_parts else "heuristic"
    
    return Intent(
        domain=winner,
        operation=operation,
        type=msg_type,
        cognitive_load=cognitive_load,
        impact=impact,
        next_action=next_action,
        confidence=confidence,
        alternatives=alternatives,
        needs_confirmation=needs_conf,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Intent to Command Prefix Mapper
# ---------------------------------------------------------------------------

PREFIX_CODE = "CODE"
PREFIX_DOC = "DOC"
PREFIX_WORK_QUERY = "WORK_QUERY"

# Patterns that indicate code intent for EIPROTA
EIPROTA_CODE_PATTERNS = [
    r"\bm[oó]dulo\b",
    r"\bc[oó]digo\b",
    r"\bimplementar\b",
    r"\bprogramar\b",
    r"\bsimular\b",
]

# Patterns that indicate code intent for WORK/PRO_DIAG
WORK_CODE_PATTERNS = [
    r"\bscript\b",
    r"\bautomatizar\b",
    r"\bpython\b",
    r"\bnode\b",
    r"\bapi\b",
]


def map_intent_to_prefix(text: str, intent: Intent | None) -> str:
    """
    Map intent domain to command prefix (CODE, DOC, or WORK_QUERY).
    
    Rules (priority order):
    1. WORK_QUERY: if is_work_query(text) and NOT is_doc_request(text) => WORK_QUERY
    2. DOC: if is_doc_request(text) => DOC (explicit doc creation)
    3. CODE: if EIPROTA with code patterns or WORK/PRO_DIAG with script patterns => CODE
    4. DOC: fallback for everything else
    
    Args:
        text: Original message text
        intent: Classified intent or None
    
    Returns:
        "CODE", "DOC", or "WORK_QUERY"
    """
    domain = intent.get("domain", "") if intent else ""
    
    # PRIORITY 1: Check for work query (task questions) FIRST
    # This catches "tareas urgentes?", "qué tengo pendiente", etc.
    if is_work_query(text, domain):
        return PREFIX_WORK_QUERY
    
    # PRIORITY 2: Check for explicit doc request
    if is_doc_request(text):
        return PREFIX_DOC
    
    if intent is None:
        return PREFIX_DOC
    
    text_lower = text.lower()
    
    if domain == DOMAIN_EIPROTA:
        for pattern in EIPROTA_CODE_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return PREFIX_CODE
        return PREFIX_DOC
    
    if domain in (DOMAIN_WORK, DOMAIN_PRO_DIAG):
        for pattern in WORK_CODE_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return PREFIX_CODE
        return PREFIX_DOC
    
    # FIN, REL, HEALTH, ENERGY -> DOC
    return PREFIX_DOC


def build_routed_command(text: str, intent: Intent | None) -> str:
    """
    Build routed command with prefix.
    
    Args:
        text: Original message text
        intent: Classified intent or None
    
    Returns:
        Prefixed command string like "CODE: original text"
    """
    prefix = map_intent_to_prefix(text, intent)
    return f"{prefix}: {text}"


# ---------------------------------------------------------------------------
# Work Query Detection
# ---------------------------------------------------------------------------

# Patterns that indicate a work query/status request (STRONG indicators)
WORK_QUERY_PATTERNS = [
    r"\bqu[eé]\s+tengo\b",           # "qué tengo"
    r"\bestado\s+de\b",              # "estado de"
    r"\bpendiente[s]?\b",             # "pendiente", "pendientes"
    r"\bbloqueado[s]?\b",             # "bloqueado"
    r"\btarea[s]?\b",                 # "tareas" - STRONG
    r"\burgente[s]?\b",               # "urgente", "urgentes" - STRONG
    r"\bprioridad\b",                 # "prioridad" - STRONG
    r"\binfo\s+sobre\b",              # "info sobre" - query for info
    r"\bmis\s+obras\b",               # "mis obras" - eiProta context
    r"\bobras\s+(eiprota|thcye|tti)\b",  # "obras eiprota", etc.
    r"\bqu[eé]\s+hay\b",              # "qué hay"
    r"\bcu[aá]l(es)?\s+son\b",        # "cuáles son"
    r"\blistar?\b",                   # "lista", "listar"
    r"\bmostrar?\b",                  # "mostrar"
    r"\bver\s+(mis|las|los)\b",       # "ver mis", "ver las"
    r"\bqu[eé]\s+sigue\b",            # "qué sigue"
    r"\bcarga\s+alta\b",              # "carga alta"
    r"\bhoy\b",                       # "hoy"
    r"\besta\s+semana\b",             # "esta semana"
    r"\bpr[oó]xim[oa]s?\b",           # "próximo", "próxima"
    r"\bvencimiento[s]?\b",           # "vencimientos"
    r"\bdue\b",                       # "due" (english)
    r"\binbox\b",                     # "inbox"
    r"\bwaiting\b",                   # "waiting"
    r"\bscheduled\b",                 # "scheduled"
    r"\bnext\b",                      # "next"
]

# ---------------------------------------------------------------------------
# Doc Request Detection (Explicit doc creation)
# ---------------------------------------------------------------------------

# Patterns that explicitly request document creation
DOC_REQUEST_PATTERNS = [
    r"\bhaz\s+(un\s+)?doc(umento)?\b",    # "haz un documento", "haz doc"
    r"\bcrea(r)?\s+(un\s+)?doc\b",        # "crea un doc", "crear doc"
    r"\bredacta[r]?\b",                    # "redacta", "redactar"
    r"\bescribe\s+(un\s+)?doc\b",         # "escribe un doc"
    r"\bgenera(r)?\s+(un\s+)?doc\b",      # "genera un documento"
    r"\bPOE\b",                            # "POE" - procedure
    r"\bSOP\b",                            # "SOP" - standard operating procedure
    r"\binforme\b",                        # "informe"
    r"\bminuta\b",                         # "minuta"
    r"\bacta\b",                           # "acta"
    r"\bensayo\b",                         # "ensayo"
    r"\ben\s+(un\s+)?doc(umento)?\b",      # "en un documento", "en doc"
    r"\bresumen\s+en\s+doc\b",             # "resumen en documento"
    r"\bdocumento\s+de\b",                 # "documento de..."
    r"\bdocumentar\b",                     # "documentar"
]


# ---------------------------------------------------------------------------
# Operational Intent Detection (priority over semantic domain)
# ---------------------------------------------------------------------------

# Patterns that indicate WORK_QUERY operational intent (task lookup/status)
# These take routing priority over semantic domain classification
OPERATIONAL_WORK_QUERY_PATTERNS = [
    r"\b(tareas?|pendientes?)\b",          # "tareas", "tarea", "pendientes"
    r"\bestado\s+sobre\b",                  # "estado sobre X"
    r"\blista\s+de\b",                      # "lista de tareas"
    r"\bmis\s+tareas\b",                    # "mis tareas"
    r"\bqu[eé]\s+tengo\b",                  # "qué tengo"
    r"\bqu[eé]\s+hay\b",                    # "qué hay pendiente"
    r"\bcu[aá]les?\s+son\b",                # "cuáles son"
    r"\burgente[s]?\b",                     # "urgentes"
    r"\bprioridad\b",                       # "prioridad"
    r"\bbloqueado[s]?\b",                   # "bloqueado"
    r"\binbox\b",                           # "inbox"
    r"\bnext\b",                            # "next"
    r"\bwaiting\b",                         # "waiting"
    r"\bscheduled\b",                       # "scheduled"
    r"\bhoy\b",                             # "hoy"
    r"\besta\s+semana\b",                   # "esta semana"
]

# Patterns that indicate FIN_EXPENSE operational intent
OPERATIONAL_FIN_EXPENSE_PATTERNS = [
    r"\$\s*\d+",                            # $25, $ 100
    r"\bgast[oéeaó][s]?\s+(en|de)?\s*\d+",  # "gasté 5", "gasto de 10"
    r"\bpagu[eé]\b",                        # "pagué"
    r"\bcompr[eé]\b",                       # "compré"
    r"\d+\s*(pesos|d[oó]lares?|usd)\b",     # "50 pesos", "10 dolares"
    r"\b(anota[r]?)\b",                     # "anota", "anotar" — register expense
    r"\bgast[eé]\b",                        # "gasté" standalone
    r"\bgasto\s+(de|en)\b",                 # "gasto de café", "gasto en taxi"
]

# Patterns that indicate WORK_CREATE operational intent (task creation)
# These have HIGHER priority than WORK_QUERY patterns
OPERATIONAL_WORK_CREATE_PATTERNS = [
    # Creation verb + tarea
    r"\b(crea|crear|a[nñ]ade|a[nñ]adir|agrega|agregar|nueva?|inserta|insertar|registra|registrar|mete|meter)\b.*\btareas?\b",
    # Tarea + creation verb (reversed)
    r"\btareas?\b.*\b(crea|crear|a[nñ]ade|a[nñ]adir|agrega|agregar|nueva?|inserta|insertar|registra|registrar|mete|meter)\b",
    # "nueva tarea:" pattern
    r"\bnueva?\s+tarea[s]?\s*:",
    # "tarea nueva" pattern
    r"\btarea[s]?\s+nueva[s]?\b",
    # "crea una tarea:" pattern (with colon)
    r"\b(crea|crear|a[nñ]ade|a[nñ]adir|haz)\s+(una?\s+)?tarea[s]?\s*:",
    # "haz una tarea" pattern
    r"\bhaz\s+(una?\s+)?tarea\b",
    # "registra tarea" pattern
    r"\bregistra\s+(una?\s+)?tarea\b",
    # "agrega tarea para" pattern
    r"\b(agrega|a[nñ]ade)\s+(una?\s+)?tarea\s+(para|de|sobre)\b",
]

# Patterns that indicate WORK_DELETE operational intent (task deletion/archival)
# These have HIGHEST priority for WORK operations
OPERATIONAL_WORK_DELETE_PATTERNS = [
    # Delete verb + tarea(s)
    r"\b(elimina|eliminar|borra|borrar|archiva|archivar|limpia|limpiar|quita|quitar|remueve|remover)\b.*\btareas?\b",
    # Tarea(s) + delete verb (reversed)
    r"\btareas?\b.*\b(elimina|eliminar|borra|borrar|archiva|archivar|limpia|limpiar|quita|quitar|remueve|remover)\b",
    # "elimina todas" pattern
    r"\b(elimina|borra|archiva|limpia)\s+(todas?|todo)\b",
    # "mueve a papelera" pattern
    r"\b(mueve|mover)\s+(a\s+)?(la\s+)?papelera\b",
    # "elimina las que digan/contengan" pattern
    r"\b(elimina|borra)\s+.*\b(que\s+)?(digan?|contengan?|incluyan?)\b",
    # "borra todo" pattern
    r"\b(borra|elimina)\s+todo\b",
]


# Patterns that indicate WORK_UPDATE operational intent (task modification)
# These have priority for status/project/domain changes
OPERATIONAL_WORK_UPDATE_PATTERNS = [
    # "pon X en Y" / "ponla en Y" / "ponlo en Y"
    r"\b(pon(?:lo|la|le|er)?|ponla|ponlo)\b.+\b(en|a)\s+\w+",
    # "cambia X a Y" / "cambialo a Y"
    r"\bcambia(?:r|lo|la)?\b.+\b(a|de|el|la|su)\b",
    # "mueve X a Y" (not "mueve a papelera" which is delete)
    r"\bmuev(?:e|a|o)(?:la|lo)?\b.+\b(a|al|hacia)\s+(?!papelera)\w+",
    # "pasa X a Y" / "pasala a Y"
    r"\bpasa(?:r|la|lo)?\b.+\b(a|al)\s+\w+",
    # "actualiza X" / "update X"
    r"\b(actualiza|actulizar|update)\b.+\btareas?\b",
    # "esta tarea a X" / "esa tarea a X"
    r"\b(esta|esa|la)\s+tarea\b.+\ba\s+\w+",
    # "la tarea de X cambiar/mover/poner a Y"
    r"\bla\s+tarea\s+de\b.+\b(cambia|mueve|pon)\b",
    # "el status/proyecto/dominio de X"
    r"\b(el|la|su)\s+(status|estado|proyecto|project|dominio|domain)\s+(de\s+la\s+tarea|de)\b",
    # "marca X como Y" / "marcar X como Y" — status update idiom
    r"\bmarca[r]?\b.+\bcomo\b",
    # "marca todas las tareas..." — bulk update idiom
    r"\bmarca[r]?\s+todas?\b",
]


# ---------------------------------------------------------------------------
# CODE domain operational intent patterns
# ---------------------------------------------------------------------------
# All CODE patterns require a code-specific noun or context word to stay
# conservative and avoid collisions with WORK / FIN / ENERGY domains.

# CODE_EXPLAIN — read-only explanation / description
OPERATIONAL_CODE_EXPLAIN_PATTERNS = [
    r"\bexpl[ií]ca(?:me|r)?\b.{0,40}\b(?:c[oó]digo|módulo|archivo|clase|función|script|este|esta)\b",
    r"\bc[oó]mo\s+funciona\b.{0,40}\b(?:c[oó]digo|módulo|archivo|clase|función|script|este|esta)\b",
    r"\bqu[eé]\s+hace\b.{0,40}\b(?:c[oó]digo|módulo|archivo|clase|función|este|esta)\b",
    r"\bdescribe\b.{0,40}\b(?:módulo|archivo|clase|función|c[oó]digo|script)\b",
]

# CODE_REVIEW — read-only review / audit
OPERATIONAL_CODE_REVIEW_PATTERNS = [
    r"\brevis[ae]\b.{0,40}\b(?:c[oó]digo|módulo|archivo|clase|función|script)\b",
    r"\banaliza\b.{0,40}\b(?:c[oó]digo|módulo|archivo|clase|función)\b",
    r"\bencuentra\b.{0,40}\b(?:bugs?|errores?)\b",
    r"\baudit[ao]\b.{0,40}\b(?:c[oó]digo|módulo|archivo)\b",
]

# CODE_FIX — mutating: fix / correct code (requires code noun or "bug")
OPERATIONAL_CODE_FIX_PATTERNS = [
    r"\barregla[r]?\b.{0,60}\b(?:bug|error|c[oó]digo|archivo|función|clase|módulo|script)\b",
    r"\bcorrige?\b.{0,60}\b(?:bug|error|c[oó]digo|archivo|función)\b",
    r"\bfixea?\b",                                        # "fixea" is always code-specific
    r"\bsoluciona[r]?\b.{0,60}\b(?:bug|error|problema)\b.{0,40}\b(?:c[oó]digo|archivo|función)?\b",
    r"\bhaz\s+que\s+(?:esto|este)\s+funcione\b",
]

# CODE_CREATE — mutating: create new file / class / function
# Deliberately excludes "módulo" (ambiguous with EIPROTA research modules) and
# bare "script" (ambiguous with WORK tasks); require language qualifier for script.
OPERATIONAL_CODE_CREATE_PATTERNS = [
    r"\b(?:crea|crear)\b.{0,60}\b(?:archivo|clase|función|método)\b",
    r"\b(?:crea|crear)\b.{0,40}\bscript\b.{0,30}\b(?:python|bash|shell|js|javascript|\.py|\.sh)\b",
    r"\b(?:genera|generar)\b.{0,60}\b(?:archivo|clase|función)\b",
    r"\b(?:implementa|implementar)\b.{0,60}\b(?:clase|función|método)\b",
    r"\bnuevo?\s+(?:archivo|clase|función)\b",
    r"\bescribe\b.{0,40}\b(?:clase|función)\b",
]

# Frozen set used in classify_text for domain override
_CODE_OPERATIONS: frozenset = frozenset({
    OP_CODE_EXPLAIN, OP_CODE_REVIEW, OP_CODE_FIX, OP_CODE_CREATE,
})


def detect_operational_intent(text: str) -> str:
    """
    Detect operational intent from text patterns.
    
    This runs BEFORE semantic domain classification and determines
    which backend endpoint to use for routing.
    
    Priority order (highest first):
    1. WORK_DELETE - delete/archive task patterns (highest risk)
    2. WORK_UPDATE - update task patterns (mutating, includes "marca X como Y")
    3. WORK_CREATE - create task patterns (mutating)
    4. FIN_EXPENSE - expense/money patterns (before WORK_QUERY to avoid "hoy" collision)
    5. WORK_QUERY  - task lookup/status patterns (read-only)
    6. COMMAND     - default fallback
    
    Args:
        text: User message text
    
    Returns:
        Operation type: OP_WORK_DELETE, OP_WORK_UPDATE, OP_WORK_CREATE, OP_WORK_QUERY, OP_FIN_EXPENSE, or OP_COMMAND
    """
    text_lower = text.lower()
    
    # Priority 1: WORK_DELETE patterns (highest priority for mutations)
    for pattern in OPERATIONAL_WORK_DELETE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return OP_WORK_DELETE
    
    # Priority 2: WORK_UPDATE patterns (mutating operation)
    # Must check BEFORE WORK_CREATE to capture "cambia", "pon", "mueve" patterns
    for pattern in OPERATIONAL_WORK_UPDATE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return OP_WORK_UPDATE
    
    # Priority 3: WORK_CREATE patterns (mutating operation)
    # NOTE: Check BEFORE doc request because "crea tarea: revisar informe"
    # should be treated as task creation, not document creation
    for pattern in OPERATIONAL_WORK_CREATE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return OP_WORK_CREATE
    
    # Priority 4: FIN_EXPENSE patterns — checked before WORK_QUERY so that
    # monetary inputs containing temporal words like "hoy" are not stolen by
    # the broad WORK_QUERY \bhoy\b pattern.
    for pattern in OPERATIONAL_FIN_EXPENSE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return OP_FIN_EXPENSE

    # Priority 5: CODE domain patterns (before doc check and WORK_QUERY).
    # Ordered: mutating first (FIX > CREATE), then read-only (REVIEW > EXPLAIN).
    # All patterns require a code-specific noun to avoid false positives.
    for pattern in OPERATIONAL_CODE_FIX_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return OP_CODE_FIX

    for pattern in OPERATIONAL_CODE_CREATE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return OP_CODE_CREATE

    for pattern in OPERATIONAL_CODE_REVIEW_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return OP_CODE_REVIEW

    for pattern in OPERATIONAL_CODE_EXPLAIN_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return OP_CODE_EXPLAIN

    # Check for doc request (takes priority over WORK_QUERY)
    if is_doc_request(text):
        return OP_COMMAND

    # Priority 5: WORK_QUERY patterns (read-only)
    for pattern in OPERATIONAL_WORK_QUERY_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return OP_WORK_QUERY
    
    # Default: COMMAND
    return OP_COMMAND


def is_work_query(text: str, domain: str = None) -> bool:
    """
    Detect if the text is a work query request.
    
    This function now detects work queries regardless of domain classification,
    because task-related questions can be misclassified as ENERGY or other domains.
    
    
    Args:
        text: User message text
        domain: Detected domain from classifier (optional, used for bonus weighting)
    
    Returns:
        True if this looks like a work query request
    """
    text_lower = text.lower()
    
    # Check if this is a doc request (takes priority if explicit)
    if is_doc_request(text):
        return False
    
    # Count matching patterns
    matches = 0
    for pattern in WORK_QUERY_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            matches += 1
    
    # Bonus: if domain is WORK, lower threshold
    threshold = 1
    if domain == DOMAIN_WORK:
        threshold = 1
    
    return matches >= threshold


def is_doc_request(text: str) -> bool:
    """
    Detect if the text explicitly requests document creation.
    
    This should only match when user EXPLICITLY asks for a document,
    not just any text input that could be routed to DOC as fallback.
    
    Args:
        text: User message text
    
    Returns:
        True if user explicitly wants to create a document
    """
    text_lower = text.lower()
    
    for pattern in DOC_REQUEST_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    
    return False


def parse_work_query_filters(text: str) -> dict:
    """
    Parse natural language text into work query filters.
    
    ENHANCED: Now performs live validation against Notion taxonomy.
    - If target value doesn't exist in taxonomy AND no explicit prefix → text search fallback
    - If explicit prefix AND value doesn't exist → InvalidFilter with suggestions
    
    Args:
        text: User message like "¿Qué hay pendiente hoy?" or "Estado proyecto CELLAB"
    
    Returns:
        Dictionary with filters: status, project, domain, project_key, title_keyword, load, date_range
        Plus audit fields: _target_audit, _routing_reason, _is_invalid_filter
    """
    from datetime import date, timedelta
    from .taxonomy import parse_target_from_text, build_target_filter, TargetFilterResult
    
    text_lower = text.lower()
    filters: dict = {}
    today = date.today()
    
    # ---------------------------------------------------------------------------
    # Parse target using taxonomy module WITH LIVE VALIDATION
    # ---------------------------------------------------------------------------
    parsed_target = parse_target_from_text(text)
    target_filter: TargetFilterResult = build_target_filter(parsed_target, validate_live=True)
    
    # Check for InvalidFilter (explicit prefix with non-existent value)
    if target_filter.get("is_invalid_filter"):
        filters["_is_invalid_filter"] = True
        filters["_invalid_filter_message"] = target_filter.get("validation_message", "Invalid filter value")
        filters["_suggested_values"] = target_filter.get("suggested_values", [])
        # Don't add actual filter - query should not proceed
    else:
        # Add to filters based on resolved filter type (may be fallback)
        filter_type = target_filter.get("filter_type", "none")
        filter_value = target_filter.get("filter_value", "")
        
        if filter_type == "proyecto":
            filters["project"] = filter_value
        elif filter_type == "domain":
            filters["domain"] = filter_value
        elif filter_type == "key":
            filters["project_key"] = filter_value
        elif filter_type == "title_keyword":
            filters["title_keyword"] = filter_value
    
    # Add comprehensive target audit info
    filters["_target_audit"] = {
        "target_type": parsed_target["target_type"],
        "target_value": parsed_target["value"],
        "has_explicit_prefix": parsed_target.get("has_explicit_prefix", False),
        "filter_applied": target_filter.get("filter_type", "none"),
        "matched_taxonomy": target_filter.get("matched_taxonomy", False),
        "fallback_used": target_filter.get("fallback_used", "none"),
        "validation_message": target_filter.get("validation_message", ""),
    }
    
    # Add routing reason for debugging
    if target_filter.get("fallback_used") == "text_search":
        filters["_routing_reason"] = f"Target '{parsed_target['value']}' not found in taxonomy, using text search in title"
    elif target_filter.get("is_invalid_filter"):
        filters["_routing_reason"] = f"Explicit prefix used but '{parsed_target['value']}' not in taxonomy - InvalidFilter"
    elif target_filter.get("matched_taxonomy"):
        filters["_routing_reason"] = f"Target '{parsed_target['value']}' matched taxonomy as {target_filter.get('filter_type')}"
    else:
        filters["_routing_reason"] = "No target detected or keyword search"
    
    # ---------------------------------------------------------------------------
    # Detect status filters (with explicit status: prefix support)
    # ---------------------------------------------------------------------------
    statuses = []
    raw_status_values = []  # Track raw values for validation
    
    # 1. Check explicit status: prefix patterns first (status:VALUE or status VALUE)
    explicit_status_match = re.search(r"\bstatus[:\s]+([A-Za-z_]+)", text_lower)
    if explicit_status_match:
        raw_val = explicit_status_match.group(1).strip().upper()
        raw_status_values.append(raw_val)
        # Map to valid status if recognized
        if raw_val in ("WAITING", "BLOQUEADO"):
            statuses.append("WAITING")
        elif raw_val in ("INBOX", "PENDIENTE"):
            statuses.append("INBOX")
        elif raw_val in ("NEXT", "SIGUIENTE", "PROXIMO"):
            statuses.append("NEXT")
        elif raw_val in ("SCHEDULED", "PROGRAMADO", "AGENDADO"):
            statuses.append("SCHEDULED")
        elif raw_val in ("DONE", "COMPLETED", "TERMINADO", "HECHO"):
            statuses.append("DONE")
        else:
            # Unknown status value - store for validation later
            statuses.append(raw_val)
    
    # 2. Implicit keyword detection (only if no explicit prefix found)
    if not explicit_status_match:
        if re.search(r"\bbloqueado[s]?\b|\bwaiting\b", text_lower):
            statuses.append("WAITING")
        if re.search(r"\bpendiente[s]?\b|\binbox\b", text_lower):
            statuses.append("INBOX")
        if re.search(r"\bsiguiente[s]?\b|\bnext\b|\bpr[oó]xim[oa]s?\b", text_lower):
            statuses.append("NEXT")
        if re.search(r"\bprogramad[oa]s?\b|\bscheduled\b|\bagendad[oa]s?\b", text_lower):
            statuses.append("SCHEDULED")
        
        # urgent/urgente special handling
        if re.search(r"\burgente[s]?\b|\burgent\b", text_lower):
            # Urgent usually means NEXT
            if "NEXT" not in statuses:
                statuses.append("NEXT")
    
    # If specific statuses found, use them; otherwise will use active defaults later
    if statuses:
        filters["status"] = statuses
    if raw_status_values:
        filters["_raw_status_values"] = raw_status_values  # For validation
    
    # ---------------------------------------------------------------------------
    # Legacy project detection (fallback if taxonomy didn't find anything)
    # ---------------------------------------------------------------------------
    if "project" not in filters and "domain" not in filters and "project_key" not in filters and "title_keyword" not in filters:
        # Look for project name after "proyecto" or capitalized words
        project_match = re.search(r"\bproyecto\s+([A-Z][A-Za-z0-9_-]+)", text, re.IGNORECASE)
        if project_match:
            filters["project"] = project_match.group(1)
        else:
            # Look for any capitalized sequence that could be a project name
            cap_match = re.search(r"\b([A-Z]{3,})\b", text)
            if cap_match:
                # Exclude common words
                word = cap_match.group(1)
                if word not in {"QUE", "HOY", "LOS", "LAS", "UNA", "CON", "POR", "MIS", "TUS", "STATUS", "NEXT", "INBOX", "WAITING", "SCHEDULED"}:
                    filters["project"] = word
    
    # ---------------------------------------------------------------------------
    # Detect load (unchanged)
    # ---------------------------------------------------------------------------
    if re.search(r"\bcarga\s+alta\b|\balta\s+carga\b|\bpesad[oa]s?\b", text_lower):
        filters["load"] = "Alta"
    elif re.search(r"\bcarga\s+media\b|\bmedia\s+carga\b", text_lower):
        filters["load"] = "Media"
    elif re.search(r"\bcarga\s+baja\b|\bbaja\s+carga\b|\blivianas?\b", text_lower):
        filters["load"] = "Baja"
    
    # ---------------------------------------------------------------------------
    # Detect date range (unchanged)
    # ---------------------------------------------------------------------------
    if re.search(r"\bhoy\b", text_lower):
        filters["date_range"] = {
            "from": today.isoformat(),
            "to": today.isoformat()
        }
    elif re.search(r"\besta\s+semana\b", text_lower):
        # This week = today to next Sunday
        days_until_sunday = (6 - today.weekday()) % 7
        end_of_week = today + timedelta(days=days_until_sunday)
        filters["date_range"] = {
            "from": today.isoformat(),
            "to": end_of_week.isoformat()
        }
    elif re.search(r"\bpr[oó]xim[oa]s?\s*\d+\s*d[ií]as?\b", text_lower):
        # "próximos N días"
        days_match = re.search(r"\bpr[oó]xim[oa]s?\s*(\d+)\s*d[ií]as?\b", text_lower)
        if days_match:
            n_days = int(days_match.group(1))
            filters["date_range"] = {
                "from": today.isoformat(),
                "to": (today + timedelta(days=n_days)).isoformat()
            }
    elif re.search(r"\bsemana\s+que\s+viene\b|\bpr[oó]xima\s+semana\b", text_lower):
        # Next week
        next_monday = today + timedelta(days=(7 - today.weekday()))
        next_sunday = next_monday + timedelta(days=6)
        filters["date_range"] = {
            "from": next_monday.isoformat(),
            "to": next_sunday.isoformat()
        }
    
    return filters
