"""Operator actions over active restrictions with explicit auth and ledgering."""

from __future__ import annotations

import uuid

from ..contracts import now_iso
from ..storage.mso_store import list_recent_operator_actions, persist_operator_action
from .capability_registry import clear_grant, clear_revocation, grant_temporary_capability
from .contracts import OperatorActionRecord, OperatorContext
from .operator_auth import authorize_operator_action
from .restrictions import get_restriction, mark_restriction_review, transition_restriction


def _validate_common(*, operator_id: str, reason: str, restriction_id: str, action_type: str):
    if not reason.strip():
        raise ValueError("reason is required")
    restriction = get_restriction(restriction_id)
    if restriction is None:
        raise ValueError(f"Unknown restriction_id: {restriction_id}")
    authorize_operator_action(operator_id, action_type)


def _record(
    *,
    operator_id: str,
    operator_role: str,
    action_type: str,
    restriction_id: str,
    reason: str,
    trace_id: str,
    result_status: str,
    operator_context: OperatorContext | None = None,
    notes: str = "",
) -> OperatorActionRecord:
    record = OperatorActionRecord(
        action_id=str(uuid.uuid4()),
        operator_id=operator_id,
        operator_role=operator_role,  # type: ignore[arg-type]
        action_type=action_type,
        target_restriction_id=restriction_id,
        reason=reason,
        timestamp=now_iso(),
        trace_id=trace_id,
        token_id=operator_context.token_id if operator_context else "",
        request_id=operator_context.request_id if operator_context else "",
        result_status=result_status,
        notes=notes,
    )
    persist_operator_action(record)
    return record


def acknowledge_restriction(
    *,
    operator_id: str,
    restriction_id: str,
    reason: str,
    trace_id: str = "",
    operator_context: OperatorContext | None = None,
) -> OperatorActionRecord:
    _validate_common(
        operator_id=operator_id,
        reason=reason,
        restriction_id=restriction_id,
        action_type="acknowledge_restriction",
    )
    restriction = get_restriction(restriction_id)
    assert restriction is not None
    operator = authorize_operator_action(operator_id, "acknowledge_restriction")
    mark_restriction_review(
        restriction_id,
        review_state="acknowledged",
        operator_id=operator.operator_id,
        reason=reason,
    )
    return _record(
        operator_id=operator.operator_id,
        operator_role=operator.role,
        action_type="acknowledge_restriction",
        restriction_id=restriction_id,
        reason=reason,
        trace_id=trace_id or restriction.trace_id,
        operator_context=operator_context,
        result_status="acknowledged",
        notes=f"Restriction remains {restriction.status}.",
    )


def clear_restriction(
    *,
    operator_id: str,
    restriction_id: str,
    reason: str,
    trace_id: str = "",
    operator_context: OperatorContext | None = None,
) -> OperatorActionRecord:
    _validate_common(
        operator_id=operator_id,
        reason=reason,
        restriction_id=restriction_id,
        action_type="clear_restriction",
    )
    restriction = get_restriction(restriction_id)
    assert restriction is not None
    operator = authorize_operator_action(operator_id, "clear_restriction")
    if restriction.status not in {"ACTIVE", "EXTENDED", "OVERRIDDEN"}:
        raise ValueError("Only ACTIVE, EXTENDED, or OVERRIDDEN restrictions can be cleared")
    if restriction.enforcement_kind == "grant" and restriction.enforcement_ref:
        clear_grant(restriction.enforcement_ref)
    elif restriction.enforcement_kind == "revocation" and restriction.enforcement_ref:
        clear_revocation(restriction.enforcement_ref)
    transition_restriction(restriction_id, status="CLEARED", reason=reason)
    mark_restriction_review(
        restriction_id,
        review_state="actioned",
        operator_id=operator.operator_id,
        reason=reason,
    )
    return _record(
        operator_id=operator.operator_id,
        operator_role=operator.role,
        action_type="clear_restriction",
        restriction_id=restriction_id,
        reason=reason,
        trace_id=trace_id or restriction.trace_id,
        operator_context=operator_context,
        result_status="cleared",
    )


