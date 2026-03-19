"""
ExecutionRegistry — in-memory, thread-safe store for ExecutionRun objects.

Responsibilities
----------------
- Register a new ExecutionRun (on execution start).
- Look up any run by execution_id.
- Apply status transitions (under lock, validated).
- List all runs for observability.

Thread safety
-------------
All mutations and reads are protected by a single threading.Lock.
The lock is held only for the duration of the critical section — no
blocking I/O or heavy computation happens under the lock.

MVP constraints
---------------
- Pure in-memory store (no persistence, no DB).
- No eviction policy: runs accumulate until the process restarts.
  (Eviction is deferred to the next implementation cycle.)
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from .execution_run import (
    ExecutionRun,
    ExecutionStatus,
    TerminationReason,
    TERMINAL_STATUSES,
)


class RegistryError(Exception):
    """Base error for ExecutionRegistry violations."""


class ExecutionNotFound(RegistryError):
    """Raised when an execution_id is not in the registry."""


class InvalidTransition(RegistryError):
    """Raised when a status transition is not allowed."""


class ExecutionRegistry:
    """
    Thread-safe in-memory store for ExecutionRun objects.

    Usage
    -----
        registry = ExecutionRegistry()
        registry.register(run)
        registry.mark_running(run.execution_id, container_id="assistantos-runner-xyz")
        registry.mark_completed(run.execution_id)
    """

    def __init__(self) -> None:
        self._runs: dict[str, ExecutionRun] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, run: ExecutionRun) -> None:
        """
        Register a new ExecutionRun.

        Raises RegistryError if execution_id already exists.
        """
        with self._lock:
            if run.execution_id in self._runs:
                raise RegistryError(
                    f"Execution {run.execution_id!r} is already registered"
                )
            self._runs[run.execution_id] = run

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, execution_id: str) -> Optional[ExecutionRun]:
        """Return the ExecutionRun for execution_id, or None if not found."""
        with self._lock:
            return self._runs.get(execution_id)

    def require(self, execution_id: str) -> ExecutionRun:
        """Return the ExecutionRun, raising ExecutionNotFound if absent."""
        run = self.get(execution_id)
        if run is None:
            raise ExecutionNotFound(
                f"Execution {execution_id!r} not found in registry"
            )
        return run

    def all_runs(self) -> list[ExecutionRun]:
        """Return a snapshot list of all registered runs."""
        with self._lock:
            return list(self._runs.values())

    def count(self) -> int:
        """Return the total number of registered runs."""
        with self._lock:
            return len(self._runs)

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def mark_running(
        self,
        execution_id: str,
        container_id: Optional[str] = None,
        started_at: Optional[float] = None,
    ) -> None:
        """Transition PENDING → RUNNING."""
        self._transition(
            execution_id,
            from_statuses={ExecutionStatus.PENDING},
            to_status=ExecutionStatus.RUNNING,
            container_id=container_id,
            started_at=started_at or time.time(),
        )

    def mark_completed(
        self,
        execution_id: str,
        ended_at: Optional[float] = None,
    ) -> None:
        """Transition RUNNING → COMPLETED."""
        self._transition(
            execution_id,
            from_statuses={ExecutionStatus.RUNNING},
            to_status=ExecutionStatus.COMPLETED,
            termination_reason=TerminationReason.NONE,
            ended_at=ended_at or time.time(),
        )

    def mark_failed(
        self,
        execution_id: str,
        reason: TerminationReason = TerminationReason.ERROR,
        ended_at: Optional[float] = None,
    ) -> None:
        """Transition RUNNING → FAILED (or PENDING → FAILED for pre-start errors)."""
        self._transition(
            execution_id,
            from_statuses={ExecutionStatus.RUNNING, ExecutionStatus.PENDING},
            to_status=ExecutionStatus.FAILED,
            termination_reason=reason,
            ended_at=ended_at or time.time(),
        )

    def mark_aborted(
        self,
        execution_id: str,
        reason: TerminationReason = TerminationReason.REVOKED,
        ended_at: Optional[float] = None,
    ) -> None:
        """
        Transition any non-terminal state → ABORTED.

        Idempotent: already-ABORTED runs are silently left unchanged.
        """
        with self._lock:
            run = self._runs.get(execution_id)
            if run is None:
                return  # Silent — revocation may race with registration
            if run.status == ExecutionStatus.ABORTED:
                return  # Already aborted — idempotent
            if run.status in TERMINAL_STATUSES:
                return  # Already in a terminal state — do nothing
            run.status = ExecutionStatus.ABORTED
            run.termination_reason = reason
            run.ended_at = ended_at or time.time()

    def update_status(
        self,
        execution_id: str,
        status: ExecutionStatus,
        termination_reason: TerminationReason = TerminationReason.NONE,
        ended_at: Optional[float] = None,
        container_id: Optional[str] = None,
    ) -> None:
        """
        General-purpose status update (used by RunnerAPI).

        Does not enforce from_statuses — use specific mark_* methods when
        the transition is known.  This method is for RunnerAPI's finally block
        where the previous state might vary.
        """
        with self._lock:
            run = self._runs.get(execution_id)
            if run is None:
                return  # Silent — run may not have been registered (no plan)
            run.status = status
            run.termination_reason = termination_reason
            if ended_at is not None:
                run.ended_at = ended_at
            if container_id is not None:
                run.container_id = container_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition(
        self,
        execution_id: str,
        from_statuses: set[ExecutionStatus],
        to_status: ExecutionStatus,
        termination_reason: TerminationReason = TerminationReason.NONE,
        started_at: Optional[float] = None,
        ended_at: Optional[float] = None,
        container_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            run = self._runs.get(execution_id)
            if run is None:
                raise ExecutionNotFound(
                    f"Execution {execution_id!r} not found in registry"
                )
            if run.status not in from_statuses:
                raise InvalidTransition(
                    f"Cannot transition {run.execution_id!r} from "
                    f"{run.status.value!r} to {to_status.value!r} "
                    f"(allowed from: {[s.value for s in from_statuses]})"
                )
            run.status = to_status
            run.termination_reason = termination_reason
            if started_at is not None:
                run.started_at = started_at
            if ended_at is not None:
                run.ended_at = ended_at
            if container_id is not None:
                run.container_id = container_id
