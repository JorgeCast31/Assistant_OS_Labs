"""
MSO Seat Model Provider Registry — honest provider selection for Delegated MSO Seat.

Selection is config/env driven. Default provider is set by MSO_SEAT_PROVIDER.
Provider availability is always derived from real configuration state — never fabricated.

Supported providers:
  anthropic — remote API, requires ANTHROPIC_API_KEY
  openai    — not yet implemented (no adapter)
  llama     — local backend (ollama or llamacpp), requires MSO_ENABLED + LOCAL_LLM_*
  gemma     — not yet implemented (no adapter)

Unknown provider names are rejected — fail-closed.

No network calls are made in this module. Availability is config-derived only.
Actual liveness probes (round-trip) are done by the cognition layer on demand.
"""
from __future__ import annotations

from typing import Optional

from .seat_model_provider import (
    MSOSeatModelProvider,
    ModelProviderName,
    ModelProviderResponse,
    SUPPORTED_PROVIDER_NAMES,
    make_unavailable_response,
    validate_provider_name,
)


# ---------------------------------------------------------------------------
# Internal resolver helpers (no network, config-derived only)
# ---------------------------------------------------------------------------


def _resolve_anthropic() -> MSOSeatModelProvider:
    """
    Resolve Anthropic provider availability from environment config.

    Availability:
    - "available"     if ANTHROPIC_API_KEY is set (non-empty)
    - "api_key_missing" otherwise
    """
    from ..config import ANTHROPIC_API_KEY, CODE_REVIEW_MODEL, MSO_SEAT_MODEL

    api_key_set = bool(ANTHROPIC_API_KEY and ANTHROPIC_API_KEY.strip())
    model = MSO_SEAT_MODEL or CODE_REVIEW_MODEL or "claude-haiku-4-5-20251001"

    return MSOSeatModelProvider(
        provider_name=ModelProviderName.ANTHROPIC,
        model_name=model,
        availability="available" if api_key_set else "api_key_missing",
        local_or_remote="remote",
        supports_chat=True,
        supports_plan_only=True,
        safety_notes=(
            "cognitive_only",
            "requires_policy_decision",
            "no_direct_execution",
        ),
        config_source="env",
    )


def _resolve_llama() -> MSOSeatModelProvider:
    """
    Resolve local Llama provider availability from environment config.

    Availability:
    - "available"               if MSO_ENABLED + LOCAL_LLM_PROVIDER + LOCAL_LLM_BASE_URL all set
    - "local_endpoint_missing"  if MSO_ENABLED but LOCAL_LLM_BASE_URL or LOCAL_LLM_PROVIDER absent
    - "not_configured"          if MSO_ENABLED is False or all config absent
    """
    from ..config import (
        MSO_ENABLED,
        LOCAL_LLM_PROVIDER,
        LOCAL_LLM_BASE_URL,
        LOCAL_LLM_MODEL,
        MSO_SEAT_MODEL,
    )

    model = MSO_SEAT_MODEL or LOCAL_LLM_MODEL or ""

    if not MSO_ENABLED:
        return MSOSeatModelProvider(
            provider_name=ModelProviderName.LLAMA,
            model_name=model,
            availability="not_configured",
            local_or_remote="local",
            supports_chat=True,
            supports_plan_only=True,
            safety_notes=("cognitive_only", "local_endpoint", "no_direct_execution"),
            config_source="env",
        )

    has_provider = bool(LOCAL_LLM_PROVIDER and LOCAL_LLM_PROVIDER.strip())
    has_url = bool(LOCAL_LLM_BASE_URL and LOCAL_LLM_BASE_URL.strip())

    if has_provider and has_url:
        avail = "available"
    else:
        avail = "local_endpoint_missing"

    return MSOSeatModelProvider(
        provider_name=ModelProviderName.LLAMA,
        model_name=model,
        availability=avail,
        local_or_remote="local",
        supports_chat=True,
        supports_plan_only=True,
        safety_notes=("cognitive_only", "local_endpoint", "no_direct_execution"),
        config_source="env",
    )