def extend_restriction(
    *,
    operator_id: str,
    restriction_id: str,
    reason: str,
    expires_at: str,
    trace_id: str = "",
    operator_context: OperatorContext | None = None,
) -> OperatorActionRecord:
    _validate_common(
        operator_id=operator_id,
        reason=reason,
        restriction_id=restriction_id,
        action_type="extend_restriction",
    )
    restriction = get_restriction(restriction_id)
    assert restriction is not None
    operator = authorize_operator_action(operator_id, "extend_restriction")
    if restriction.status not in {"ACTIVE", "EXTENDED"}:
        raise ValueError("Only ACTIVE or EXTENDED restrictions can be extended")
    if not expires_at:
        raise ValueError("expires_at is required for extend_restriction")
    if restriction.enforcement_kind == "grant" and restriction.enforcement_ref:
        clear_grant(restriction.enforcement_ref)
        grant = grant_temporary_capability(
            action=restriction.scope.get("action", ""),
            domain=restriction.scope.get("domain", ""),
            mode="confirm_only",
            reason=reason,
            expires_at=expires_at,
            granted_by=f"operator:{operator.operator_id}",
        )
        restriction.enforcement_ref = grant.grant_id
    transition_restriction(restriction_id, status="EXTENDED", reason=reason, expires_at=expires_at)
    mark_restriction_review(
        restriction_id,
        review_state="actioned",
        operator_id=operator.operator_id,
        reason=reason,
    )
    return _record(
        operator_id=operator.operator_id,
        operator_role=operator.role,
        action_type="extend_restriction",
        restriction_id=restriction_id,
        reason=reason,
        trace_id=trace_id or restriction.trace_id,
        operator_context=operator_context,
        result_status="extended",
        notes=f"Extended until {expires_at}.",
    )


def override_restriction(
    *,
    operator_id: str,
    restriction_id: str,
    reason: str,
    override_mode: str = "allow",
    expires_at: str = "",
    trace_id: str = "",
    operator_context: OperatorContext | None = None,
) -> OperatorActionRecord:
    _validate_common(
        operator_id=operator_id,
        reason=reason,
        restriction_id=restriction_id,
        action_type="override_restriction",
    )
    restriction = get_restriction(restriction_id)
    assert restriction is not None
    operator = authorize_operator_action(operator_id, "override_restriction")
    if restriction.status not in {"ACTIVE", "EXTENDED"}:
        raise ValueError("Only ACTIVE or EXTENDED restrictions can be overridden")
    if not restriction.allow_override:
        raise ValueError("This restriction cannot be overridden")
    if restriction.enforcement_kind == "grant" and restriction.enforcement_ref:
        clear_grant(restriction.enforcement_ref)
    elif restriction.enforcement_kind == "revocation" and restriction.enforcement_ref:
        clear_revocation(restriction.enforcement_ref)
    if expires_at:
        grant = grant_temporary_capability(
            action=restriction.scope.get("action", ""),
            domain=restriction.scope.get("domain", ""),
            mode=override_mode,
            reason=reason,
            expires_at=expires_at,
            granted_by=f"operator:{operator.operator_id}",
        )
        restriction.enforcement_kind = "grant"
        restriction.enforcement_ref = grant.grant_id
    transition_restriction(restriction_id, status="OVERRIDDEN", reason=reason, expires_at=expires_at or restriction.expires_at)
    mark_restriction_review(
        restriction_id,
        review_state="actioned",
        operator_id=operator.operator_id,
        reason=reason,
    )
    return _record(
        operator_id=operator.operator_id,
        operator_role=operator.role,
        action_type="override_restriction",
        restriction_id=restriction_id,
        reason=reason,
        trace_id=trace_id or restriction.trace_id,
        operator_context=operator_context,
        result_status="overridden",
        notes=f"Override mode={override_mode}.",
    )


def get_recent_operator_actions(
    *,
    limit: int = 20,
    operator_id: str = "",
    restriction_id: str = "",
    action_type: str = "",
) -> list[dict]:
    """Query recent operator actions with practical filters."""

    return list_recent_operator_actions(
        limit=limit,
        operator_id=operator_id,
        restriction_id=restriction_id,
        action_type=action_type,
    )
