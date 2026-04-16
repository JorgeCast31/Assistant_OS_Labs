"""Formal operator token issuance, lifecycle, and audit helpers."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import logging

from ..contracts import now_iso
from ..mso.operator_identity import (
    cleanup_expired_operator_tokens,
    credential_policy,
    create_operator_token,
    list_operator_auth_tokens,
    revoke_token,
    rotate_token,
)

logger = logging.getLogger("assistant_os.control_plane")


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def issue_operator_token(*, operator_id: str, ttl_minutes: int = 60, issued_reason: str = "") -> dict:
    """Issue a new operator token and return the raw token exactly once."""

    raw_token, record = create_operator_token(
        operator_id=operator_id,
        ttl_minutes=ttl_minutes,
        issued_reason=issued_reason,
    )
    return {
        "token": raw_token,
        "token_record": asdict(record) | {"token_hash": ""},
        "issued_reason": issued_reason,
        "issued_at": now_iso(),
    }
    logger.info(
        "control_plane.token.issued",
        extra={
            "event": "control_plane.token.issued",
            "operator_id": operator_id,
            "token_id": record.token_id,
            "issued_reason": issued_reason,
        },
    )
    return payload


def revoke_operator_token(*, token_id: str, reason: str = "", revoked_by: str = "") -> dict:
    """Revoke an existing operator token."""

    token = revoke_token(token_id, revoked_by=revoked_by or "control-plane", reason=reason)
    payload = {
        "token_record": asdict(token) | {"token_hash": ""},
        "reason": reason,
        "revoked_at": now_iso(),
    }
    logger.info(
        "control_plane.token.revoked",
        extra={
            "event": "control_plane.token.revoked",
            "token_id": token_id,
            "revoked_by": revoked_by or "control-plane",
            "reason": reason,
        },
    )
    return payload


def rotate_operator_token(
    *,
    token_id: str,
    ttl_minutes: int = 60,
    rotated_by: str = "",
    rotation_reason: str = "",
) -> dict:
    """Rotate an existing token into a replacement."""

    raw_token, new_record, old_record = rotate_token(
        token_id,
        ttl_minutes=ttl_minutes,
        rotated_by=rotated_by or "control-plane",
        rotation_reason=rotation_reason or "rotation",
    )
    payload = {
        "token": raw_token,
        "token_record": asdict(new_record) | {"token_hash": ""},
        "replaced_token_record": asdict(old_record) | {"token_hash": ""},
        "rotation_reason": rotation_reason or "rotation",
        "rotated_at": now_iso(),
    }
    logger.info(
        "control_plane.token.rotated",
        extra={
            "event": "control_plane.token.rotated",
            "token_id": token_id,
            "replacement_token_id": new_record.token_id,
            "rotated_by": rotated_by or "control-plane",
            "rotation_reason": rotation_reason or "rotation",
        },
    )
    return payload


def cleanup_expired_tokens(*, now_ts: str = "") -> dict:
    """Deactivate expired tokens and expose the cleanup result."""

    updated = cleanup_expired_operator_tokens(now_ts=now_ts)
    payload = {
        "cleaned_tokens": [asdict(token) | {"token_hash": ""} for token in updated],
        "count": len(updated),
        "cleaned_at": now_iso(),
    }
    if updated:
        logger.info(
            "control_plane.token.cleanup",
            extra={
                "event": "control_plane.token.cleanup",
                "count": len(updated),
                "token_ids": [token.token_id for token in updated],
            },
        )
    return payload


def summarize_operator_tokens() -> dict[str, int]:
    """Return a compact operational summary for health and scheduler surfaces."""

    now_dt = datetime.now(timezone.utc)
    active_count = 0
    revoked_count = 0
    expired_active_tokens = 0
    for token in list_operator_auth_tokens():
        expires_at = _parse_iso(token.expires_at)
        if token.is_active:
            active_count += 1
            if expires_at is not None and expires_at <= now_dt:
                expired_active_tokens += 1
        else:
            revoked_count += 1
    return {
        "active_count": active_count,
        "revoked_count": revoked_count,
        "expired_active_tokens": expired_active_tokens,
    }


def list_operator_tokens(*, operator_id: str = "", is_active: bool | None = None) -> dict:
    """List operator token metadata for audit surfaces."""

    cleanup_expired_operator_tokens()
    tokens = list_operator_auth_tokens(operator_id=operator_id, is_active=is_active)
    active = []
    revoked = []
    for token in tokens:
        sanitized = asdict(token) | {"token_hash": ""}
        if token.is_active:
            active.append(sanitized)
        else:
            revoked.append(sanitized)
    return {
        "policy": credential_policy(),
        "tokens": active + revoked,
        "active_tokens": active,
        "revoked_tokens": revoked,
        "count": len(tokens),
        "generated_at": now_iso(),
    }
