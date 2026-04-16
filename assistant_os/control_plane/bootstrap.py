"""Formal bootstrap flow for initial control-plane operator setup."""

from __future__ import annotations

from dataclasses import asdict
import uuid
import logging

from ..config import CONTROL_PLANE_TOKEN_DEFAULT_TTL_MINUTES
from ..contracts import now_iso
from ..mso.contracts import ControlPlaneBootstrapRecord
from ..mso.operator_identity import (
    get_operator_identity,
    list_operator_auth_tokens,
    list_operator_identities,
    set_operator_active,
)
from ..storage.mso_store import list_control_plane_bootstrap_records, persist_control_plane_bootstrap
from .token_service import issue_operator_token

logger = logging.getLogger("assistant_os.control_plane")


class BootstrapError(RuntimeError):
    """Raised when bootstrap is invalid or unsafe to repeat."""


def bootstrap_control_plane(
    *,
    operator_id: str = "ops-admin",
    ttl_minutes: int = CONTROL_PLANE_TOKEN_DEFAULT_TTL_MINUTES,
    reason: str = "initial_control_plane_bootstrap",
) -> dict:
    """Perform a guarded one-time bootstrap for the initial admin operator."""

    if list_control_plane_bootstrap_records(limit=1):
        raise BootstrapError("Control plane bootstrap has already been completed")
    if any(identity.role == "admin" and identity.is_active for identity in list_operator_identities()):
        active_admin_tokens = list_operator_auth_tokens(operator_id=operator_id, is_active=True)
        if active_admin_tokens:
            raise BootstrapError("Active admin credentials already exist; refusing repeated bootstrap")
    identity = get_operator_identity(operator_id)
    if identity is None:
        raise BootstrapError(f"Unknown bootstrap operator_id: {operator_id}")
    if identity.role != "admin":
        raise BootstrapError("Bootstrap operator must have admin role")
    if not identity.is_active:
        set_operator_active(operator_id, is_active=True)

    issued = issue_operator_token(
        operator_id=operator_id,
        ttl_minutes=ttl_minutes,
        issued_reason=reason,
    )
    record = ControlPlaneBootstrapRecord(
        bootstrap_id=str(uuid.uuid4()),
        operator_id=operator_id,
        role="admin",
        token_id=issued["token_record"]["token_id"],
        created_at=now_iso(),
        expires_at=issued["token_record"]["expires_at"],
        reason=reason,
        request_id=f"bootstrap:{uuid.uuid4()}",
    )
    persist_control_plane_bootstrap(record)
    logger.info(
        "control_plane.bootstrap.completed",
        extra={
            "event": "control_plane.bootstrap.completed",
            "operator_id": operator_id,
            "token_id": issued["token_record"]["token_id"],
            "reason": reason,
        },
    )
    return {
        "bootstrap_record": asdict(record),
        "operator": asdict(get_operator_identity(operator_id)),
        "token": issued["token"],
        "token_record": issued["token_record"],
    }