def _resolve_openai() -> MSOSeatModelProvider:
    """OpenAI provider — no adapter implemented yet. Always not_implemented."""
    from ..config import MSO_SEAT_MODEL

    return MSOSeatModelProvider(
        provider_name=ModelProviderName.OPENAI,
        model_name=MSO_SEAT_MODEL or "gpt-4o",
        availability="not_implemented",
        local_or_remote="remote",
        supports_chat=False,
        supports_plan_only=False,
        safety_notes=(
            "not_implemented",
            "cognitive_only",
            "no_direct_execution",
        ),
        config_source="none",
    )


def _resolve_gemma() -> MSOSeatModelProvider:
    """Gemma provider — no adapter implemented yet. Always not_implemented."""
    from ..config import MSO_SEAT_MODEL

    return MSOSeatModelProvider(
        provider_name=ModelProviderName.GEMMA,
        model_name=MSO_SEAT_MODEL or "gemma3:4b",
        availability="not_implemented",
        local_or_remote="local",
        supports_chat=False,
        supports_plan_only=False,
        safety_notes=(
            "not_implemented",
            "cognitive_only",
            "no_direct_execution",
        ),
        config_source="none",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_provider(name: str) -> Optional[MSOSeatModelProvider]:
    """
    Resolve a provider by name, returning its honest availability state.

    Returns None for unknown/invalid provider names (fail-closed).

    Parameters
    ----------
    name : str
        Provider name (case-insensitive): "anthropic", "openai", "llama", "gemma".

    Returns
    -------
    MSOSeatModelProvider or None
        Provider metadata if name is known, None if unknown/invalid.
    """
    ok, provider_enum = validate_provider_name(name)
    if not ok or provider_enum is None:
        return None

    if provider_enum == ModelProviderName.ANTHROPIC:
        return _resolve_anthropic()
    if provider_enum == ModelProviderName.LLAMA:
        return _resolve_llama()
    if provider_enum == ModelProviderName.OPENAI:
        return _resolve_openai()
    if provider_enum == ModelProviderName.GEMMA:
        return _resolve_gemma()

    return None


def get_seated_provider() -> Optional[MSOSeatModelProvider]:
    """
    Return the currently configured Delegated MSO Seat provider.

    Reads MSO_SEAT_PROVIDER from environment/config.

    Returns
    -------
    MSOSeatModelProvider if a valid provider is configured.
    None if MSO_SEAT_PROVIDER is not set or is empty.
    """
    from ..config import MSO_SEAT_PROVIDER

    if not MSO_SEAT_PROVIDER:
        return None

    return resolve_provider(MSO_SEAT_PROVIDER)


def list_all_providers() -> list[MSOSeatModelProvider]:
    """
    Return metadata for all known providers with their honest availability status.

    This never makes network calls — availability is derived from config only.

    Returns
    -------
    list[MSOSeatModelProvider]
        One entry per supported provider, in canonical order.
    """
    return [
        _resolve_anthropic(),
        _resolve_openai(),
        _resolve_llama(),
        _resolve_gemma(),
    ]


def describe_seated_provider() -> str:
    """
    Human-readable description of the currently seated provider.

    Returns
    -------
    str
        Description string for display/logging. Never empty.
    """
    provider = get_seated_provider()
    if provider is None:
        return "No cognitive provider is currently seated/configured."

    status = provider.availability
    name = provider.provider_name.value
    model = provider.model_name or "(model not configured)"

    if provider.is_available:
        return f"Seated provider: {name} / {model} [available]"
    return f"Seated provider: {name} / {model} [{status}]"


def make_orchestration_proposal(
    *,
    user_intent: str,
    domain: str = "UNKNOWN",
    requested_action: str = "",
    resource: Optional[str] = None,
    capability_name: str = "",
    capability_scope: tuple[str, ...] = (),
    risk_level: str = "unknown",
    delegated_seat_ref: Optional[str] = None,
) -> "MSOExecutionProposal":
    """
    Produce a structured non-executing orchestration proposal from the seated provider.

    If the provider is available, its description is included as a plan step.
    If the provider is unavailable, a safe deterministic fallback is returned.

    This function NEVER:
    - calls a runner or pipeline
    - executes commands
    - mutates files
    - sets execution_allowed=True

    The returned proposal is always:
    - cognitive_only: True
    - used_execution: False
    - execution_allowed: False
    - next_required_authority: (PolicyDecision, CapabilityToken, OperationBinding,
                                AuthorizedPlan, PoliceGate)

    Parameters
    ----------
    user_intent : str
        The original user request or intent.
    domain : str
        Classified domain (e.g., "CODE", "FIN", "WORK", "ASSISTANT", "UNKNOWN").
    requested_action : str
        Specific action within domain. Empty if unknown.
    capability_name : str
        Required capability name for execution. Empty if not applicable.
    capability_scope : tuple[str, ...]
        Capability scope values required for execution.
    risk_level : str
        "low" | "medium" | "high" | "unknown"
    delegated_seat_ref : Optional[str]
        The seat reference associated with this proposal, for traceability.

    Returns
    -------
    MSOExecutionProposal
        Immutable cognitive-only proposal. Never an execution result.
    """
    from .execution_proposal import (
        MSOExecutionProposal,
        build_execution_proposal,
        build_safe_fallback_proposal,
    )

    provider = get_seated_provider()

    if provider is None:
        return build_safe_fallback_proposal(
            user_intent=user_intent,
            reason="No cognitive provider is currently seated/configured.",
            delegated_seat_ref=delegated_seat_ref,
        )

    if not provider.is_available:
        return build_safe_fallback_proposal(
            user_intent=user_intent,
            reason=f"Provider {provider.provider_name.value!r} is {provider.availability}.",
            delegated_seat_ref=delegated_seat_ref,
        )

    # Provider is available: build a structured proposal with provider metadata.
    provider_description = describe_seated_provider()
    plan_steps: tuple[str, ...] = (
        f"Cognitive provider: {provider_description}",
        f"Domain classified as: {domain}",
        f"Requested action: {requested_action or '(not resolved)'}",
        f"Required capability: {capability_name or '(not declared)'}",
        "Execution requires: PolicyDecision → CapabilityToken → OperationBinding "
        "→ AuthorizedPlan → PoliceGate.",
        "This proposal is cognitive-only. No execution has occurred.",
    )

    notes = (
        f"Proposal produced by seated provider: {provider.provider_name.value} "
        f"/ {provider.model_name or '(model unknown)'}. "
        "Human confirmation is required before any execution can proceed."
    )

    return build_execution_proposal(
        user_intent=user_intent,
        domain=domain,
        requested_action=requested_action,
        resource=resource,
        capability_name=capability_name,
        capability_scope=capability_scope,
        risk_level=risk_level,
        requires_human_confirmation=True,
        delegated_seat_ref=delegated_seat_ref,
        provider_name=provider.provider_name.value,
        model_name=provider.model_name or None,
        plan_steps=plan_steps,
        notes=notes,
    )


def make_plan_response(*, delegated_seat_ref: Optional[str] = None) -> ModelProviderResponse:
    """
    Return a cognitive-only plan response from the seated provider.

    If no provider is configured or available, returns a structured
    unavailable response (never crashes).

    This response is always:
    - cognitive_only: True
    - used_execution: False

    Parameters
    ----------
    delegated_seat_ref : Optional[str]
        The seat reference to associate with this response for traceability.

    Returns
    -------
    ModelProviderResponse
        Structured cognitive-only response.
    """
    from .seat_model_provider import make_cognitive_response

    provider = get_seated_provider()

    if provider is None:
        return make_unavailable_response(
            provider_name="none",
            model_name="",
            reason="No cognitive provider is currently seated/configured.",
        )

    if not provider.is_available:
        return make_unavailable_response(
            provider_name=provider.provider_name.value,
            model_name=provider.model_name,
            reason=f"Provider {provider.provider_name.value} is {provider.availability}.",
        )

    meta: dict = {
        "cognitive_only": True,
        "non_executing": True,
        "provider": provider.to_dict(),
    }
    if delegated_seat_ref:
        meta["delegated_seat_ref"] = delegated_seat_ref

    return make_cognitive_response(
        text=describe_seated_provider(),
        provider_name=provider.provider_name.value,
        model_name=provider.model_name,
        metadata=meta,
    )
