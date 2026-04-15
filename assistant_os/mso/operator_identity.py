"""Minimal operator identity registry for governed admin access."""

from __future__ import annotations

from dataclasses import replace

from ..contracts import now_iso
from .contracts import OperatorIdentity

_BOOTSTRAP_TS = "2026-04-14T00:00:00+00:00"
_BOOTSTRAP_OPERATORS: dict[str, OperatorIdentity] = {
    "ops-viewer": OperatorIdentity(
        operator_id="ops-viewer",
        role="viewer",
        is_active=True,
        created_at=_BOOTSTRAP_TS,
    ),
    "ops-reviewer": OperatorIdentity(
        operator_id="ops-reviewer",
        role="reviewer",
        is_active=True,
        created_at=_BOOTSTRAP_TS,
    ),
    "ops-admin": OperatorIdentity(
        operator_id="ops-admin",
        role="admin",
        is_active=True,
        created_at=_BOOTSTRAP_TS,
    ),
}
_operators: dict[str, OperatorIdentity] = {
    operator_id: replace(identity)
    for operator_id, identity in _BOOTSTRAP_OPERATORS.items()
}


def reset_operator_registry() -> None:
    """Reset the in-memory registry to the bootstrap operator set."""

    global _operators
    _operators = {
        operator_id: replace(identity)
        for operator_id, identity in _BOOTSTRAP_OPERATORS.items()
    }


def get_operator_identity(operator_id: str) -> OperatorIdentity | None:
    """Return an operator identity by id."""

    if not operator_id:
        return None
    return _operators.get(operator_id)


def list_operator_identities() -> list[OperatorIdentity]:
    """Return the current operator registry."""

    return sorted(_operators.values(), key=lambda item: item.operator_id)


def touch_operator_identity(operator_id: str) -> OperatorIdentity | None:
    """Update the operator last-used timestamp after a validated action."""

    identity = get_operator_identity(operator_id)
    if identity is None:
        return None
    identity.last_used_at = now_iso()
    return identity


def set_operator_active(operator_id: str, *, is_active: bool) -> OperatorIdentity:
    """Test/support helper to toggle operator activation."""

    identity = get_operator_identity(operator_id)
    if identity is None:
        raise ValueError(f"Unknown operator_id: {operator_id}")
    identity.is_active = is_active
    return identity
