"""Explicit role-based authorization for operator actions."""

from __future__ import annotations

from datetime import datetime, timezone

from ..contracts import now_iso
from .contracts import OperatorAuthToken, OperatorContext, OperatorIdentity, OperatorRole
from .operator_identity import (
    get_operator_identity,
    get_operator_token_by_secret,
    touch_operator_identity,
    touch_operator_token,
)


class OperatorAuthorizationError(PermissionError):
    """Raised when an operator is missing, inactive, or unauthorized."""


class OperatorAuthenticationError(PermissionError):
    """Raised when an operator token is missing, invalid, inactive, or expired."""


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


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _validate_token_record(raw_token: str) -> tuple[OperatorAuthToken, OperatorIdentity]:
    token = get_operator_token_by_secret(raw_token.strip())
    if token is None:
        raise OperatorAuthenticationError("Invalid operator token")
    if not token.is_active:
        raise OperatorAuthenticationError("Operator token is inactive")
    expires_at = _parse_iso(token.expires_at)
    if expires_at is None or expires_at <= datetime.now(timezone.utc):
        raise OperatorAuthenticationError("Operator token is expired")
    operator = _load_active_operator(token.operator_id)
    return token, operator


def authenticate_operator_token(raw_token: str, *, request_id: str) -> OperatorContext:
    """Authenticate a raw token and build a per-request operator context."""

    if not raw_token.strip():
        raise OperatorAuthenticationError("Missing operator token")
    token, operator = _validate_token_record(raw_token)
    touch_operator_identity(operator.operator_id)
    touch_operator_token(token.token_id)
    return OperatorContext(
        operator_id=operator.operator_id,
        role=operator.role,
        token_id=token.token_id,
        request_id=request_id,
        authenticated_at=now_iso(),
    )


def authorize_operator_read(operator_id: str) -> OperatorIdentity:
    """Validate an operator for read-only admin access."""

    operator = _load_active_operator(operator_id)
    touch_operator_identity(operator.operator_id)
    return operator


def authorize_operator_context_read(context: OperatorContext) -> OperatorContext:
    """Validate a request context for read-only admin access."""

    _load_active_operator(context.operator_id)
    return context


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


def authorize_operator_context_action(context: OperatorContext, action_type: str) -> OperatorContext:
    """Validate an authenticated request context for a governed operator action."""

    required_role = _ACTION_MIN_ROLE.get(action_type)
    if required_role is None:
        raise OperatorAuthorizationError(f"Unsupported operator action: {action_type}")
    if _ROLE_RANK[context.role] < _ROLE_RANK[required_role]:
        raise OperatorAuthorizationError(
            f"Operator role {context.role} cannot perform {action_type}"
        )
    return context
