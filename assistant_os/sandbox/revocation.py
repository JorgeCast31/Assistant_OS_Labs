"""
RevocationManager — real-time revocation and abort control for sandbox executions.

Responsibilities
----------------
- Accept revocation requests for any execution_id (before, during, or after run).
- Signal the active execution's abort_signal (threading.Event) immediately.
- Update the ExecutionRegistry to reflect the revoked state.
- Emit a RevocationEvent to the AuditLog.

Revocation is idempotent: revoking an already-revoked execution is a no-op.

Race handling
-------------
Two races are handled correctly:

    Race A — revoke BEFORE registration:
        revoke_execution(id)          → adds id to _revoked, no signal yet
        register_abort_signal(id, ev) → detects already revoked → sets ev immediately

    Race B — revoke AFTER registration:
        register_abort_signal(id, ev) → stores ev in _abort_signals
        revoke_execution(id)          → adds id to _revoked → finds ev → sets it

Both cases use the same _lock so they are atomic relative to each other.

What RevocationManager does NOT do
-----------------------------------
- Does not decide policy (that is AuthorizedPlan / ArtifactPolicy).
- Does not become the Kernel.
- Does not perform I/O (Docker calls are handled by ContainerBackend via abort_signal).
- Does not manage secrets (SecretInjector handles that).
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Optional

from .audit import AuditEventType, AuditLog, RevocationEvent
from .execution_registry import ExecutionRegistry

if TYPE_CHECKING:
    pass


class RevocationManager:
    """
    Real-time revocation controller for sandbox executions.

    Parameters
    ----------
    registry  : ExecutionRegistry to update on revocation.
    audit_log : AuditLog to record RevocationEvents.
    """

    def __init__(
        self,
        registry: ExecutionRegistry,
        audit_log: AuditLog,
    ) -> None:
        self._registry = registry
        self._audit_log = audit_log
        self._revoked: set[str] = set()
        self._abort_signals: dict[str, threading.Event] = {}
        self._plan_ids: dict[str, str] = {}   # execution_id → plan_id (for audit)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Core revocation API
    # ------------------------------------------------------------------

    def revoke_execution(
        self,
        execution_id: str,
        reason: str = "manual",
    ) -> None:
        """
        Revoke an execution by ID.

        Idempotent — calling multiple times for the same ID is safe.

        Parameters
        ----------
        execution_id : ID to revoke.
        reason       : "manual" | "policy" | "unknown"
        """
        with self._lock:
            already_revoked = execution_id in self._revoked
            self._revoked.add(execution_id)
            signal = self._abort_signals.get(execution_id)
            if signal is not None:
                signal.set()

        if already_revoked:
            return  # Idempotent — nothing more to do

        # Update registry (silent if run not yet registered)
        self._registry.mark_aborted(execution_id)

        # Look up plan_id for the audit event
        plan_id = self._plan_ids.get(execution_id, "")

        # Emit revocation event
        self._audit_log.emit(RevocationEvent(
            event_type=AuditEventType.EXECUTION_REVOKED,
            execution_id=execution_id,
            plan_id=plan_id,
            timestamp=time.time(),
            reason=reason,
        ))

    def check_revoked(self, execution_id: str) -> bool:
        """Return True if execution_id has been revoked."""
        with self._lock:
            return execution_id in self._revoked

    # ------------------------------------------------------------------
    # Abort signal registration (called by RunnerAPI)
    # ------------------------------------------------------------------

    def register_abort_signal(
        self,
        execution_id: str,
        abort_signal: threading.Event,
        plan_id: str = "",
    ) -> None:
        """
        Register an abort_signal for an execution that is about to start.

        If the execution was already revoked, sets the signal immediately
        so ContainerBackend aborts at the first poll.

        Parameters
        ----------
        execution_id : execution being registered.
        abort_signal : threading.Event — set to trigger abort in ContainerBackend.
        plan_id      : used for audit events emitted by revoke_execution().
        """
        with self._lock:
            self._abort_signals[execution_id] = abort_signal
            if plan_id:
                self._plan_ids[execution_id] = plan_id
            # Already revoked? Signal immediately.
            if execution_id in self._revoked:
                abort_signal.set()

    def unregister_abort_signal(self, execution_id: str) -> None:
        """
        Remove the abort signal after execution completes.

        Called in RunnerAPI's finally block — always, regardless of outcome.
        Safe to call even if no signal was registered.
        """
        with self._lock:
            self._abort_signals.pop(execution_id, None)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def revoked_ids(self) -> frozenset[str]:
        """Return a snapshot of all revoked execution IDs."""
        with self._lock:
            return frozenset(self._revoked)
