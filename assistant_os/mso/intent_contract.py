"""MSO Intent Metadata Contract — S-MSO-INTENT-METADATA-CONTRACT-01.

Defines the canonical intent metadata contract for MSO interactions.

The MSO must distinguish between cognitive request types (conversation, status,
planning, validation, orchestration, proposal, confirmation, execution_request)
and cognition cost tiers (default, cheap, advanced).

This module:
- Defines all allowed values as constants
- Provides normalize_mso_intent_metadata() for deterministic, fail-safe normalization
- Provides mso_context_interaction_mode_to_intent_mode() for clean surface_behavior mapping
- Never grants execution authority
- mso_direct cannot execute regardless of execution_intent value

Safety invariants (enforced here, never relaxed):
- Unknown intent_mode falls back to 'conversation' with a warning
- Unknown cognition_level falls back to 'default' with a warning
- Unknown model_seat is warned, not silently selected
- Invalid execution_intent falls back to False
- execution_request intent_mode does NOT grant execution from mso_direct
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Intent mode constants
# ---------------------------------------------------------------------------

INTENT_MODE_CONVERSATION = "conversation"
INTENT_MODE_STATUS = "status"
INTENT_MODE_PLANNING = "planning"
INTENT_MODE_VALIDATION = "validation"
INTENT_MODE_ORCHESTRATION = "orchestration"
INTENT_MODE_PROPOSAL = "proposal"
INTENT_MODE_CONFIRMATION = "confirmation"
INTENT_MODE_EXECUTION_REQUEST = "execution_request"

SUPPORTED_INTENT_MODES: frozenset[str] = frozenset({
    INTENT_MODE_CONVERSATION,
    INTENT_MODE_STATUS,
    INTENT_MODE_PLANNING,
    INTENT_MODE_VALIDATION,
    INTENT_MODE_ORCHESTRATION,
    INTENT_MODE_PROPOSAL,
    INTENT_MODE_CONFIRMATION,
    INTENT_MODE_EXECUTION_REQUEST,
})

# ---------------------------------------------------------------------------
# Cognition level constants
# ---------------------------------------------------------------------------

COGNITION_LEVEL_DEFAULT = "default"
COGNITION_LEVEL_CHEAP = "cheap"
COGNITION_LEVEL_ADVANCED = "advanced"

SUPPORTED_COGNITION_LEVELS: frozenset[str] = frozenset({
    COGNITION_LEVEL_DEFAULT,
    COGNITION_LEVEL_CHEAP,
    COGNITION_LEVEL_ADVANCED,
})

# ---------------------------------------------------------------------------
# Known model seats (must match seat_model_provider.py SUPPORTED_PROVIDER_NAMES)
# ---------------------------------------------------------------------------

_KNOWN_MODEL_SEATS: frozenset[str] = frozenset({
    "anthropic",
    "llama",
    "openai",
    "gemma",
})

# ---------------------------------------------------------------------------
# mso_context interaction_mode → intent_mode mapping
# ---------------------------------------------------------------------------

_MSO_CONTEXT_INTERACTION_MODE_MAP: dict[str, str] = {
    "conversational": INTENT_MODE_CONVERSATION,
    "planning": INTENT_MODE_PLANNING,
    "validation": INTENT_MODE_VALIDATION,
    "orchestration": INTENT_MODE_ORCHESTRATION,
}


def mso_context_interaction_mode_to_intent_mode(interaction_mode: str) -> str:
    """Map a surface_behavior mso_context interaction_mode to a contract intent_mode.

    Unknown modes fall back to 'conversation'.
    """
    return _MSO_CONTEXT_INTERACTION_MODE_MAP.get(interaction_mode, INTENT_MODE_CONVERSATION)


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def normalize_mso_intent_metadata(raw: dict | None) -> dict:
    """Normalize raw intent metadata to a validated, safe contract dict.

    Parameters
    ----------
    raw:
        Caller-supplied intent metadata dict, or None.

    Returns
    -------
    dict with keys:
        intent_mode       — one of SUPPORTED_INTENT_MODES (default: 'conversation')
        cognition_level   — one of SUPPORTED_COGNITION_LEVELS (default: 'default')
        model_seat        — str, empty if absent; warned if unknown provider
        execution_intent  — bool (default: False)
        valid             — bool, True unless unrecoverable structure
        warnings          — list[str] of normalization notices
        source            — 'metadata' | 'default'
    """
    warnings: list[str] = []

    if raw is None or not isinstance(raw, dict):
        return {
            "intent_mode": INTENT_MODE_CONVERSATION,
            "cognition_level": COGNITION_LEVEL_DEFAULT,
            "model_seat": "",
            "execution_intent": False,
            "valid": True,
            "warnings": warnings,
            "source": "default",
        }

    # -- intent_mode ----------------------------------------------------------
    raw_mode = raw.get("intent_mode", "")
    if raw_mode and raw_mode in SUPPORTED_INTENT_MODES:
        intent_mode = raw_mode
    elif raw_mode:
        warnings.append(
            f"unknown intent_mode={raw_mode!r}; defaulting to 'conversation'"
        )
        intent_mode = INTENT_MODE_CONVERSATION
    else:
        intent_mode = INTENT_MODE_CONVERSATION

    # -- cognition_level ------------------------------------------------------
    raw_level = raw.get("cognition_level", "")
    if raw_level and raw_level in SUPPORTED_COGNITION_LEVELS:
        cognition_level = raw_level
    elif raw_level:
        warnings.append(
            f"unknown cognition_level={raw_level!r}; defaulting to 'default'"
        )
        cognition_level = COGNITION_LEVEL_DEFAULT
    else:
        cognition_level = COGNITION_LEVEL_DEFAULT

    # -- model_seat -----------------------------------------------------------
    raw_seat = raw.get("model_seat", "")
    if isinstance(raw_seat, str):
        model_seat = raw_seat.strip().lower() if raw_seat else ""
    else:
        model_seat = ""
    if model_seat and model_seat not in _KNOWN_MODEL_SEATS:
        warnings.append(
            f"unknown model_seat={model_seat!r}; not a known provider — seat ignored"
        )

    # -- execution_intent -----------------------------------------------------
    raw_exec = raw.get("execution_intent", False)
    if isinstance(raw_exec, bool):
        execution_intent = raw_exec
    else:
        warnings.append(
            f"invalid execution_intent type={type(raw_exec).__name__!r}; defaulting to False"
        )
        execution_intent = False

    return {
        "intent_mode": intent_mode,
        "cognition_level": cognition_level,
        "model_seat": model_seat,
        "execution_intent": execution_intent,
        "valid": True,
        "warnings": warnings,
        "source": "metadata",
    }


# ---------------------------------------------------------------------------
# Intent contract descriptor (used by entity_status)
# ---------------------------------------------------------------------------


def build_intent_contract_descriptor() -> dict:
    """Return the static intent contract descriptor for entity status."""
    return {
        "supported_intent_modes": sorted(SUPPORTED_INTENT_MODES),
        "supported_cognition_levels": sorted(SUPPORTED_COGNITION_LEVELS),
        "mso_direct_can_execute": False,
        "execution_requires_governed_path": True,
    }
