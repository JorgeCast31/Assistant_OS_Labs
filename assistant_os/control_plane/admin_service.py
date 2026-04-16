"""Governed admin service layer for the operator control plane."""

from __future__ import annotations

from dataclasses import asdict
import uuid
import logging

from ..mso.contracts import ControlPlaneRequest, OperatorContext
from ..mso.operator_actions import now_iso
from ..mso.operator_actions import (
    acknowledge_restriction,
    clear_restriction,
    extend_restriction,
    get_recent_operator_actions,
    override_restriction,
)
from ..mso.operator_auth import (
    authenticate_operator_token,
    authorize_operator_context_action,
    authorize_operator_context_read,
)
from ..mso.restrictions import (
    get_active_restrictions,
    get_recent_expired_restrictions,
    get_restriction,
    get_restriction_history,
    get_restrictions_by_source_event,
    get_restrictions_by_type,
)
from ..mso.operator_identity import list_operator_identities
from ..storage.mso_store import list_control_plane_bootstrap_records
from .bootstrap import bootstrap_control_plane
from .locks import LockConflictError, lock_manager
from .maintenance import (
    force_lock_cleanup,
    force_token_cleanup,
    inspect_active_locks,
    recent_maintenance,
    recent_signals,
    run_maintenance_cycle,
)
from .token_service import (
    cleanup_expired_tokens,
    issue_operator_token,
    list_operator_tokens,
    rotate_operator_token,
    revoke_operator_token as revoke_operator_token_record,
)

logger = logging.getLogger("assistant_os.control_plane")


class RestrictionConflictError(RuntimeError):
    """Raised when a conflicting operator action is already in progress."""


def _get_lock(restriction_id: str):
    """Compatibility shim for tests and internal callers expecting direct access."""

    return lock_manager._get_lock(f"restriction:{restriction_id}")


def authenticate_request(raw_token: str) -> OperatorContext:
    """Authenticate an operator token and mint a request-scoped context."""

    return authenticate_operator_token(raw_token, request_id=f"admin-req:{uuid.uuid4()}")


def make_control_plane_request(
    context: OperatorContext,
    *,
    action: str,
    payload: dict,
) -> ControlPlaneRequest:
    """Build a typed control-plane request boundary for governed handling."""

    return ControlPlaneRequest(
        request_id=context.request_id,
        operator_context=context,
        action=action,
        payload=dict(payload),
        created_at=now_iso(),
    )


def list_restrictions(
    request: ControlPlaneRequest,
    *,
    restriction_type: str = "",
    source_event_id: str = "",
    review_state: str = "",
    status_filter: str = "active",
) -> dict:
    authorize_operator_context_read(request.operator_context)
    if source_event_id:
        restrictions = get_restrictions_by_source_event(source_event_id)
    elif restriction_type:
        restrictions = get_restrictions_by_type(restriction_type)
    elif status_filter.lower() == "expired":
        restrictions = get_recent_expired_restrictions(limit=50)
    else:
        restrictions = get_active_restrictions()
    if review_state:
        restrictions = [item for item in restrictions if item.review_state == review_state]
    return {
        "control_plane_request": asdict(request),
        "operator_context": asdict(request.operator_context),
        "restrictions": [asdict(item) for item in restrictions],
        "count": len(restrictions),
    }


def get_restriction_detail(request: ControlPlaneRequest, restriction_id: str) -> dict:
    authorize_operator_context_read(request.operator_context)
    restriction = get_restriction(restriction_id)
    if restriction is None:
        raise ValueError(f"Restriction {restriction_id!r} not found")
    return {
        "control_plane_request": asdict(request),
        "operator_context": asdict(request.operator_context),
        "restriction": asdict(restriction),
    }


def get_restriction_history_view(request: ControlPlaneRequest, restriction_id: str) -> dict:
    authorize_operator_context_read(request.operator_context)
    history = get_restriction_history(restriction_id)
    if history.get("restriction") is None:
        raise ValueError(f"Restriction {restriction_id!r} not found")
    return {
        "control_plane_request": asdict(request),
        "operator_context": asdict(request.operator_context),
        "history": history,
    }


def list_operator_actions_view(
    request: ControlPlaneRequest,
    *,
    filter_operator_id: str = "",
    restriction_id: str = "",
    action_type: str = "",
) -> dict:
    authorize_operator_context_read(request.operator_context)
    actions = get_recent_operator_actions(
        limit=50,
        operator_id=filter_operator_id,
        restriction_id=restriction_id,
        action_type=action_type,
    )
    return {
        "control_plane_request": asdict(request),
        "operator_context": asdict(request.operator_context),
        "operator_actions": [item.get("payload", item) for item in actions],
        "count": len(actions),
    }


