"""
M30: Bounded cognitive classification.

Provides ONE strictly-typed classification task that the local LLM can
participate in as an advisory provider.

Contract
--------
Input : text + optional context_hint string
Output: ClassificationResult or None (on any failure → caller falls back)

The classification is ADVISORY ONLY.  It has no execution authority.
The deterministic kernel remains the source of truth regardless of output.

Schema (strict):
  {
    "classification":    str,   # the label assigned
    "reasoning_summary": str,   # brief explanation
    "risk_notes":        str,   # safety/risk note (may be empty)
    "confidence":        float  # [0.0, 1.0]
  }

Validation contract:
  - All four keys required
  - confidence must be numeric, clamped to [0.0, 1.0]
  - Unknown keys are stripped
  - Empty / whitespace-only values for classification → validation failure
  - On any validation failure → return None (caller activates fallback)
"""
from __future__ import annotations

import logging
from typing import Optional, TypedDict

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

class ClassificationResult(TypedDict):
    """Bounded output from local LLM classification advisory."""

    classification:    str
    reasoning_summary: str
    risk_notes:        str
    confidence:        float
    # Provenance fields added by classify_with_local_llm():
    provider:          str    # e.g. "llamacpp"
    backend:           str    # same as provider, for UI compat
    latency_ms:        int
    fallback_used:     bool
    validation:        str    # "passed" | failure reason


# Required keys in the raw model output
_REQUIRED_KEYS: frozenset[str] = frozenset({
    "classification",
    "reasoning_summary",
    "risk_notes",
    "confidence",
})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_classification_output(raw: object) -> tuple[ClassificationResult | None, str]:
    """
    Validate raw LLM output against the classification schema.

    Returns (ClassificationResult, "") on success.
    Returns (None, reason) on any validation failure.

    Rules (fail-closed):
    - raw must be a dict
    - all four required keys must be present
    - classification must be a non-empty string
    - confidence must be numeric; clamped to [0.0, 1.0]
    """
    if not isinstance(raw, dict):
        return None, "output_not_a_dict"

    missing = _REQUIRED_KEYS - raw.keys()
    if missing:
        return None, f"missing_keys:{','.join(sorted(missing))}"

    classification = str(raw.get("classification", "")).strip()
    if not classification:
        return None, "classification_empty"

    reasoning = str(raw.get("reasoning_summary", "")).strip()
    risk      = str(raw.get("risk_notes", "")).strip()

    raw_conf = raw.get("confidence")
    # Explicitly reject booleans: float(True)==1.0 would silently pass,
    # but a model returning True/False for confidence is a schema error.
    # Fail-closed per M31 hardening rule.
    if isinstance(raw_conf, bool):
        return None, f"confidence_not_numeric:{raw_conf!r}"
    try:
        confidence = float(raw_conf)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None, f"confidence_not_numeric:{raw_conf!r}"

    # Clamp to [0.0, 1.0]
    confidence = max(0.0, min(1.0, confidence))

    return ClassificationResult(
        classification=classification,
        reasoning_summary=reasoning,
        risk_notes=risk,
        confidence=confidence,
        provider="",        # filled by caller
        backend="",         # filled by caller
        latency_ms=0,       # filled by caller
        fallback_used=False,
        validation="passed",
    ), ""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_classification_prompt(text: str, context_hint: str = "") -> str:
    """
    Build a tight prompt that instructs the model to return classification JSON.

    The prompt is designed to produce ONLY the required JSON — no prose, no
    markdown fences, no commentary before or after.
    """
    ctx_clause = f"\nContext hint: {context_hint}" if context_hint.strip() else ""
    return (
        "You are an internal classification assistant for AssistantOS.\n"
        "You are advisory only. You have NO execution authority.\n\n"
        "Classify the following user text and return ONLY valid JSON "
        "with this exact shape — no markdown, no prose:\n"
        '{"classification":"<WORK|FIN|CODE|OTHER>","reasoning_summary":"<brief>","risk_notes":"<brief or empty>","confidence":<0.0-1.0>}\n\n'
        "Rules:\n"
        "- classification must be exactly one of: WORK, FIN, CODE, OTHER\n"
        "- confidence must be a float between 0.0 and 1.0\n"
        "- be concise; leave risk_notes empty string if no risk\n"
        "- output ONLY the JSON object, nothing else\n"
        f"{ctx_clause}\n"
        f"User text: {text}\n"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify_with_local_llm(
    text: str,
    context_hint: str = "",
) -> Optional[ClassificationResult]:
    """
    Run a bounded classification advisory using the configured local LLM.

    Returns ClassificationResult on success (validation passed).
    Returns None on any failure (disabled, offline, timeout, invalid output).
    The caller must implement deterministic fallback when None is returned.

    This function NEVER raises — all errors are absorbed and logged.
    """
    try:
        from ..mso.local_llm_adapter import consult_advisory, is_enabled, _normalized_provider
        from ..config import LOCAL_LLM_TIMEOUT_SECONDS
    except ImportError as exc:
        _log.debug("classify_with_local_llm: import error: %s", exc)
        return None

    if not is_enabled():
        return None

    provider = _normalized_provider()

    # Build a classification-specific prompt
    prompt = build_classification_prompt(text, context_hint)

    # Reuse the unified advisory consultation path but with a classification prompt.
    # We send it as a LocalLlmRequest so the adapter handles timeout/transport.
    try:
        from ..mso.contracts import LocalLlmRequest
        from ..mso.local_llm_adapter import _extract_json_object

        # Dispatch directly to the provider-specific generate function
        # so we can get raw content + latency without advisory normalisation.
        if provider == "ollama":
            from ..mso.local_llm_adapter import _ollama_generate
            raw_dict, error, latency_ms = _ollama_generate(prompt)
        elif provider == "llamacpp":
            from ..mso.local_llm_adapter import _llamacpp_complete
            raw_dict, error, latency_ms = _llamacpp_complete(prompt)
        else:
            _log.debug("classify_with_local_llm: unsupported provider %s", provider)
            return None

        if error or raw_dict is None:
            _log.debug("classify_with_local_llm: LLM call failed: %s", error)
            return None

        result, validation_error = validate_classification_output(raw_dict)
        if result is None:
            _log.debug("classify_with_local_llm: validation failed: %s", validation_error)
            return None

        # Fill provenance fields
        result["provider"]   = "local_llm"
        result["backend"]    = provider
        result["latency_ms"] = latency_ms
        return result

    except Exception as exc:
        _log.debug("classify_with_local_llm: unexpected error: %s", exc)
        return None
