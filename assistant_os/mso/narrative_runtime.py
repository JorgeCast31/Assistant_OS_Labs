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


def build_mso_grounding_context() -> dict:
    """Return a grounding context dict for MSO cognitive generation.

    Delegates to build_economic_perception_frame() (SPRINT-ALPHA-02) and adds
    the legacy 'pending_review_items' key as an alias for 'prepared_actions_summary'
    so Phase 1 callers receive the field they expect.

    Reads local system state — no network calls, no execution, no side effects.
    Always returns execution_allowed=False, can_execute_now=False, execution_closed=True.
    """
    from .perception import build_economic_perception_frame
    frame = build_economic_perception_frame()
    # Legacy alias: Phase 1 callers (build_narrative_context_message) expect this key
    frame["pending_review_items"] = frame.get("prepared_actions_summary", [])
    return frame


def build_narrative_context_message() -> tuple[str, dict]:
    """Return (message, narrative_context) for a MSO narrative status response.

    Reads local system state — no network calls, no execution, no side effects.
    Always returns execution_allowed=False and can_execute_now=False.
    """
    ctx = build_mso_grounding_context()
    operational_mode = ctx["operational_mode"]
    seat_provider_description = ctx["seat_provider"]
    prepared_count = ctx["prepared_actions_count"]
    next_safe_step = ctx["next_safe_step"]

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
    return message, ctx


__all__ = [
    "is_mso_narrative_intent",
    "build_mso_grounding_context",
    "build_narrative_context_message",
]