def perform_restriction_action(
    request: ControlPlaneRequest,
    *,
    restriction_id: str,
    action_name: str,
    reason: str,
    trace_id: str = "",
    expires_at: str = "",
    override_mode: str = "allow",
) -> dict:
    authorize_operator_context_action(request.operator_context, f"{action_name}_restriction")
    if not reason.strip():
        raise ValueError("reason is required")

    try:
        with lock_manager.hold(
            f"restriction:{restriction_id}",
            owner_id=request.request_id,
            timeout_seconds=0.0,
        ):
            if action_name == "acknowledge":
                action = acknowledge_restriction(
                    operator_id=request.operator_context.operator_id,
                    restriction_id=restriction_id,
                    reason=reason,
                    trace_id=trace_id,
                    operator_context=request.operator_context,
                )
            elif action_name == "clear":
                action = clear_restriction(
                    operator_id=request.operator_context.operator_id,
                    restriction_id=restriction_id,
                    reason=reason,
                    trace_id=trace_id,
                    operator_context=request.operator_context,
                )
            elif action_name == "extend":
                action = extend_restriction(
                    operator_id=request.operator_context.operator_id,
                    restriction_id=restriction_id,
                    reason=reason,
                    expires_at=expires_at,
                    trace_id=trace_id,
                    operator_context=request.operator_context,
                )
            elif action_name == "override":
                action = override_restriction(
                    operator_id=request.operator_context.operator_id,
                    restriction_id=restriction_id,
                    reason=reason,
                    override_mode=override_mode,
                    expires_at=expires_at,
                    trace_id=trace_id,
                    operator_context=request.operator_context,
                )
            else:
                raise ValueError(f"Unsupported admin action: {action_name}")
            restriction = get_restriction(restriction_id)
            return {
                "control_plane_request": asdict(request),
                "operator_context": asdict(request.operator_context),
                "action": asdict(action),
                "restriction": asdict(restriction) if restriction else None,
            }
    except LockConflictError as exc:
        logger.warning(
            "control_plane.lock.conflict",
            extra={
                "event": "control_plane.lock.conflict",
                "restriction_id": restriction_id,
                "request_id": request.request_id,
                "action_name": action_name,
            },
        )
        raise RestrictionConflictError(str(exc)) from exc


def mint_operator_token(
    *,
    operator_id: str,
    ttl_minutes: int = 60,
) -> dict:
    return issue_operator_token(
        operator_id=operator_id,
        ttl_minutes=ttl_minutes,
        issued_reason=f"control-plane-issue:{operator_id}",
    )


def revoke_operator_token(*, token_id: str, reason: str = "", revoked_by: str = "") -> dict:
    return revoke_operator_token_record(
        token_id=token_id,
        reason=reason or "control-plane-revoke",
        revoked_by=revoked_by or "control-plane",
    )


def list_operator_tokens_view(*, operator_id: str = "", is_active: bool | None = None) -> dict:
    return list_operator_tokens(operator_id=operator_id, is_active=is_active)


def rotate_operator_token_view(
    *,
    token_id: str,
    ttl_minutes: int = 60,
    rotated_by: str = "",
    rotation_reason: str = "",
) -> dict:
    return rotate_operator_token(
        token_id=token_id,
        ttl_minutes=ttl_minutes,
        rotated_by=rotated_by,
        rotation_reason=rotation_reason,
    )


def cleanup_expired_tokens_view(*, now_ts: str = "") -> dict:
    return cleanup_expired_tokens(now_ts=now_ts)


def list_operator_identities_view() -> dict:
    operators = [asdict(item) for item in list_operator_identities()]
    return {
        "operators": operators,
        "count": len(operators),
    }


def bootstrap_control_plane_view(
    *,
    operator_id: str = "ops-admin",
    ttl_minutes: int,
    reason: str,
) -> dict:
    return bootstrap_control_plane(operator_id=operator_id, ttl_minutes=ttl_minutes, reason=reason)


def list_bootstrap_history_view() -> dict:
    records = list_control_plane_bootstrap_records(limit=20)
    return {
        "bootstrap_history": [item.get("payload", {}) for item in records],
        "count": len(records),
    }


def get_maintenance_status_view() -> dict:
    return {
        "recent_maintenance": recent_maintenance(limit=10),
        "recent_signals": recent_signals(limit=10),
        "locks": {
            "active_count": len(lock_manager.active_locks()),
            "active": lock_manager.active_locks(),
        },
    }


def run_maintenance_cycle_view(
    *,
    operator_context: OperatorContext | None = None,
    trace_id: str = "",
    now_ts: str = "",
) -> dict:
    return run_maintenance_cycle(
        trigger="operator" if operator_context else "internal",
        operator_context=operator_context,
        trace_id=trace_id,
        now_ts=now_ts,
    )


def force_token_cleanup_view(
    *,
    operator_context: OperatorContext | None = None,
    trace_id: str = "",
    now_ts: str = "",
) -> dict:
    return force_token_cleanup(
        operator_context=operator_context,
        trace_id=trace_id,
        now_ts=now_ts,
    )


def inspect_active_locks_view(
    *,
    operator_context: OperatorContext | None = None,
    trace_id: str = "",
) -> dict:
    return inspect_active_locks(operator_context=operator_context, trace_id=trace_id)


def force_lock_cleanup_view(
    *,
    operator_context: OperatorContext | None = None,
    trace_id: str = "",
) -> dict:
    return force_lock_cleanup(operator_context=operator_context, trace_id=trace_id)
