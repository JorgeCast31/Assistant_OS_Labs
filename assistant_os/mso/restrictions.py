"""Restriction lifecycle management for operator-visible control plane."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import uuid

from ..contracts import ACTION_BASIC_COGNITIVE_EXECUTION, now_iso
from ..storage.mso_store import persist_restriction, query_records
from .contracts import ActiveRestriction, SecurityResponseRecord, WorkerSecurityEvent


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _restriction_type_for_response(response: SecurityResponseRecord) -> str:
    if response.action == "revoke_capability":
        return "REVOKE_CAPABILITY"
    return "REQUIRE_CONFIRMATION"


def create_restriction_from_response(
    response: SecurityResponseRecord,
    *,
    source_events: list[WorkerSecurityEvent],
    enforcement_kind: str,
    enforcement_ref: str,
) -> ActiveRestriction:
    restriction = ActiveRestriction(
        restriction_id=str(uuid.uuid4()),
        type=_restriction_type_for_response(response),
        target=response.target_action or ACTION_BASIC_COGNITIVE_EXECUTION,
        scope={
            "domain": response.target_domain,
            "action": response.target_action or ACTION_BASIC_COGNITIVE_EXECUTION,
            "response_action": response.action,
        },
        source_events=[event.event_id for event in source_events],
        created_at=response.created_at,
        expires_at=response.expires_at,
        status="ACTIVE",
        reason=response.detail,
        trace_id=(source_events[0].trace_id if source_events else ""),
        response_id=response.response_id,
        enforcement_kind=enforcement_kind,
        enforcement_ref=enforcement_ref,
        last_transition_at=response.created_at,
        last_transition_reason="created_from_security_response",
        review_state="unreviewed",
    )
    persist_restriction(restriction)
    return restriction


def _load_restriction(restriction_id: str) -> ActiveRestriction | None:
    records = query_records(kind="restrictions", limit=200)
    for item in records:
        payload = item.get("payload", {})
        if payload.get("restriction_id") == restriction_id:
            return ActiveRestriction(**payload)
    return None


def _save_transition(restriction: ActiveRestriction, *, status: str, reason: str, expires_at: str | None = None) -> ActiveRestriction:
    restriction.status = status  # type: ignore[assignment]
    restriction.last_transition_at = now_iso()
    restriction.last_transition_reason = reason
    if expires_at is not None:
        restriction.expires_at = expires_at
    persist_restriction(restriction)
    return restriction


def _save_review_state(
    restriction: ActiveRestriction,
    *,
    review_state: str,
    operator_id: str,
    reason: str,
) -> ActiveRestriction:
    restriction.review_state = review_state  # type: ignore[assignment]
    if review_state == "acknowledged":
        restriction.reviewed_at = now_iso()
        restriction.reviewed_by = operator_id
    elif review_state == "actioned":
        restriction.actioned_at = now_iso()
        restriction.actioned_by = operator_id
    restriction.last_transition_at = now_iso()
    restriction.last_transition_reason = reason
    persist_restriction(restriction)
    return restriction


def expire_restrictions(*, now_ts: str = "") -> list[ActiveRestriction]:
    current = _parse_iso(now_ts) or datetime.now(timezone.utc)
    updated: list[ActiveRestriction] = []
    for item in query_records(kind="restrictions", limit=500):
        restriction = ActiveRestriction(**item.get("payload", {}))
        if restriction.status not in {"ACTIVE", "EXTENDED"}:
            continue
        expires_at = _parse_iso(restriction.expires_at)
        if expires_at is None or expires_at > current:
            continue
        updated.append(_save_transition(restriction, status="EXPIRED", reason="automatic_expiry"))
    return updated


def get_active_restrictions() -> list[ActiveRestriction]:
    expire_restrictions()
    items = [ActiveRestriction(**item.get("payload", {})) for item in query_records(kind="restrictions", limit=500)]
    return sorted([item for item in items if item.status in {"ACTIVE", "EXTENDED"}], key=lambda item: item.created_at, reverse=True)


def get_recent_expired_restrictions(limit: int = 10) -> list[ActiveRestriction]:
    expire_restrictions()
    items = [ActiveRestriction(**item.get("payload", {})) for item in query_records(kind="restrictions", limit=500)]
    expired = [item for item in items if item.status == "EXPIRED"]
    return sorted(expired, key=lambda item: item.last_transition_at or item.created_at, reverse=True)[:limit]


def get_restrictions_by_type(restriction_type: str) -> list[ActiveRestriction]:
    expire_restrictions()
    items = [ActiveRestriction(**item.get("payload", {})) for item in query_records(kind="restrictions", limit=500)]
    return [item for item in items if item.type == restriction_type]


def get_restrictions_by_source_event(source_event_id: str) -> list[ActiveRestriction]:
    expire_restrictions()
    items = [ActiveRestriction(**item.get("payload", {})) for item in query_records(kind="restrictions", limit=500)]
    return [item for item in items if source_event_id in item.source_events]


def get_restriction(restriction_id: str) -> ActiveRestriction | None:
    expire_restrictions()
    return _load_restriction(restriction_id)


def get_restriction_history(restriction_id: str) -> dict:
    restriction = get_restriction(restriction_id)
    response_id = restriction.response_id if restriction else ""
    source_event_ids = set(restriction.source_events if restriction else [])
    actions = [
        item.get("payload", {})
        for item in query_records(kind="operator_actions", limit=200)
        if item.get("payload", {}).get("target_restriction_id") == restriction_id
    ]
    security_response = next(
        (
            item.get("payload", {})
            for item in query_records(kind="security_responses", limit=200)
            if item.get("payload", {}).get("response_id") == response_id
        ),
        None,
    )
    source_events = [
        item.get("payload", {})
        for item in query_records(kind="worker_security_events", limit=500)
        if item.get("payload", {}).get("event_id") in source_event_ids
    ]
    return {
        "restriction": asdict(restriction) if restriction else None,
        "security_response": security_response,
        "source_events": sorted(source_events, key=lambda item: item.get("created_at", ""), reverse=True),
        "operator_actions": sorted(actions, key=lambda item: item.get("timestamp", ""), reverse=True),
    }


def transition_restriction(
    restriction_id: str,
    *,
    status: str,
    reason: str,
    expires_at: str | None = None,
) -> ActiveRestriction:
    restriction = _load_restriction(restriction_id)
    if restriction is None:
        raise ValueError(f"Unknown restriction_id: {restriction_id}")
    return _save_transition(restriction, status=status, reason=reason, expires_at=expires_at)


def mark_restriction_review(
    restriction_id: str,
    *,
    review_state: str,
    operator_id: str,
    reason: str,
) -> ActiveRestriction:
    restriction = _load_restriction(restriction_id)
    if restriction is None:
        raise ValueError(f"Unknown restriction_id: {restriction_id}")
    return _save_review_state(
        restriction,
        review_state=review_state,
        operator_id=operator_id,
        reason=reason,
    )
