"""
MSO Cognitive Seat Status — observable seat state for the Master Sovereign Operator.

Spec reference: S-MSO-SEAT-METADATA-OBSERVABILITY-01

Provides:
- build_mso_seat_status()        — full observable seat status dict
- set_runtime_seat_provider()    — in-memory only provider override (thread-safe)
- get_effective_provider_name()  — runtime override or env config
- reset_runtime_seat_override_for_tests() — test teardown helper

Invariants (enforced here, never relaxed):
- used_execution is always False
- cognitive_only is always True
- can_execute is always False

No network calls are made in this module. Provider availability is config-derived only.
"""
from __future__ import annotations

import threading
from typing import Any


# ---------------------------------------------------------------------------
# Static provider metadata (operator-curated, no network)
# ---------------------------------------------------------------------------

_PROVIDER_STATIC_METADATA: dict[str, dict] = {
    "anthropic": {
        "cost_tier": "medium",
        "quality_tier": "high",
        "latency_tier": "medium",
        "recommended_for": ["conversation", "planning", "validation"],
        "source": "static_operator_metadata",
    },
    "llama": {
        "cost_tier": "low",
        "quality_tier": "variable",
        "latency_tier": "low",
        "recommended_for": ["local_private", "cheap_cognition"],
        "source": "static_operator_metadata",
    },
    "openai": {
        "cost_tier": "medium_high",
        "quality_tier": "high",
        "latency_tier": "medium",
        "recommended_for": ["conversation", "planning"],
        "source": "static_operator_metadata",
    },
    "gemma": {
        "cost_tier": "low",
        "quality_tier": "medium",
        "latency_tier": "low",
        "recommended_for": ["local_private"],
        "source": "static_operator_metadata",
    },
}


# ---------------------------------------------------------------------------
# Runtime seat override (thread-safe, in-memory only)
# ---------------------------------------------------------------------------

_runtime_lock = threading.Lock()
_runtime_provider_override: str | None = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def get_effective_provider_name() -> str | None:
    """Return runtime override if set, else MSO_SEAT_PROVIDER from env."""
    with _runtime_lock:
        if _runtime_provider_override is not None:
            return _runtime_provider_override
    from ..config import MSO_SEAT_PROVIDER

    return MSO_SEAT_PROVIDER or None


def reset_runtime_seat_override_for_tests() -> None:
    """Reset the in-memory override. Call this in test teardown only."""
    global _runtime_provider_override
    with _runtime_lock:
        _runtime_provider_override = None


def set_runtime_seat_provider(provider_name: str) -> dict:
    """
    Set the runtime (in-memory only) MSO seat provider.

    - Validates provider name against SUPPORTED_PROVIDER_NAMES
    - Rejects unknown providers
    - Does NOT call provider, issue tokens, call Police, or execute anything
    - runtime_only=True always (not persisted to env or disk)

    Returns a result dict, never raises.
    """
    global _runtime_provider_override
    from .seat_model_provider import SUPPORTED_PROVIDER_NAMES

    name = provider_name.strip().lower() if provider_name else ""
    if not name or name not in SUPPORTED_PROVIDER_NAMES:
        return {
            "ok": False,
            "error": (
                f"Unknown provider: {provider_name!r}. "
                f"Allowed: {sorted(SUPPORTED_PROVIDER_NAMES)}"
            ),
            "runtime_only": True,
            "used_execution": False,
            "cognitive_only": True,
        }

    # Resolve to check availability (no network — config-derived only)
    from .seat_model_provider_registry import resolve_provider

    resolved = resolve_provider(name)
    if resolved is not None and resolved.availability == "not_implemented":
        return {
            "ok": False,
            "error": (
                f"Provider {name!r} is known but not implemented. No adapter exists."
            ),
            "provider": name,
            "availability": "not_implemented",
            "runtime_only": True,
            "used_execution": False,
            "cognitive_only": True,
        }

    with _runtime_lock:
        _runtime_provider_override = name

    return {
        "ok": True,
        "runtime_only": True,
        "active_provider": name,
        "requires_restart_for_env": False,
        "note": (
            f"Provider set to {name!r} for this runtime session only. "
            "Set MSO_SEAT_PROVIDER in environment to persist across restarts."
        ),
        "used_execution": False,
        "cognitive_only": True,
    }


# ---------------------------------------------------------------------------
# Main observable status builder
# ---------------------------------------------------------------------------


