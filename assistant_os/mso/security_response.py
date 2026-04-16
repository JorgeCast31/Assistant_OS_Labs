"""Threshold-based responses to worker security events."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import uuid

from ..contracts import ACTION_BASIC_COGNITIVE_EXECUTION, now_iso
from ..storage.mso_store import list_recent_security_responses, persist_security_response, query_records
from .capability_registry import grant_temporary_capability, revoke_capability
from .contracts import SecurityResponseRecord, WorkerSecurityEvent
from .restrictions import create_restriction_from_response

_WINDOW_SECONDS = 600
_THRESHOLDS = {
    "worker_timeout": 2,
    "worker_crash": 2,
    "network_denied": 1,
    "invalid_input_ref": 2,
    "scope_violation": 2,
    "resource_limit_exceeded": 3,
}


def _window_start_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=_WINDOW_SECONDS)).isoformat()


def _count_within_window(event_type: str) -> int:
    recent = query_records(kind="worker_security_events", since=_window_start_iso(), limit=200)
    return sum(1 for item in recent if item.get("payload", {}).get("event_type") == event_type)


def _recent_response_exists(event_type: str, action: str) -> bool:
    recent = list_recent_security_responses(limit=50)
    window_start = _window_start_iso()
    return any(
        item.get("payload", {}).get("event_type") == event_type
        and item.get("payload", {}).get("action") == action
        and item.get("_meta", {}).get("stored_at", "") >= window_start
        for item in recent
    )


def _make_response(event_type: str, action: str, detail: str, *, count_within_window: int, expires_at: str = "") -> SecurityResponseRecord:
    return SecurityResponseRecord(
        response_id=str(uuid.uuid4()),
        source="mso_security_response",
        event_type=event_type,
        action=action,
        detail=detail,
        created_at=now_iso(),
        count_within_window=count_within_window,
        window_seconds=_WINDOW_SECONDS,
        target_domain="COGNITIVE",
        target_action=ACTION_BASIC_COGNITIVE_EXECUTION,
        expires_at=expires_at,
    )


def enrich_event_window_counts(events: list[WorkerSecurityEvent]) -> list[WorkerSecurityEvent]:
    """Fill count-within-window for new events before persistence."""
    local_counts: dict[str, int] = {}
    for event in events:
        base = _count_within_window(event.event_type)
        local_counts[event.event_type] = local_counts.get(event.event_type, 0) + 1
        event.count_within_window = base + local_counts[event.event_type]
    return events


def apply_security_responses(events: list[WorkerSecurityEvent]) -> list[SecurityResponseRecord]:
    """Trigger bounded governance responses from repeated worker security events."""
    responses: list[SecurityResponseRecord] = []
    now_dt = datetime.now(timezone.utc)
    for event in events:
        threshold = _THRESHOLDS.get(event.event_type)
        if threshold is None or event.count_within_window < threshold:
            continue

        if event.event_type in {"worker_timeout", "resource_limit_exceeded", "invalid_input_ref", "scope_violation"}:
            if _recent_response_exists(event.event_type, "require_confirmation"):
                continue
            expires_at = (now_dt + timedelta(minutes=10)).isoformat()
            grant = grant_temporary_capability(
                action=ACTION_BASIC_COGNITIVE_EXECUTION,
                domain="COGNITIVE",
                mode="confirm_only",
                reason=f"Security response triggered by {event.event_type}.",
                expires_at=expires_at,
                granted_by="mso_security_response",
            )
            response = _make_response(
                event.event_type,
                "require_confirmation",
                f"Worker cognitive execution now requires confirmation after {event.count_within_window} {event.event_type} event(s).",
                count_within_window=event.count_within_window,
                expires_at=expires_at,
            )
            restriction = create_restriction_from_response(
                response,
                source_events=[event],
                enforcement_kind="grant",
                enforcement_ref=grant.grant_id,
            )
            response.restriction_id = restriction.restriction_id
        elif event.event_type in {"worker_crash", "network_denied"}:
            if _recent_response_exists(event.event_type, "revoke_capability"):
                continue
            expires_at = (now_dt + timedelta(minutes=15)).isoformat()
            revocation = revoke_capability(
                action=ACTION_BASIC_COGNITIVE_EXECUTION,
                domain="COGNITIVE",
                reason=f"Security response triggered by {event.event_type}.",
                revoked_by="mso_security_response",
                expires_at=expires_at,
            )
            response = _make_response(
                event.event_type,
                "revoke_capability",
                f"Cognitive execution temporarily revoked after {event.count_within_window} {event.event_type} event(s).",
                count_within_window=event.count_within_window,
                expires_at=expires_at,
            )
            restriction = create_restriction_from_response(
                response,
                source_events=[event],
                enforcement_kind="revocation",
                enforcement_ref=revocation.revocation_id,
            )
            response.restriction_id = restriction.restriction_id
        else:
            continue

        event.response_triggered = True
        persist_security_response(response)
        responses.append(response)
    return responses
