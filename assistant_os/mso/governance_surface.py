"""Minimal internal governance read model for dynamic MSO presence."""

from __future__ import annotations

from ..contracts import now_iso
from ..contracts import ACTION_BASIC_COGNITIVE_EXECUTION
from .capability_registry import check_capability, list_active_revocations, list_temporary_grants
from .contracts import GovernanceSummary, OperationalMode
from ..storage.mso_store import list_recent_security_responses, list_recent_worker_security_events
from .operator_actions import get_recent_operator_actions as query_operator_actions
from .restrictions import (
    get_active_restrictions,
    get_recent_expired_restrictions,
    get_restriction_history,
    get_restrictions_by_source_event,
    get_restrictions_by_type,
)
from .system_state import (
    build_system_state_snapshot,
    clear_operational_mode_override,
    get_operational_mode_override,
    set_operational_mode,
)
from .task_registry import list_tasks
from .trace_aggregator import get_recent_governance_decisions, get_trace_chain


def get_active_tasks():
    return list_tasks(status="active")


def get_pending_tasks():
    return list_tasks(status="pending")


def get_recent_failures(limit: int = 10):
    return list_tasks(status="failed")[:limit]


def get_trace_view(task_or_plan_id: str):
    return get_trace_chain(task_or_plan_id)


def get_system_state():
    return build_system_state_snapshot()


def get_recent_governance(limit: int = 10):
    return get_recent_governance_decisions(limit=limit)


def get_operational_mode() -> tuple[OperationalMode, str, str]:
    snapshot = build_system_state_snapshot()
    return snapshot.operational_mode, snapshot.operational_mode_reason, snapshot.operational_mode_source


def set_operational_mode_override(mode: OperationalMode, *, reason: str = "") -> None:
    set_operational_mode(mode, reason=reason)


def clear_operational_mode() -> None:
    clear_operational_mode_override()


def get_active_revocations():
    return list_active_revocations()


def get_temporary_grants():
    return list_temporary_grants()


def get_recent_anomaly_signals(limit: int = 10):
    return build_system_state_snapshot(decision_limit=limit).recent_anomaly_signals[:limit]


def get_recent_worker_security_events(limit: int = 10):
    return list_recent_worker_security_events(limit=limit)


def get_recent_security_responses(limit: int = 10):
    return list_recent_security_responses(limit=limit)


def get_recent_operator_actions(
    limit: int = 10,
    *,
    operator_id: str = "",
    restriction_id: str = "",
    action_type: str = "",
):
    return query_operator_actions(
        limit=limit,
        operator_id=operator_id,
        restriction_id=restriction_id,
        action_type=action_type,
    )


def get_active_restrictions_view():
    return get_active_restrictions()


def get_recent_expired_restrictions_view(limit: int = 10):
    return get_recent_expired_restrictions(limit=limit)


def get_restrictions_by_type_view(restriction_type: str):
    return get_restrictions_by_type(restriction_type)


def get_restrictions_by_source_event_view(source_event_id: str):
    return get_restrictions_by_source_event(source_event_id)


def get_restriction_history_view(restriction_id: str):
    return get_restriction_history(restriction_id)


def get_cognitive_restriction_level() -> dict:
    capability = check_capability(ACTION_BASIC_COGNITIVE_EXECUTION, "COGNITIVE")
    return {
        "allowed": capability.allowed,
        "mode": capability.mode,
        "source": capability.source,
        "expires_at": capability.expires_at,
        "notes": capability.notes,
    }


def get_hardened_domains() -> list[str]:
    snapshot = build_system_state_snapshot()
    return [item.domain for item in snapshot.domain_operational_states if item.hardened]


def get_governance_summary() -> GovernanceSummary:
    snapshot = build_system_state_snapshot()
    recent_failures = list_tasks(status="failed")[:10]
    if snapshot.active_tasks:
        current_state = "active"
    elif snapshot.pending_tasks:
        current_state = "pending"
    elif snapshot.blocked_tasks:
        current_state = "blocked"
    else:
        current_state = "idle"
    return GovernanceSummary(
        generated_at=now_iso(),
        active_count=len(snapshot.active_tasks),
        pending_count=len(snapshot.pending_tasks),
        blocked_count=len(snapshot.blocked_tasks),
        failed_recent_count=len(recent_failures),
        active_task_ids=[task.task_id for task in snapshot.active_tasks],
        pending_task_ids=[task.task_id for task in snapshot.pending_tasks],
        recent_failure_task_ids=[task.task_id for task in recent_failures],
        current_state=current_state,
        operational_mode=snapshot.operational_mode,
        active_revocation_count=len(snapshot.active_capability_revocations),
        active_grant_count=len(snapshot.active_capability_grants),
        recent_anomaly_count=len(snapshot.recent_anomaly_signals),
        hardened_domains=[item.domain for item in snapshot.domain_operational_states if item.hardened],
    )
