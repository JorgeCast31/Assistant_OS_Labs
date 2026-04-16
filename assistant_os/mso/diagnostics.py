"""Minimal diagnostics surface for sovereign and cognitive execution state."""

from __future__ import annotations

from dataclasses import asdict

from ..executors.cognitive_worker_runner import get_runner_status
from ..storage.mso_store import (
    get_store_status,
    list_recent_cycles,
    list_recent_delegations,
    list_recent_escalations,
    list_recent_intents,
    list_recent_operator_actions,
    list_recent_reports,
    list_recent_restrictions,
    list_recent_security_responses,
    list_recent_translator_rejections,
    list_recent_worker_security_events,
)
from .operator_identity import list_operator_identities
from .governance_surface import (
    get_active_restrictions_view,
    get_cognitive_restriction_level,
    get_hardened_domains,
    get_operational_mode,
    get_recent_anomaly_signals,
    get_recent_expired_restrictions_view,
    get_recent_operator_actions as get_operator_actions,
    get_recent_security_responses as get_security_responses,
    get_recent_worker_security_events as get_worker_security_events,
    get_system_state,
)


def get_mso_diagnostics(limit: int = 10) -> dict:
    snapshot = get_system_state()
    operational_mode, mode_reason, mode_source = get_operational_mode()
    recent_reports = list_recent_reports(limit=limit)
    security_events = list_recent_worker_security_events(limit=limit)
    security_responses = list_recent_security_responses(limit=limit)
    recent_restrictions = list_recent_restrictions(limit=limit)
    operator_actions = list_recent_operator_actions(limit=limit)
    worker_failures = [
        item
        for item in recent_reports
        if item.get("payload", {}).get("status") in {"failed", "timeout", "blocked", "needs_escalation"}
    ]
    event_counters: dict[str, int] = {}
    for item in security_events:
        event_type = item.get("payload", {}).get("event_type", "")
        if event_type:
            event_counters[event_type] = event_counters.get(event_type, 0) + 1
    return {
        "operational_mode": {
            "mode": operational_mode,
            "reason": mode_reason,
            "source": mode_source,
        },
        "active_tasks": [task.task_id for task in snapshot.active_tasks],
        "recent_cycles": list_recent_cycles(limit=limit),
        "recent_delegations": list_recent_delegations(limit=limit),
        "recent_intents": list_recent_intents(limit=limit),
        "recent_reports": recent_reports,
        "recent_escalations": list_recent_escalations(limit=limit),
        "recent_translator_rejections": list_recent_translator_rejections(limit=limit),
        "recent_worker_security_events": security_events,
        "security_event_counters": event_counters,
        "triggered_responses": security_responses,
        "active_restrictions": [asdict(item) for item in get_active_restrictions_view()],
        "recent_expired_restrictions": [asdict(item) for item in get_recent_expired_restrictions_view(limit=limit)],
        "recent_restrictions": recent_restrictions,
        "recent_operator_actions": operator_actions,
        "operator_identities": [asdict(item) for item in list_operator_identities()],
        "worker_lifecycle_events": get_worker_security_events(limit=limit),
        "worker_failures": worker_failures,
        "worker_runner_status": get_runner_status(),
        "current_restriction_level": get_cognitive_restriction_level(),
        "worker_health_summary": {
            "recent_failure_count": len(worker_failures),
            "recent_security_event_count": len(security_events),
            "recent_response_count": len(security_responses),
        },
        "store_status": get_store_status(),
        "recent_anomalies": [asdict(signal) for signal in get_recent_anomaly_signals(limit=limit)],
        "hardened_domains": get_hardened_domains(),
        "recent_security_responses": get_security_responses(limit=limit),
        "operator_action_ledger": get_operator_actions(limit=limit),
    }
