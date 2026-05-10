"""
MSO Seat Model Provider — cognitive provider contract for Delegated MSO Seat.

This module defines the minimal contract for interchangeable cognitive model
providers that may occupy the Delegated MSO Seat.

Design
------
A model provider is the *cognitive engine* powering a delegated seat.
It can classify, plan, summarize, propose, or explain.

It CANNOT:
- execute actions
- mutate the repo
- authorize itself
- bypass PolicyDecision, Police Gate, CapabilityToken, AuthorizedPlan

All provider responses carry:
- used_execution: False   (invariant — never changes)
- cognitive_only: True    (invariant — never changes)

Provider availability is always reported honestly:
- available: configured and reachable
- not_configured: required env vars missing
- api_key_missing: provider requires an API key that is not set
- local_endpoint_missing: local server URL not configured
- not_implemented: no adapter exists for this provider yet
- unavailable: configured but currently unreachable
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional, TypedDict


# ---------------------------------------------------------------------------
# Provider Identifiers
# ---------------------------------------------------------------------------


class ModelProviderName(str, Enum):
    """Supported cognitive model provider families for the Delegated MSO Seat."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    LLAMA = "llama"
    GEMMA = "gemma"


SUPPORTED_PROVIDER_NAMES: frozenset[str] = frozenset(
    {p.value for p in ModelProviderName}
)


# ---------------------------------------------------------------------------
# Availability Status
# ---------------------------------------------------------------------------


ModelProviderAvailabilityStatus = Literal[
    "available",
    "configured",
    "not_configured",
    "api_key_missing",
    "local_endpoint_missing",
    "not_implemented",
    "unavailable",
]

_AVAILABLE_STATUSES: frozenset[str] = frozenset({"available", "configured"})


# ---------------------------------------------------------------------------
# Provider Metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MSOSeatModelProvider:
    """
    Metadata contract for a cognitive model provider occupying a Delegated MSO Seat.

    This is NOT an execution authority. It describes which cognitive engine
    is currently powering the seat, and whether it is reachable/configured.

    Fields
    ------
    provider_name : ModelProviderName
        The provider family (anthropic, openai, llama, gemma).

    model_name : str
        The specific model identifier (e.g., "claude-haiku-4-5-20251001",
        "mistral:7b", "gpt-4o"). May be empty if not yet resolved.

    availability : ModelProviderAvailabilityStatus
        Honest operational status. Never fabricated.

    local_or_remote : "local" | "remote"
        Whether the provider runs locally or via a remote API.

    supports_chat : bool
        Whether the provider can handle chat-style interactions.

    supports_plan_only : bool
        Whether the provider can return plan-only (non-executing) responses.

    safety_notes : tuple[str, ...]
        Static safety annotations about this provider.

    config_source : str
        Where the configuration was loaded from (e.g., "env", "registry").
    """

    provider_name: ModelProviderName
    model_name: str
    availability: ModelProviderAvailabilityStatus
    local_or_remote: Literal["local", "remote"]
    supports_chat: bool = True
    supports_plan_only: bool = True
    safety_notes: tuple[str, ...] = field(default_factory=tuple)
    config_source: str = "env"

    @property
    def is_available(self) -> bool:
        """True only when provider is configured and reachable."""
        return self.availability in _AVAILABLE_STATUSES

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for audit/transport. Never includes secrets."""
        return {
            "provider_name": self.provider_name.value,
            "model_name": self.model_name,
            "availability": self.availability,
            "local_or_remote": self.local_or_remote,
            "supports_chat": self.supports_chat,
            "supports_plan_only": self.supports_plan_only,
            "safety_notes": list(self.safety_notes),
            "config_source": self.config_source,
            "is_available": self.is_available,
            "used_execution": False,
            "cognitive_only": True,
        }


# ---------------------------------------------------------------------------
# Provider Request / Response
# ---------------------------------------------------------------------------


class ModelProviderRequest(TypedDict, total=False):
    """Request envelope for a cognitive provider interaction."""

    prompt: str
    messages: list[dict[str, str]]
    task_type: str             # "chat" | "classify" | "plan" | "summarize"
    delegated_seat_ref: Optional[str]
    plan_only: bool            # If True, response must be plan-only (no execution)


class ModelProviderResponse(TypedDict):
    """
    Response envelope from a cognitive provider.

    Invariants (enforced by registry, not provider):
    - used_execution is ALWAYS False
    - cognitive_only is ALWAYS True
    """

    text: str
    provider_name: str
    model_name: str
    status: str                # "ok" | "unavailable" | "error"
    used_execution: bool       # invariant: always False
    cognitive_only: bool       # invariant: always True
    error: Optional[str]
    metadata: dict[str, Any]


# ---------------------------------------------------------------------------
# Response Constructors
# ---------------------------------------------------------------------------


def make_unavailable_response(
    *,
    provider_name: str,
    model_name: str = "",
    reason: str = "provider not configured",
) -> ModelProviderResponse:
    """Build a structured unavailable response. Never crashes the caller."""
    return ModelProviderResponse(
        text="",
        provider_name=provider_name,
        model_name=model_name,
        status="unavailable",
        used_execution=False,
        cognitive_only=True,
        error=reason,
        metadata={"cognitive_only": True, "non_executing": True},
    )


def make_cognitive_response(
    *,
    text: str,
    provider_name: str,
    model_name: str,
    metadata: Optional[dict[str, Any]] = None,
) -> ModelProviderResponse:
    """Build a valid cognitive-only response. Enforces safety invariants."""
    base_metadata: dict[str, Any] = {
        "cognitive_only": True,
        "non_executing": True,
    }
    if metadata:
        base_metadata.update(metadata)
    base_metadata["cognitive_only"] = True
    base_metadata["non_executing"] = True

    return ModelProviderResponse(
        text=text,
        provider_name=provider_name,
        model_name=model_name,
        status="ok",
        used_execution=False,
        cognitive_only=True,
        error=None,
        metadata=base_metadata,
    )


def validate_provider_name(name: str) -> tuple[bool, Optional[ModelProviderName]]:
    """
    Validate a provider name string.

    Returns
    -------
    (True, ModelProviderName) if valid.
    (False, None) if invalid.
    """
    try:
        return True, ModelProviderName(name.lower().strip())
    except ValueError:
        return False, None
