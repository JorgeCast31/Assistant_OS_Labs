"""Explicit role-based authorization for operator actions."""

from __future__ import annotations

from .contracts import OperatorIdentity, OperatorRole
from .operator_identity import get_operator_identity, touch_operator_identity


class OperatorAuthorizationError(PermissionError):
    """Raised when an operator is missing, inactive, or unauthorized."""


_ACTION_MIN_ROLE: dict[str, OperatorRole] = {
    "acknowledge_restriction": "reviewer",
    "clear_restriction": "admin",
    "extend_restriction": "admin",
    "override_restriction": "admin",
}
_ROLE_RANK: dict[OperatorRole, int] = {
    "viewer": 1,
    "reviewer": 2,
    "admin": 3,
}


def _load_active_operator(operator_id: str) -> OperatorIdentity:
    if not operator_id.strip():
        raise OperatorAuthorizationError("operator_id is required")
    operator = get_operator_identity(operator_id.strip())
    if operator is None:
        raise OperatorAuthorizationError(f"Unknown operator_id: {operator_id}")
    if not operator.is_active:
        raise OperatorAuthorizationError(f"Inactive operator_id: {operator_id}")
    return operator


def authorize_operator_read(operator_id: str) -> OperatorIdentity:
    """Validate an operator for read-only admin access."""

    operator = _load_active_operator(operator_id)
    touch_operator_identity(operator.operator_id)
    return operator


def authorize_operator_action(operator_id: str, action_type: str) -> OperatorIdentity:
    """Validate an operator for a governed restriction action."""

    operator = _load_active_operator(operator_id)
    required_role = _ACTION_MIN_ROLE.get(action_type)
    if required_role is None:
        raise OperatorAuthorizationError(f"Unsupported operator action: {action_type}")
    if _ROLE_RANK[operator.role] < _ROLE_RANK[required_role]:
        raise OperatorAuthorizationError(
            f"Operator role {operator.role} cannot perform {action_type}"
        )
    touch_operator_identity(operator.operator_id)
    return operator
