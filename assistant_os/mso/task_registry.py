"""Internal MSO task registry.

Observes task lifecycle transitions without owning execution.
"""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from threading import RLock
from typing import Optional
import uuid

from ..contracts import now_iso
from .contracts import TaskRecord, TaskStatus, TaskTransition

_lock = RLock()
_tasks: dict[str, TaskRecord] = {}
_recent_transitions: deque[TaskTransition] = deque(maxlen=200)


def register_task(record: TaskRecord) -> TaskRecord:
    """Register or replace a task record and emit an initial transition if needed."""
    with _lock:
        existing = _tasks.get(record.task_id)
        _tasks[record.task_id] = record
        if existing is None:
            _recent_transitions.append(
                TaskTransition(
                    transition_id=str(uuid.uuid4()),
                    task_id=record.task_id,
                    at=record.created_at or now_iso(),
                    from_status="",
                    to_status=record.status,
                    domain=record.domain,
                    action=record.last_known_action,
                    reason="registered",
                    trace_id=record.trace_id,
                    plan_id=record.plan_id,
                )
            )
        return record


def transition_task(
    task_id: str,
    *,
    to_status: TaskStatus,
    reason: str = "",
    result_type: str = "",
    error_type: str = "",
    error_message: str = "",
    execution_id: str = "",
) -> Optional[TaskRecord]:
    """Transition an existing task to a new status."""
    with _lock:
        current = _tasks.get(task_id)
        if current is None:
            return None
        timestamp = now_iso()
        updated = replace(
            current,
            status=to_status,
            updated_at=timestamp,
            completed_at=timestamp if to_status in {"completed", "failed", "blocked"} else current.completed_at,
            result_type=result_type or current.result_type,
            error_type=error_type or current.error_type,
            error_message=error_message or current.error_message,
            execution_id=execution_id or current.execution_id,
        )
        if to_status == "active" and not updated.started_at:
            updated = replace(updated, started_at=timestamp)
        _tasks[task_id] = updated
        _recent_transitions.append(
            TaskTransition(
                transition_id=str(uuid.uuid4()),
                task_id=task_id,
                at=timestamp,
                from_status=current.status,
                to_status=to_status,
                domain=updated.domain,
                action=updated.last_known_action,
                reason=reason,
                trace_id=updated.trace_id,
                plan_id=updated.plan_id,
            )
        )
        return updated


def get_task(task_id: str) -> Optional[TaskRecord]:
    with _lock:
        return _tasks.get(task_id)


def list_tasks(*, status: TaskStatus | None = None) -> list[TaskRecord]:
    with _lock:
        records = list(_tasks.values())
    if status is None:
        return sorted(records, key=lambda item: item.updated_at, reverse=True)
    return [item for item in sorted(records, key=lambda item: item.updated_at, reverse=True) if item.status == status]


def get_recent_transitions(limit: int = 20) -> list[TaskTransition]:
    with _lock:
        items = list(_recent_transitions)
    return list(reversed(items[-limit:]))


def reset_task_registry() -> None:
    with _lock:
        _tasks.clear()
        _recent_transitions.clear()
