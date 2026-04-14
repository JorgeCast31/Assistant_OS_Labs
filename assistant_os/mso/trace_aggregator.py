"""Unified MSO trace aggregation layer."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
from threading import RLock

from .contracts import DeterministicDecisionTrace, GovernanceDecision, TraceChain

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
