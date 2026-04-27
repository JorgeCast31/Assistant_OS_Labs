"""System state snapshot builder for dynamic MSO governance."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from threading import RLock

from ..contracts import now_iso
from .anomaly_engine import analyze_anomalies, build_domain_operational_states, derive_operational_mode
from .capability_registry import list_active_revocations, list_temporary_grants
from .contracts import AgentStatusSummary, DomainStatusSummary, OperationalMode, SystemStateSnapshot
from .task_registry import get_recent_transitions, list_tasks
from .trace_aggregator import get_recent_decisions, get_recent_governance_decisions, list_trace_chains
from ..storage.mso_store import list_recent_worker_security_events

_lock = RLock()
_operational_mode_override: OperationalMode | None = None
_operational_mode_reason = ""

# Persisted state file — written atomically, read on startup.
_STATE_FILE = Path(".assistant_os_state.json")

_PERSIST_MODES = {"FROZEN", "DEGRADED", "RESTRICTED"}


def _persist_state(mode: OperationalMode | None, reason: str) -> None:
    """Atomically write current mode override to disk."""
    payload = {"operational_mode": mode, "reason": reason}
    tmp = Path(str(_STATE_FILE) + ".tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(_STATE_FILE)
    except OSError:
        pass  # Persistence is best-effort; in-memory state is authoritative


def _load_persisted_state() -> None:
    """Read persisted mode from disk on startup and apply to in-memory state."""
    global _operational_mode_override, _operational_mode_reason
    if not _STATE_FILE.exists():
        return
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        mode = data.get("operational_mode")
        reason = str(data.get("reason", ""))
        if mode in _PERSIST_MODES:
            with _lock:
                _operational_mode_override = mode  # type: ignore[assignment]
                _operational_mode_reason = reason
    except (OSError, json.JSONDecodeError):
        pass


def set_operational_mode(mode: OperationalMode, *, reason: str = "") -> None:
    """Force a system-wide operational mode until cleared."""
    global _operational_mode_override, _operational_mode_reason
    with _lock:
        _operational_mode_override = mode
        _operational_mode_reason = reason
    _persist_state(mode, reason)


def clear_operational_mode_override() -> None:
    global _operational_mode_override, _operational_mode_reason
    with _lock:
        _operational_mode_override = None
        _operational_mode_reason = ""
    _persist_state(None, "")


def get_operational_mode_override() -> tuple[OperationalMode | None, str]:
    with _lock:
        return _operational_mode_override, _operational_mode_reason


# Apply any persisted mode override immediately on module load.
_load_persisted_state()


def build_system_state_snapshot(*, transition_limit: int = 20, decision_limit: int = 20) -> SystemStateSnapshot:
    """Build a structured snapshot of the current observable system state."""
    all_tasks = list_tasks()
    active_tasks = [task for task in all_tasks if task.status == "active"]
    pending_tasks = [task for task in all_tasks if task.status == "pending"]
    blocked_tasks = [task for task in all_tasks if task.status == "blocked"]

    domain_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for task in all_tasks:
        domain_counts[task.domain][task.status] += 1

    domain_status_summary = [
        DomainStatusSummary(
            domain=domain,
            active=counts.get("active", 0),
            pending=counts.get("pending", 0),
            completed=counts.get("completed", 0),
            failed=counts.get("failed", 0),
            blocked=counts.get("blocked", 0),
        )
        for domain, counts in sorted(domain_counts.items())
    ]

    recent_governance_decisions = get_recent_governance_decisions(limit=decision_limit)
    recent_worker_security_events = list_recent_worker_security_events(limit=decision_limit)
    anomaly_signals = analyze_anomalies(
        domain_status_summary=domain_status_summary,
        recent_governance_decisions=recent_governance_decisions,
        recent_worker_security_events=recent_worker_security_events,
    )
    override_mode, override_reason = get_operational_mode_override()
    operational_mode, operational_mode_reason, operational_mode_source = derive_operational_mode(
        anomaly_signals,
        override_mode=override_mode,
        override_reason=override_reason,
    )

    domain_operational_states = build_domain_operational_states(
        domain_status_summary,
        anomaly_signals,
        operational_mode=operational_mode,
    )

    active_with_advisory = sum(1 for task in active_tasks if task.advisory_trace_ref)
    active_code_tasks = sum(1 for task in active_tasks if task.domain == "CODE")
    active_cognitive_tasks = sum(1 for task in active_tasks if task.domain == "COGNITIVE")
    agent_status_summary = [
        AgentStatusSummary(
            agent_name="orchestrator",
            status="active" if active_tasks else "idle",
            active_tasks=len(active_tasks),
            notes="Canonical structural executor.",
        ),
        AgentStatusSummary(
            agent_name="advisory_engine",
            status="observed" if active_with_advisory or all_tasks else "idle",
            active_tasks=active_with_advisory,
            notes="Observation-only advisory layer; no execution authority.",
        ),
        AgentStatusSummary(
            agent_name="code_executor",
            status="observed" if active_code_tasks or any(task.domain == "CODE" for task in all_tasks) else "idle",
            active_tasks=active_code_tasks,
            notes="Derived from CODE-domain tasks; no direct heartbeat yet.",
        ),
        AgentStatusSummary(
            agent_name="local_cognitive_worker",
            status="observed" if active_cognitive_tasks or any(task.domain == "COGNITIVE" for task in all_tasks) else "idle",
            active_tasks=active_cognitive_tasks,
            notes="Bounded cognitive execution worker; no persistent state mutation authority.",
        ),
    ]

    trace_chains = list_trace_chains(limit=decision_limit)
    return SystemStateSnapshot(
        generated_at=now_iso(),
        operational_mode=operational_mode,
        operational_mode_reason=operational_mode_reason,
        operational_mode_source=operational_mode_source,
        active_tasks=active_tasks,
        pending_tasks=pending_tasks,
        blocked_tasks=blocked_tasks,
        recent_task_transitions=get_recent_transitions(limit=transition_limit),
        recent_decisions=get_recent_decisions(limit=decision_limit),
        recent_governance_decisions=recent_governance_decisions,
        recent_anomaly_signals=anomaly_signals[:decision_limit],
        recent_worker_security_events=recent_worker_security_events[:decision_limit],
        active_capability_grants=list_temporary_grants()[:decision_limit],
        active_capability_revocations=list_active_revocations()[:decision_limit],
        running_executions=[task.execution_id or task.plan_id for task in active_tasks],
        domain_status_summary=domain_status_summary,
        domain_operational_states=domain_operational_states,
        agent_status_summary=agent_status_summary,
        trace_chain_refs=[chain.chain_id for chain in trace_chains],
    )
