"""
ExecutionRun — runtime entity tracking a single sandbox execution.

Every execution passing through RunnerAPI is represented as an ExecutionRun.
The model captures identity, lifecycle state, container handle, and outcome.

Status machine
--------------
    PENDING  → RUNNING  → COMPLETED
                       ↘ FAILED
                       ↘ ABORTED   (via RevocationManager)

Terminal states: COMPLETED, FAILED, ABORTED.

Immutable fields are set at creation time.
Mutable fields (status, ended_at, termination_reason, container_id) are
updated by ExecutionRegistry under its lock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExecutionStatus(str, Enum):
    """Lifecycle states for an ExecutionRun."""
    PENDING   = "pending"    # registered; execution not yet started
    RUNNING   = "running"    # execution is active inside the container
    COMPLETED = "completed"  # execution finished successfully (exit 0)
    FAILED    = "failed"     # execution failed (non-zero, timeout, error)
    ABORTED   = "aborted"    # execution was revoked or force-terminated


class TerminationReason(str, Enum):
    """Why an execution ended."""
    NONE           = "none"           # normal completion
    TIMEOUT        = "timeout"        # killed by timeout enforcement
    ERROR          = "error"          # sandbox code failed (non-zero exit / runtime error)
    REVOKED        = "revoked"        # terminated by RevocationManager
    MANUAL         = "manual"         # manual abort requested
    INTERNAL_ERROR = "internal_error" # infrastructure failure (backend exception, etc.)


# Terminal states — no further transitions allowed.
TERMINAL_STATUSES: frozenset[ExecutionStatus] = frozenset({
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.ABORTED,
})


@dataclass
class ExecutionRun:
    """
    First-class runtime entity for one execution.

    Immutable fields (set at creation, never changed)
    -------------------------------------------------
    execution_id        : unique ID (from AuthorizedPlan or generated)
    plan_id             : authorizing plan ID
    authorized_plan_hash: hash of the plan at authorization time
    policy_id           : policy that governs the execution
    runtime_profile     : e.g. "python3.11"

    Mutable fields (updated by ExecutionRegistry)
    -----------------------------------------------
    status              : current lifecycle state
    started_at          : wall-clock timestamp when execution began (seconds)
    ended_at            : wall-clock timestamp when execution ended (seconds)
    termination_reason  : why the execution ended
    container_id        : Docker container name/ID, if available
    resource_summary    : optional dict of resource usage metrics
    """

    execution_id: str
    plan_id: str
    authorized_plan_hash: str
    policy_id: str
    runtime_profile: str = "python3.11"
    delegated_seat_ref: str = ""

    # Mutable lifecycle fields
    status: ExecutionStatus = ExecutionStatus.PENDING
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    termination_reason: TerminationReason = TerminationReason.NONE
    container_id: Optional[str] = None
    resource_summary: Optional[dict] = field(default=None, repr=False)

    def duration_ms(self) -> Optional[int]:
        """Return wall-clock duration in milliseconds, or None if not finished."""
        if self.started_at is not None and self.ended_at is not None:
            return int((self.ended_at - self.started_at) * 1000)
        return None

    def is_terminal(self) -> bool:
        """True if execution has reached a terminal state."""
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict:
        """Safe for audit logs and API responses.  No secret values."""
        return {
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "authorized_plan_hash": self.authorized_plan_hash,
            "policy_id": self.policy_id,
            "runtime_profile": self.runtime_profile,
            "delegated_seat_ref": self.delegated_seat_ref,
            "status": self.status.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms(),
            "termination_reason": self.termination_reason.value,
            "container_id": self.container_id,
            "resource_summary": self.resource_summary,
        }
