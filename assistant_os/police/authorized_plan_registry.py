"""Police-internal plan ref registry.

Minimal process-local registry for Police Gate plan binding validation.
Police works with opaque string refs, not runtime objects.
"""

from __future__ import annotations

from typing import Any

_STATUS_ACTIVE = "active"
_STATUS_REVOKED = "revoked"

# authorized_plan_ref (str) -> binding metadata
_registry: dict[str, dict[str, Any]] = {}


def register_authorized_plan_ref(
    authorized_plan_ref: str,
    *,
    execution_id: str,
    token_ref: str,
    binding_ref: str,
    status: str = _STATUS_ACTIVE,
    capability_scope: tuple[str, ...] | None = None,
) -> None:
    """Register a Police-visible authorized plan reference."""
    _registry[authorized_plan_ref] = {
        "execution_id": execution_id,
        "token_ref": token_ref,
        "binding_ref": binding_ref,
        "status": status,
        "capability_scope": tuple(capability_scope or ()),
    }


def _lookup(authorized_plan_ref: str) -> dict[str, Any] | None:
    """Return the registered plan binding metadata, or None if unknown."""
    return _registry.get(authorized_plan_ref)


def _reset_for_testing() -> None:
    """Clear all registered authorized plan refs.

    FOR TEST USE ONLY — provides isolation between test cases.
    Never call from production code.
    """
    _registry.clear()