def build_mso_seat_status() -> dict[str, Any]:
    """
    Build the current MSO cognitive seat status.

    Returns active seat, all available seats with metadata, and selection info.
    Never makes network calls. Provider availability is config-derived only.
    used_execution is always False (invariant).
    """
    try:
        from ..config import MSO_SEAT_PROVIDER
        from .seat_model_provider import SUPPORTED_PROVIDER_NAMES
        from .seat_model_provider_registry import list_all_providers, resolve_provider

        # -- Determine selection source -----------------------------------
        with _runtime_lock:
            runtime_override = _runtime_provider_override

        if runtime_override is not None:
            effective_name: str | None = runtime_override
            selection_source = "runtime_override"
        elif MSO_SEAT_PROVIDER:
            effective_name = MSO_SEAT_PROVIDER
            selection_source = "env"
        else:
            effective_name = None
            selection_source = "not_configured"

        # -- Resolve active provider --------------------------------------
        resolved = resolve_provider(effective_name) if effective_name else None
        static_meta = _PROVIDER_STATIC_METADATA.get(effective_name or "", {})

        if resolved is not None:
            active_seat: dict[str, Any] = {
                "provider": resolved.provider_name.value,
                "model": resolved.model_name,
                "availability": resolved.availability,
                "selection_source": selection_source,
                "local_or_remote": resolved.local_or_remote,
                "supports_chat": resolved.supports_chat,
                "supports_planning": resolved.supports_plan_only,
                "supports_validation": resolved.supports_plan_only,
                "supports_orchestration": False,
                "can_execute": False,
                "cognitive_only": True,
                "cost_tier": static_meta.get("cost_tier", "unknown"),
                "quality_tier": static_meta.get("quality_tier", "unknown"),
                "latency_tier": static_meta.get("latency_tier", "unknown"),
                "notes": list(resolved.safety_notes),
                "metadata_source": "static_operator_metadata",
            }
        else:
            # No provider configured or resolved
            active_seat = {
                "provider": effective_name,
                "model": None,
                "availability": "not_configured",
                "selection_source": selection_source,
                "local_or_remote": None,
                "supports_chat": False,
                "supports_planning": False,
                "supports_validation": False,
                "supports_orchestration": False,
                "can_execute": False,
                "cognitive_only": True,
                "cost_tier": static_meta.get("cost_tier", "unknown"),
                "quality_tier": static_meta.get("quality_tier", "unknown"),
                "latency_tier": static_meta.get("latency_tier", "unknown"),
                "notes": [],
                "metadata_source": "static_operator_metadata",
            }

        # -- Build available seats list -----------------------------------
        available_seats: list[dict[str, Any]] = []
        for provider in list_all_providers():
            p_name = provider.provider_name.value
            p_static = _PROVIDER_STATIC_METADATA.get(p_name, {})
            available_seats.append(
                {
                    "provider": p_name,
                    "status": provider.availability,
                    "model": provider.model_name,
                    "local_or_remote": provider.local_or_remote,
                    "cost_tier": p_static.get("cost_tier", "unknown"),
                    "quality_tier": p_static.get("quality_tier", "unknown"),
                    "latency_tier": p_static.get("latency_tier", "unknown"),
                    "recommended_for": list(p_static.get("recommended_for", [])),
                    "metadata_source": "static_operator_metadata",
                }
            )

        # -- Build selection metadata -------------------------------------
        selection: dict[str, Any] = {
            "current_provider": effective_name,
            "selection_source": selection_source,
            "can_change_runtime": True,
            "change_method": "runtime_store",
            "change_instruction": (
                "POST /mso/seat/provider or set MSO_SEAT_PROVIDER env var"
            ),
            "allowed_providers": sorted(SUPPORTED_PROVIDER_NAMES),
            "runtime_only": True,
        }

        return {
            "active_seat": active_seat,
            "available_seats": available_seats,
            "selection": selection,
            "used_execution": False,
            "cognitive_only": True,
        }

    except Exception as exc:
        return {
            "active_seat": {
                "provider": None,
                "availability": "unknown",
                "can_execute": False,
                "used_execution": False,
                "cognitive_only": True,
            },
            "available_seats": [],
            "selection": {
                "current_provider": None,
                "can_change_runtime": True,
                "change_method": "runtime_store",
            },
            "used_execution": False,
            "cognitive_only": True,
            "error": f"{type(exc).__name__}: {exc}",
        }
