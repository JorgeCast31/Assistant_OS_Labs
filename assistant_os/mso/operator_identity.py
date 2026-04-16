"""Minimal operator identity and token registry for governed admin access."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import uuid

from ..contracts import now_iso
from ..config import (
    CONTROL_PLANE_MAX_ACTIVE_TOKENS_PER_OPERATOR,
    CONTROL_PLANE_TOKEN_DEFAULT_TTL_MINUTES,
    CONTROL_PLANE_TOKEN_MAX_TTL_MINUTES,
)
from ..storage.mso_store import list_operator_tokens, persist_operator_token, query_records
from .contracts import OperatorAuthToken, OperatorIdentity

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


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def credential_policy() -> dict[str, int]:
    """Return the enforced control-plane credential policy."""

    return {
        "default_ttl_minutes": CONTROL_PLANE_TOKEN_DEFAULT_TTL_MINUTES,
        "max_ttl_minutes": CONTROL_PLANE_TOKEN_MAX_TTL_MINUTES,
        "max_active_tokens_per_operator": CONTROL_PLANE_MAX_ACTIVE_TOKENS_PER_OPERATOR,
    }


def _active_tokens_for_operator(operator_id: str) -> list[OperatorAuthToken]:
    now_dt = datetime.now(timezone.utc)
    active: list[OperatorAuthToken] = []
    for token in list_operator_auth_tokens(operator_id=operator_id):
        if not token.is_active:
            continue
        expires_at = _parse_iso(token.expires_at)
        if expires_at is None or expires_at <= now_dt:
            continue
        active.append(token)
    return active


def create_operator_token(
    *,
    operator_id: str,
    ttl_minutes: int = CONTROL_PLANE_TOKEN_DEFAULT_TTL_MINUTES,
    rotated_from: str = "",
    rotation_reason: str = "",
    issued_reason: str = "",
) -> tuple[str, OperatorAuthToken]:
    """Create and persist a new opaque token for an active operator."""

    identity = get_operator_identity(operator_id)
    if identity is None:
        raise ValueError(f"Unknown operator_id: {operator_id}")
    if not identity.is_active:
        raise ValueError(f"Inactive operator_id: {operator_id}")
    policy = credential_policy()
    ttl = max(1, min(ttl_minutes, policy["max_ttl_minutes"]))
    active_tokens = _active_tokens_for_operator(operator_id)
    if len(active_tokens) >= policy["max_active_tokens_per_operator"]:
        raise ValueError(
            f"Operator {operator_id} reached max active tokens ({policy['max_active_tokens_per_operator']})"
        )
    issued_at = now_iso()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=ttl)
    ).isoformat()
    raw_token = secrets.token_urlsafe(32)
    record = OperatorAuthToken(
        token_id=str(uuid.uuid4()),
        operator_id=operator_id,
        issued_at=issued_at,
        expires_at=expires_at,
        is_active=True,
        token_hash=_hash_token(raw_token),
        rotated_from=rotated_from,
        rotation_reason=rotation_reason,
        issued_reason=issued_reason,
    )
    persist_operator_token(record)
    return raw_token, record


def list_operator_auth_tokens(*, operator_id: str = "", is_active: bool | None = None) -> list[OperatorAuthToken]:
    """List persisted operator token metadata."""

    items = list_operator_tokens(operator_id=operator_id, is_active=is_active)
    return [OperatorAuthToken(**item.get("payload", {})) for item in items]


def get_operator_token_by_id(token_id: str) -> OperatorAuthToken | None:
    """Return token metadata by token_id."""

    for item in query_records(kind="operator_tokens", limit=500):
        payload = item.get("payload", {})
        if payload.get("token_id") == token_id:
            return OperatorAuthToken(**payload)
    return None


def get_operator_token_by_secret(raw_token: str) -> OperatorAuthToken | None:
    """Resolve a persisted token by its opaque raw value."""

    token_hash = _hash_token(raw_token)
    for item in query_records(kind="operator_tokens", limit=500):
        payload = item.get("payload", {})
        stored_hash = str(payload.get("token_hash", ""))
        if stored_hash and hmac.compare_digest(stored_hash, token_hash):
            return OperatorAuthToken(**payload)
    return None


def revoke_token(token_id: str, *, revoked_by: str = "", reason: str = "") -> OperatorAuthToken:
    """Deactivate a persisted operator token."""

    token = get_operator_token_by_id(token_id)
    if token is None:
        raise ValueError(f"Unknown token_id: {token_id}")
    token.is_active = False
    token.revoked_at = now_iso()
    token.revoked_by = revoked_by
    if reason and not token.rotation_reason:
        token.rotation_reason = reason
    persist_operator_token(token)
    return token


def rotate_token(
    token_id: str,
    *,
    ttl_minutes: int = CONTROL_PLANE_TOKEN_DEFAULT_TTL_MINUTES,
    rotated_by: str = "",
    rotation_reason: str = "",
) -> tuple[str, OperatorAuthToken, OperatorAuthToken]:
    """Rotate an active token into a newly issued replacement."""

    current = get_operator_token_by_id(token_id)
    if current is None:
        raise ValueError(f"Unknown token_id: {token_id}")
    if not current.is_active:
        raise ValueError("Cannot rotate an inactive token")
    raw_token, new_record = create_operator_token(
        operator_id=current.operator_id,
        ttl_minutes=ttl_minutes,
        rotated_from=current.token_id,
        rotation_reason=rotation_reason or "token_rotation",
        issued_reason="rotation",
    )
    revoked = revoke_token(
        current.token_id,
        revoked_by=rotated_by,
        reason=rotation_reason or "token_rotation",
    )
    return raw_token, new_record, revoked


def cleanup_expired_operator_tokens(*, now_ts: str = "") -> list[OperatorAuthToken]:
    """Deactivate tokens that have expired but remain active."""

    now_dt = _parse_iso(now_ts) or datetime.now(timezone.utc)
    updated: list[OperatorAuthToken] = []
    for token in list_operator_auth_tokens():
        if not token.is_active:
            continue
        expires_at = _parse_iso(token.expires_at)
        if expires_at is None or expires_at > now_dt:
            continue
        token.is_active = False
        token.revoked_at = now_iso()
        token.revoked_by = "system:expiry_cleanup"
        persist_operator_token(token)
        updated.append(token)
    return updated


def touch_operator_token(token_id: str) -> OperatorAuthToken | None:
    """Update token last-used timestamp after a valid authenticated request."""

    token = get_operator_token_by_id(token_id)
    if token is None:
        return None
    token.last_used_at = now_iso()
    persist_operator_token(token)
    return token
