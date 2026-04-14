"""Minimal internal governance read model for MSO presence."""

from __future__ import annotations

from ..contracts import now_iso
from .contracts import GovernanceSummary
from .system_state import build_system_state_snapshot
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
    )
