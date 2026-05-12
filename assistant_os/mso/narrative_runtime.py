"""MSO Narrative Runtime — read-only cognitive fallback for ambiguous operational inputs.

Intercepts unknown_ambiguous inputs on assistant_chat that appear to be
MSO/operational queries and returns a rich read-only narrative response
using local system state. No network calls. No side effects.

Safety invariants (never negotiable, enforced by design):
  - Does not execute.
  - Does not approve.
  - Does not issue CapabilityToken.
  - Does not create AuthorizedPlan.
  - Does not call PoliceGate.
  - Does not call runner or pipeline.
  - Does not enable HOST, MACHINE_OPERATOR, or OpenClaw.
  - execution_allowed = False always.
  - can_execute_now = False always.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Narrative intent patterns — exact match after normalization (fast path)
# ---------------------------------------------------------------------------

_NARRATIVE_EXACT: frozenset[str] = frozenset({
    # Sprint-specified canonical examples
    "como quedamos",
    "que falta",
    "que puedes hacer realmente",
    "revisa el sistema",
    "quiero seguir con code",
    # MSO/operational state queries
    "que hay en mission control",
    "como esta el mso",
    "que hace el mso",
    "que pasa con el mso",
    "que esta pasando",
    "en que estamos",
    # Queue / pending
    "que hay pendiente",
    "hay acciones pendientes",
    "cuantas acciones pendientes",
    "que falta por confirmar",
    "que tengo pendiente",
    "tengo algo pendiente",
    # Summary / status
    "resumen operacional",
    "resumen del sistema",
    "dame un resumen operacional",
    "dame el estado del sistema",
    "cual es el estado operacional",
    # Next step
    "que sigue",
    "siguiente paso",
    "cuales son los proximos pasos",
    "que debo hacer ahora",
    # Provider / configuration
    "cual es el proveedor",
    "que proveedor tienes",
    "tienes proveedor configurado",
    "necesitas api key",
    # Continuation
    "quiero continuar",
    "podemos continuar",
    "por donde vamos",
    "como va el sistema",
    "como va el mso",
})

# ---------------------------------------------------------------------------
# Narrative intent patterns — regex (flexible matching for phrase variants)
# ---------------------------------------------------------------------------

_NARRATIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcomo\b.{0,10}\bquedamos\b"),
    re.compile(r"\bproximos?\s+pasos?\b"),
    re.compile(r"\bestado\s+(?:del\s+)?(?:mso|operacional)\b"),
    re.compile(r"\bresumen\b.{0,10}\b(?:operacional|mso)\b"),
    re.compile(r"\bseguir\b.{0,15}\bcode\b"),
    re.compile(r"\bque\b.{0,5}\bfalta\b.{0,10}\bconfirmar\b"),
    re.compile(r"\bacciones?\b.{0,10}\bpendientes?\b"),
    re.compile(r"\bmission\s+control\b"),
)


def is_mso_narrative_intent(normalized: str) -> bool:
    """Return True if normalized text is an MSO/operational narrative query.

    Uses exact match first (O(1)), then regex for flexible variants.
    Never raises — returns False on any exception.
    """
    if not normalized:
        return False
    if normalized in _NARRATIVE_EXACT:
        return True
    try:
        return any(p.search(normalized) for p in _NARRATIVE_PATTERNS)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Narrative response builder
# ---------------------------------------------------------------------------


def build_narrative_context_message() -> tuple[str, dict]:
    """Return (message, narrative_context) for a MSO narrative status response.

    Reads local system state — no network calls, no execution, no side effects.
    Always returns execution_allowed=False and can_execute_now=False.

    Returns
    -------
    tuple[str, dict]
        message: Human-readable narrative status message.
        narrative_context: Structured dict with system state snapshot.
    """
    operational_mode = "UNKNOWN"
    seat_provider_description = "No cognitive provider is currently seated/configured."
    prepared_count = 0
    pending_review_items: list[dict] = []

    try:
        from .seat_model_provider_registry import describe_seated_provider
        seat_provider_description = describe_seated_provider()
    except Exception:
        pass

    try:
        from ..operability import build_mso_state_response
        state = build_mso_state_response()
        operational_mode = state.get("operational_mode", "UNKNOWN")
    except Exception:
        pass

    try:
        from .prepared_action_queue import list_pending_confirmable_action_dicts
        pending_review_items = list_pending_confirmable_action_dicts()
        prepared_count = len(pending_review_items)
    except Exception:
        pass

    if operational_mode not in ("NORMAL", "UNKNOWN"):
        next_safe_step = (
            f"Resuelve la restriccion de gobernanza. "
            f"Modo operacional: {operational_mode}."
        )
    elif prepared_count > 0:
        next_safe_step = (
            f"Revisa {prepared_count} accion(es) preparada(s) en la cola de confirmacion. "
            "Cada accion incluye una linea de autoridad de 11 etapas. "
            "La ejecucion permanece cerrada."
        )
    else:
        next_safe_step = (
            "Crea un plan_request para iniciar un flujo gobernado. "
            "No hay acciones pendientes de confirmacion."
        )

    parts: list[str] = [
        f"Modo operacional: {operational_mode}.",
        f"Proveedor cognitivo: {seat_provider_description}.",
    ]
    if prepared_count > 0:
        parts.append(
            f"Acciones preparadas en cola de revision manual: {prepared_count}. "
            "La ejecucion permanece cerrada."
        )
    else:
        parts.append("Cola de acciones preparadas: vacia.")
    parts.append(f"Proximo paso seguro: {next_safe_step}")
    parts.append(
        "El MSO coordina; no ejecuta. "
        "Toda ejecucion requiere: PolicyDecision -> CapabilityToken -> "
        "OperationBinding -> AuthorizedPlan -> PoliceGate."
    )

    message = " ".join(parts)

    narrative_context: dict = {
        "execution_allowed": False,
        "can_execute_now": False,
        "operational_mode": operational_mode,
        "seat_provider": seat_provider_description,
        "prepared_actions_count": prepared_count,
        "pending_review_items": pending_review_items,
        "next_safe_step": next_safe_step,
    }

    return message, narrative_context


__all__ = [
    "is_mso_narrative_intent",
    "build_narrative_context_message",
]
