"""Unified MSO trace aggregation layer."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
from threading import RLock

from .contracts import (
    DelegationTask,
    DeterministicDecisionTrace,
    EscalationRequest,
    ExecutionCapability,
    ExecutionReport,
    GovernanceDecision,
    SovereignCycleRecord,
    SovereignIntent,
    TraceChain,
    WorkerSecurityEvent,
)

_lock = RLock()
_chains: dict[str, TraceChain] = {}
_recent_decisions: deque[DeterministicDecisionTrace] = deque(maxlen=200)
_recent_governance: deque[GovernanceDecision] = deque(maxlen=200)


def begin_trace_chain(
    *,
    task_id: str,
    context_id: str,
    trace_id: str,
    plan_id: str,
    request_text: str,
    operation: str,
    domain: str,
    action: str,
    execution_mode: str,
    created_at: str,
    advisory_trace: dict | None,
    decision_trace: DeterministicDecisionTrace,
    governance_trace: dict | None = None,
    governance_decision: GovernanceDecision | None = None,
    surface: str = "",
) -> TraceChain:
    """Register the initial unified chain before any execution occurs."""
    chain = TraceChain(
        chain_id=plan_id,
        task_id=task_id,
        context_id=context_id,
        trace_id=trace_id,
        plan_id=plan_id,
        request_text=request_text,
        operation=operation,
        domain=domain,
        action=action,
        execution_mode=execution_mode,
        created_at=created_at,
        surface=surface,
        advisory_trace_ref=f"advisory:{plan_id}" if advisory_trace else "",
        decision_trace_ref=decision_trace.decision_ref,
        governance_trace_ref=governance_decision.governance_ref if governance_decision else "",
        advisory_trace=dict(advisory_trace or {}),
        decision_trace=asdict(decision_trace),
        governance_trace=asdict(governance_decision) if governance_decision else dict(governance_trace or {}),
    )
    with _lock:
        _chains[plan_id] = chain
        _recent_decisions.append(decision_trace)
        if governance_decision is not None:
            _recent_governance.append(governance_decision)
    return chain


def attach_cognitive_execution(
    plan_id: str,
    *,
    sovereign_intent: SovereignIntent | None = None,
    delegation_task: DelegationTask | None = None,
    execution_capability: ExecutionCapability | None = None,
    execution_report: ExecutionReport | None = None,
    escalation_request: EscalationRequest | None = None,
) -> TraceChain | None:
    """Attach sovereign/worker contracts to an existing unified chain."""
    with _lock:
        chain = _chains.get(plan_id)
        if chain is None:
            return None
        if sovereign_intent is not None:
            chain.sovereign_intent = asdict(sovereign_intent)
            chain.sovereign_intent_ref = f"intent:{sovereign_intent.intent_id}"
        if delegation_task is not None:
            chain.delegation_task = asdict(delegation_task)
            chain.delegation_task_ref = f"delegation:{delegation_task.task_id}"
        if execution_capability is not None:
            chain.execution_capability = asdict(execution_capability)
            chain.execution_capability_ref = f"capability:{execution_capability.capability_id}"
        if execution_report is not None:
            chain.execution_report = asdict(execution_report)
            chain.execution_report_ref = f"report:{execution_report.report_id}"
        if escalation_request is not None:
            chain.escalation_request = asdict(escalation_request)
            chain.escalation_request_ref = f"escalation:{escalation_request.escalation_id}"
        return chain


def attach_sovereign_cycle(plan_id: str, cycle: SovereignCycleRecord) -> TraceChain | None:
    """Attach runtime cycle bookkeeping to an existing chain."""
    with _lock:
        chain = _chains.get(plan_id)
        if chain is None:
            return None
        chain.sovereign_cycle = asdict(cycle)
        chain.sovereign_cycle_ref = f"cycle:{cycle.cycle_id}"
        return chain


def attach_worker_security_events(plan_id: str, events: list[WorkerSecurityEvent]) -> TraceChain | None:
    """Attach worker security events to an existing chain."""
    with _lock:
        chain = _chains.get(plan_id)
        if chain is None:
            return None
        for event in events:
            chain.worker_security_events.append(asdict(event))
            chain.worker_security_event_refs.append(f"worker_event:{event.event_id}")
        return chain


def attach_persistence_refs(plan_id: str, refs: dict[str, str]) -> TraceChain | None:
    """Attach persistence references to an existing chain."""
    with _lock:
        chain = _chains.get(plan_id)
        if chain is None:
            return None
        chain.persistence_refs.update({k: v for k, v in refs.items() if v})
        return chain


def finalize_trace_chain(
    plan_id: str,
    *,
    executed: bool,
    result: dict,
    execution_id: str = "",
) -> TraceChain | None:
    """Attach result/execution data to an existing chain."""
    with _lock:
        chain = _chains.get(plan_id)
        if chain is None:
            return None
        chain.execution = {
            "executed": executed,
            "execution_id": execution_id or result.get("plan_id", ""),
            "result_type": result.get("result_type", ""),
            "ok": result.get("ok", False),
        }
        chain.result = dict(result)
        return chain


def get_trace_chain(plan_id: str) -> TraceChain | None:
    with _lock:
        return _chains.get(plan_id)


def list_trace_chains(limit: int = 20) -> list[TraceChain]:
    with _lock:
        chains = list(_chains.values())
    return sorted(chains, key=lambda item: item.created_at, reverse=True)[:limit]


def get_recent_decisions(limit: int = 20) -> list[DeterministicDecisionTrace]:
    with _lock:
        items = list(_recent_decisions)
    return list(reversed(items[-limit:]))


def get_recent_governance_decisions(limit: int = 20) -> list[GovernanceDecision]:
    with _lock:
        items = list(_recent_governance)
    return list(reversed(items[-limit:]))


def reset_trace_aggregator() -> None:
    with _lock:
        _chains.clear()
        _recent_decisions.clear()
        _recent_governance.clear()
