"""System state snapshot builder for MSO governance."""

from __future__ import annotations

from collections import defaultdict

from ..contracts import now_iso
from .contracts import AgentStatusSummary, DomainStatusSummary, SystemStateSnapshot
from .task_registry import get_recent_transitions, list_tasks
from .trace_aggregator import get_recent_decisions, get_recent_governance_decisions, list_trace_chains


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

    active_with_advisory = sum(1 for task in active_tasks if task.advisory_trace_ref)
    active_code_tasks = sum(1 for task in active_tasks if task.domain == "CODE")
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
    ]

    trace_chains = list_trace_chains(limit=decision_limit)
    return SystemStateSnapshot(
        generated_at=now_iso(),
        active_tasks=active_tasks,
        pending_tasks=pending_tasks,
        blocked_tasks=blocked_tasks,
        recent_task_transitions=get_recent_transitions(limit=transition_limit),
        recent_decisions=get_recent_decisions(limit=decision_limit),
        recent_governance_decisions=get_recent_governance_decisions(limit=decision_limit),
        running_executions=[task.execution_id or task.plan_id for task in active_tasks],
        domain_status_summary=domain_status_summary,
        agent_status_summary=agent_status_summary,
        trace_chain_refs=[chain.chain_id for chain in trace_chains],
    )
