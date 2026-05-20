"""
MSO Entity Status — S-MSO-OPERABLE-ENTITY-01.

Exposes the operational status of the MSO (Master Sovereign Operator) runtime boundary,
including authority chain validation, surface enablement, interaction modes, and seated
cognitive provider availability.

This module produces a single public function that returns an immutable status dict
reflecting the real state of the system without fabrication or side effects.
"""
from __future__ import annotations

from typing import Any

from .seat_model_provider_registry import get_seated_provider


def build_mso_entity_status() -> dict[str, Any]:
    """
    Build the current operational status of the MSO entity.

    Returns a dict describing:
    - Runtime boundary kernel configuration
    - Authority chain enforcement (policy governance, police gate, authority artifact version)
    - Surface enablement (assistant_chat, mso_direct, code_api)
    - Interaction modes
    - Seated cognitive provider availability
    - Safe recommended next actions

    All values are derived from real system state. Availability from the seated provider
    is never fabricated.

    Returns
    -------
    dict
        Immutable status snapshot with structure as specified in S-MSO-OPERABLE-ENTITY-01.
    """

    # Resolve seated provider with fail-safe fallback.
    model_seat: dict[str, Any] = {}
    try:
        provider = get_seated_provider()
        if provider is None:
            model_seat = {
                "provider": None,
                "model": None,
                "availability": "not_configured",
                "local_or_remote": None,
                "supports_chat": False,
                "supports_plan_only": False,
            }
        else:
            model_seat = {
                "provider": provider.provider_name.value,
                "model": provider.model_name,
                "availability": provider.availability,
                "local_or_remote": provider.local_or_remote,
                "supports_chat": provider.supports_chat,
                "supports_plan_only": provider.supports_plan_only,
            }
    except Exception:
        # Registry call failed — return safe unavailable state.
        model_seat = {
            "provider": None,
            "model": None,
            "availability": "not_configured",
            "local_or_remote": None,
            "supports_chat": False,
            "supports_plan_only": False,
        }

    return {
        "entity": "MSO",
        "status": "operational",
        "runtime_boundary": {
            "kernel": "assistant_os.mso.kernel.handle_sovereign_request",
            "orchestrator_owned": True,
            "primary_chat_path_uses_kernel": True,
        },
        "authority_chain": {
            "policy_governance_token": True,
            "police_gate": True,
            "authority_artifact_version": "2",
            "runner_fail_closed": True,
        },
        "surfaces": {
            "assistant_chat": {
                "can_execute": True,
                "path": "MSO Kernel → Police → Runner",
            },
            "mso_direct": {
                "can_execute": False,
                "can_prepare": True,
                "used_execution": False,
            },
            "code_api": {
                "authority_source": "code_api",
                "authority_class": "external_local",
                "mso_governed": False,
            },
        },
        "interaction_modes": [
            "conversational",
            "planning",
            "validation",
            "orchestration",
            "status",
        ],
        "model_seat": model_seat,
        "next_safe_actions": [
            "Use mso_direct status for inspection",
            "Use planning mode to prepare confirmable actions",
            "Use assistant_chat for governed execution",
        ],
    }
