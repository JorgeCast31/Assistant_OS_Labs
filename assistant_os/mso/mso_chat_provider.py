"""MSO Chat Provider — Anthropic-backed cognitive generation for mso_direct.

This module is the single integration point between mso_direct surface
behavior and the Anthropic SDK for conversational generation.

Safety invariants (enforced by this module, never delegated to the LLM):
  - used_execution = False always
  - cognitive_only = True always
  - execution_allowed never read from LLM output
  - Responses containing execution-claim phrases are rejected
  - Any exception returns a structured error response (never raises)
"""
from __future__ import annotations

import re
import logging
from typing import Any, Optional

from ..config import ANTHROPIC_API_KEY
from .seat_model_provider import make_unavailable_response, make_cognitive_response

_log = logging.getLogger(__name__)

_MSO_CHAT_MODEL_DEFAULT = "claude-haiku-4-5-20251001"
_MSO_CHAT_MAX_TOKENS = 512

# Patterns that indicate the LLM is claiming to have executed something.
# Responses matching any of these are rejected and fall back to deterministic.
_EXECUTION_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(he\s+ejecutado|ejecut[oéa]\s+la|i\s+have\s+executed|executed\s+the)\b", re.IGNORECASE),
    re.compile(r"\b(completado\s+la\s+tarea|completed\s+the\s+task|task\s+completed|tarea\s+completada)\b", re.IGNORECASE),
    re.compile(r"\b(running\s+the\s+(?:task|action|plan|proceso)|corriendo\s+el\s+proceso)\b", re.IGNORECASE),
    re.compile(r"\b(deployed?|desplegado|lanzado\s+el\s+proceso)\b", re.IGNORECASE),
)


def _resolve_model() -> str:
    """Return the model name to use, preferring MSO_SEAT_MODEL then CODE_REVIEW_MODEL."""
    try:
        from ..config import MSO_SEAT_MODEL, CODE_REVIEW_MODEL
        return MSO_SEAT_MODEL or CODE_REVIEW_MODEL or _MSO_CHAT_MODEL_DEFAULT
    except Exception:
        return _MSO_CHAT_MODEL_DEFAULT


def _get_anthropic_client():
    """Return a configured Anthropic client. Raises if SDK unavailable or key missing."""
    import anthropic as _anthropic
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")
    return _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _validate_provider_text(text: str) -> Optional[str]:
    """Return an error reason string if text fails validation, else None.

    Checks:
    - Must be non-empty after stripping
    - Must not contain execution-claim phrases
    """
    stripped = (text or "").strip()
    if not stripped:
        return "provider returned empty response"
    for pattern in _EXECUTION_CLAIM_PATTERNS:
        if pattern.search(stripped):
            return f"provider response contains execution claim (pattern: {pattern.pattern!r})"
    return None


def is_mso_chat_available() -> bool:
    """Return True if the Anthropic provider is configured and can be called.

    No network calls — config-derived only.
    """
    return bool(ANTHROPIC_API_KEY and ANTHROPIC_API_KEY.strip())


def call_mso_chat_provider(
    grounding_context: dict,
    user_text: str,
    history: Optional[list[dict[str, str]]] = None,
) -> dict[str, Any]:
    """Call the Anthropic provider for MSO conversational generation.

    Parameters
    ----------
    grounding_context : dict
        Dict from build_mso_grounding_context(). Injected as system context.
    user_text : str
        The user's current message.
    history : list[{"role": "user"|"assistant", "content": str}] | None
        Prior conversation turns (max last 5). Pass None for single-turn.

    Returns
    -------
    dict
        ModelProviderResponse-shaped dict with keys:
        text, provider_name, model_name, status, used_execution,
        cognitive_only, error, metadata.

        used_execution is ALWAYS False.
        cognitive_only is ALWAYS True.
        status is "ok" on success, "unavailable" or "error" on failure.

    Never raises — all exceptions are caught and returned as error responses.
    """
    provider_name = "anthropic"
    model_name = _resolve_model()

    if not is_mso_chat_available():
        return make_unavailable_response(
            provider_name=provider_name,
            model_name=model_name,
            reason="ANTHROPIC_API_KEY not configured",
        )

    from .prompts import build_mso_chat_system_prompt
    system_prompt = build_mso_chat_system_prompt(grounding_context)

    # Build messages list: optional history + current user turn
    messages: list[dict[str, str]] = []
    if history:
        for turn in history[-5:]:  # max 5 prior turns
            role = turn.get("role", "")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_text or ""})

    try:
        client = _get_anthropic_client()
        response = client.messages.create(
            model=model_name,
            max_tokens=_MSO_CHAT_MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        )
        raw_text: str = response.content[0].text

    except Exception as exc:
        _log.debug("mso_chat_provider: provider call failed: %s", exc)
        return make_unavailable_response(
            provider_name=provider_name,
            model_name=model_name,
            reason=f"provider call failed: {exc}",
        )

    # Validate output — reject execution claims and empty text
    validation_error = _validate_provider_text(raw_text)
    if validation_error:
        _log.debug("mso_chat_provider: response validation failed: %s", validation_error)
        return make_unavailable_response(
            provider_name=provider_name,
            model_name=model_name,
            reason=f"response validation failed: {validation_error}",
        )

    return make_cognitive_response(
        text=raw_text.strip(),
        provider_name=provider_name,
        model_name=model_name,
        metadata={
            "cognitive_only": True,
            "non_executing": True,
            "mso_chat": True,
            "grounding_operational_mode": grounding_context.get("operational_mode", "UNKNOWN"),
        },
    )
