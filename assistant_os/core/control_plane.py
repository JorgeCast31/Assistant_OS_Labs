"""
control_plane.py — Agent lifecycle authority for the HOST domain.

SINGLE SOURCE OF TRUTH for:
  - Agent activation status: ACTIVE / PAUSED / QUARANTINE
  - In-flight process registry (_IN_FLIGHT)
  - kill_switch authority

Rules
-----
- Only ACTIVE agents may launch host processes.
- kill_switch() quarantines the agent, reconciles stale PIDs, then calls abort_in_flight().
- register_in_flight() is called by host_agent AFTER a successful Popen.
- abort_in_flight() iterates all known PIDs and sends SIGTERM.
- An agent not explicitly activated defaults to PAUSED.
- reconcile_in_flight() removes stale (dead) PIDs from the registry.

Thread safety
-------------
All state mutations use a single module-level threading.Lock.
OS liveness checks (_is_pid_alive) are performed OUTSIDE the lock to avoid
blocking I/O under contention; the subsequent cleanup write is atomic.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class AgentStatus(str, Enum):
    ACTIVE     = "active"
    PAUSED     = "paused"
    QUARANTINE = "quarantine"


@dataclass
class AbortResult:
    """Outcome of a single PID abort attempt."""
    pid:          int
    execution_id: str
    success:      bool
    error:        Optional[str] = None


@dataclass
class KillSwitchResult:
    """Aggregate result of a kill_switch() call."""
    agent_id:      str
    abort_results: list[AbortResult] = field(default_factory=list)

    @property
    def all_aborted(self) -> bool:
        """True iff every in-flight PID was terminated without error."""
        return all(r.success for r in self.abort_results)


@dataclass
class ReconcileResult:
    """
    Result of a reconcile_in_flight() call.

    Fields
    ------
    agent_id : the agent whose registry was reconciled
    alive    : records whose PIDs are still alive (kept in registry)
    cleaned  : records whose PIDs were dead and removed from registry
    """
    agent_id: str
    alive:    list[dict] = field(default_factory=list)
    cleaned:  list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Module-level state (thread-safe)
# ---------------------------------------------------------------------------

_lock = threading.Lock()

# agent_id → AgentStatus
# Agents not yet explicitly activated default to PAUSED.
_AGENT_STATUS: dict[str, AgentStatus] = {}

# agent_id → list of {
#   "pid":          int   — process ID
#   "execution_id": str   — correlates with audit events
#   "action":       str   — action that launched the process (Phase 5C)
#   "started_at":   float — epoch seconds at registration (Phase 5C)
# }
_IN_FLIGHT: dict[str, list[dict]] = {}


# ---------------------------------------------------------------------------
# Agent status control
# ---------------------------------------------------------------------------


def activate_agent(agent_id: str) -> None:
    """Set agent status to ACTIVE. Required before any host launch."""
    with _lock:
        _AGENT_STATUS[agent_id] = AgentStatus.ACTIVE


def pause_agent(agent_id: str) -> None:
    """Set agent status to PAUSED. Blocks future launches."""
    with _lock:
        _AGENT_STATUS[agent_id] = AgentStatus.PAUSED


def quarantine_agent(agent_id: str) -> None:
    """Set agent status to QUARANTINE. Blocks future launches."""
    with _lock:
        _AGENT_STATUS[agent_id] = AgentStatus.QUARANTINE


def get_agent_status(agent_id: str) -> AgentStatus:
    """Return current status. Defaults to PAUSED if never activated."""
    with _lock:
        return _AGENT_STATUS.get(agent_id, AgentStatus.PAUSED)


# ---------------------------------------------------------------------------
# In-flight registration
# ---------------------------------------------------------------------------


def register_in_flight(
    agent_id: str,
    pid: int,
    execution_id: str,
    action: str = "",
) -> None:
    """
    Record a live PID under agent_id.

    Called by host_agent immediately after subprocess.Popen succeeds.
    kill_switch() reads this table to know which PIDs to terminate.

    Phase 5C: action and started_at are stored for observability and
    stale-PID diagnosis; both default safely for backward compat.
    """
    with _lock:
        if agent_id not in _IN_FLIGHT:
            _IN_FLIGHT[agent_id] = []
        _IN_FLIGHT[agent_id].append({
            "pid":          pid,
            "execution_id": execution_id,
            "action":       action,
            "started_at":   time.time(),
        })


def get_in_flight(agent_id: str) -> list[dict]:
    """Return a snapshot copy of in-flight records for agent_id."""
    with _lock:
        return list(_IN_FLIGHT.get(agent_id, []))


def deregister_in_flight(agent_id: str, pid: int) -> None:
    """
    Remove a single PID from in-flight records for agent_id.

    Called by host_agent after a successful close_pid (SIGTERM sent).
    Idempotent: silently does nothing if pid is not found.
    """
    with _lock:
        records = _IN_FLIGHT.get(agent_id, [])
        _IN_FLIGHT[agent_id] = [r for r in records if r["pid"] != pid]


def clear_in_flight(agent_id: str) -> None:
    """Remove all in-flight records for agent_id (post-abort cleanup)."""
    with _lock:
        _IN_FLIGHT.pop(agent_id, None)


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def _is_pid_alive(pid: int) -> bool:
    """
    Return True if pid is still alive (or we cannot confirm it is dead).

    Uses os.kill(pid, 0) — signal 0 checks process existence without killing.

    PermissionError → process EXISTS but we cannot signal it → treat as alive
    (conservative: false positive is safe; false negative would remove a live PID).
    OSError (not PermissionError) → process does not exist → treat as dead.
    """
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True   # exists but unowned — conservatively alive
    except OSError:
        return False  # no such process


def reconcile_in_flight(agent_id: str) -> ReconcileResult:
    """
    Remove stale (dead) PIDs from the in-flight registry for agent_id.

    Algorithm
    ---------
    1. Snapshot current records (under lock, returns a copy).
    2. Check liveness of each PID *outside* the lock (OS call, not blocking
       in practice but follows "no I/O under lock" discipline).
    3. Atomically remove the dead entries (under lock).

    Returns ReconcileResult with alive and cleaned record lists.

    Safe to call at any time; idempotent; does not affect other agents.
    """
    snapshot = get_in_flight(agent_id)
    if not snapshot:
        return ReconcileResult(agent_id=agent_id)

    alive: list[dict] = []
    cleaned: list[dict] = []
    for record in snapshot:
        (alive if _is_pid_alive(record["pid"]) else cleaned).append(record)

    if cleaned:
        dead_pids = {r["pid"] for r in cleaned}
        with _lock:
            current = _IN_FLIGHT.get(agent_id, [])
            _IN_FLIGHT[agent_id] = [r for r in current if r["pid"] not in dead_pids]

    return ReconcileResult(agent_id=agent_id, alive=alive, cleaned=cleaned)


def abort_in_flight(agent_id: str) -> list[AbortResult]:
    """
    Attempt SIGTERM on every in-flight PID for agent_id.

    Captures per-PID errors individually so a single stale PID does not
    prevent terminating the others.  Clears _IN_FLIGHT for agent_id when done.

    Returns list of AbortResult (one per recorded PID).
    """
    records = get_in_flight(agent_id)
    results: list[AbortResult] = []
    for record in records:
        pid = record["pid"]
        eid = record["execution_id"]
        try:
            os.kill(pid, signal.SIGTERM)
            results.append(AbortResult(pid=pid, execution_id=eid, success=True))
        except OSError as exc:
            results.append(AbortResult(pid=pid, execution_id=eid, success=False, error=str(exc)))
    clear_in_flight(agent_id)
    return results


def kill_switch(agent_id: str) -> KillSwitchResult:
    """
    Authoritative kill for an agent.

    Steps (in order):
    1. quarantine_agent(agent_id)    — immediately blocks new launches
    2. reconcile_in_flight(agent_id) — prune dead PIDs before sending SIGTERM
    3. abort_in_flight(agent_id)     — SIGTERM all live recorded PIDs
    4. Return KillSwitchResult       — includes per-PID outcomes

    Phase 5D: reconcile_in_flight is called before abort_in_flight so that
    stale (already-dead) PIDs do not generate spurious OSError abort failures.
    abort_in_flight clears _IN_FLIGHT when done.

    Callers must NOT assume all PIDs were successfully terminated;
    inspect KillSwitchResult.abort_results for per-PID outcomes.
    """
    quarantine_agent(agent_id)
    reconcile_in_flight(agent_id)
    abort_results = abort_in_flight(agent_id)
    return KillSwitchResult(agent_id=agent_id, abort_results=abort_results)


# ---------------------------------------------------------------------------
# Test helper — NOT for production use
# ---------------------------------------------------------------------------


def _reset_state_for_tests() -> None:
    """Clear all module state. ONLY for use in test teardown/setup."""
    with _lock:
        _AGENT_STATUS.clear()
        _IN_FLIGHT.clear()
