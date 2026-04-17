"""
Cognitive provider registry and health facade.

Bridges the existing mso.local_llm_adapter probe into the M29 UI-facing
ProviderHealth contract. All state is derived from real backend probes.
"""
from __future__ import annotations

import time
from typing import Any, Optional, TypedDict

from ..config import (
    ASSISTANT_LOCAL_LLM_ENABLED,
    COGNITION_DEFAULT_POLICY,
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_MODEL,
    LOCAL_LLM_PROVIDER,
    MSO_ENABLED,
)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

class ProviderHealth(TypedDict, total=False):
    """Health snapshot for a single cognitive provider."""

    provider_id: str
    label: str
    backend: str         # "ollama" | "llamacpp" | "none"
    model: str
    status: str          # "online" | "offline" | "degraded" | "disabled"
    latency_ms: int
    available_tasks: list[str]
    degraded: bool
    last_health_check: Optional[str]   # ISO 8601 or None
    error: Optional[str]
    feature_enabled: bool


class ProvidersResponse(TypedDict):
    """Response envelope for GET /cognition/providers."""

    ok: bool
    providers: list[ProviderHealth]
    ui_cognition_enabled: bool
    default_policy: str


# Tasks this provider can participate in (non-authoritative, advisory only)
_LOCAL_LLM_TASKS: list[str] = [
    "orchestrator_advisory",
    "classification_hint",
    "routing_hint",
    "code_packaging",
    "reasoning_summary",
]


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _build_disabled_provider() -> ProviderHealth:
    """Return a provider entry that clearly signals the feature is off."""
    return ProviderHealth(
        provider_id="local_llm",
        label="Local Cognitive Engine",
        backend=LOCAL_LLM_PROVIDER or "none",
        model=LOCAL_LLM_MODEL or "",
        status="disabled",
        latency_ms=0,
        available_tasks=[],
        degraded=False,
        last_health_check=None,
        error="Local cognition feature not enabled",
        feature_enabled=False,
    )


def get_providers() -> ProvidersResponse:
    """
    Return the list of cognitive providers and their current health.

    Calls the real probe only when the feature flag is on.
    Never invents status — always derives from real state.
    """
    from ..config import ASSISTANT_UI_SHOW_COGNITION

    if not ASSISTANT_LOCAL_LLM_ENABLED:
        return ProvidersResponse(
            ok=True,
            providers=[_build_disabled_provider()],
            ui_cognition_enabled=False,
            default_policy=COGNITION_DEFAULT_POLICY,
        )

    provider = _probe_local_provider()
    return ProvidersResponse(
        ok=True,
        providers=[provider],
        ui_cognition_enabled=ASSISTANT_UI_SHOW_COGNITION,
        default_policy=COGNITION_DEFAULT_POLICY,
    )


def get_providers_health() -> list[ProviderHealth]:
    """Return just the health list — used by the health-only endpoint."""
    return get_providers()["providers"]


def _probe_local_provider() -> ProviderHealth:
    """
    Probe the local LLM adapter and translate LocalLlmStatus → ProviderHealth.
    Timeout / error is caught here so callers always get a structured result.
    """
    from ..mso.local_llm_adapter import probe_local_llm, is_enabled

    checked_at = _now_iso()

    if not is_enabled():
        return ProviderHealth(
            provider_id="local_llm",
            label="Local Cognitive Engine",
            backend=LOCAL_LLM_PROVIDER or "none",
            model=LOCAL_LLM_MODEL or "",
            status="disabled",
            latency_ms=0,
            available_tasks=[],
            degraded=False,
            last_health_check=checked_at,
            error="MSO_ENABLED or LOCAL_LLM_* not configured",
            feature_enabled=True,
        )

    try:
        status = probe_local_llm(roundtrip=False)
    except Exception as exc:
        return ProviderHealth(
            provider_id="local_llm",
            label="Local Cognitive Engine",
            backend=LOCAL_LLM_PROVIDER or "none",
            model=LOCAL_LLM_MODEL or "",
            status="offline",
            latency_ms=0,
            available_tasks=[],
            degraded=False,
            last_health_check=checked_at,
            error=f"Probe exception: {exc}",
            feature_enabled=True,
        )

    reachable: bool = bool(status.get("reachable"))
    model_ok: bool = bool(status.get("model_available"))
    latency: int = int(status.get("latency_ms", 0))
    error: Optional[str] = status.get("error")

    if not reachable:
        ui_status = "offline"
        degraded = False
        tasks: list[str] = []
    elif not model_ok:
        ui_status = "degraded"
        degraded = True
        tasks = []
    else:
        ui_status = "online"
        degraded = False
        tasks = _LOCAL_LLM_TASKS

    return ProviderHealth(
        provider_id="local_llm",
        label="Local Cognitive Engine",
        backend=LOCAL_LLM_PROVIDER or "none",   # reflects real configured provider
        model=LOCAL_LLM_MODEL or "",
        status=ui_status,
        latency_ms=latency,
        available_tasks=tasks,
        degraded=degraded,
        last_health_check=checked_at,
        error=error,
        feature_enabled=True,
    )
