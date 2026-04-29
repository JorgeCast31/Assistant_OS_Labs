"""Read-only backend exposure helpers for UI operability surfaces."""

from __future__ import annotations

from typing import Any

from .agents.registry import list_agents
from .config import APPLY_EXECUTION_MODE, OPENCLAW_GATEWAY_URL
from .contracts import EXECUTION_MODE_CONFIRM
from .mso.capability_registry import (
    check_capability,
    list_active_revocations,
    list_registered_capabilities,
    list_temporary_grants,
)
from .mso.system_state import build_system_state_snapshot
from .mso.task_registry import list_tasks

_KNOWN_CODE_APPLY_MODES = {"stub", "real"}
_ACTIVE_AGENT_STATUSES = {"active", "idle", "degraded", "dormant", "unknown"}


def _agent_status_for_domain(domain: str | None, tasks: list[Any]) -> str:
    if not domain:
        return "unknown"
    matching = [task for task in tasks if getattr(task, "domain", "") == domain]
    if any(getattr(task, "status", "") == "active" for task in matching):
        return "active"
    if matching:
        return "dormant"
    return "idle"


def _last_task_for_domain(domain: str | None, tasks: list[Any]) -> Any | None:
    if not domain:
        return None
    for task in tasks:
        if getattr(task, "domain", "") == domain:
            return task
    return None


def _last_execution_at(task: Any | None) -> str | None:
    if task is None:
        return None
    return (
        getattr(task, "completed_at", "")
        or getattr(task, "updated_at", "")
        or getattr(task, "started_at", "")
        or getattr(task, "created_at", "")
        or None
    )


def _last_result(task: Any | None) -> dict[str, Any] | None:
    if task is None:
        return None
    return {
        "task_id": getattr(task, "task_id", ""),
        "status": getattr(task, "status", "") or None,
        "result_type": getattr(task, "result_type", "") or None,
        "error_type": getattr(task, "error_type", "") or None,
        "error_message": getattr(task, "error_message", "") or None,
    }


def _policy_restricted(domain: str | None, revocations: list[Any]) -> bool:
    if not domain:
        return False
    return any(getattr(item, "domain", "") in {domain, "*"} for item in revocations)


def _capability_status(action: str, domain: str) -> str:
    active_revocations = {
        (item.action, item.domain) for item in list_active_revocations(domain=domain, action=action)
    }
    if active_revocations:
        return "revoked"

    active_grants = {
        (item.action, item.domain) for item in list_temporary_grants(domain=domain, action=action)
    }
    if active_grants:
        return "granted"

    result = check_capability(action, domain)
    if result.allowed:
        return "available"
    return "blocked" if result.mode == "deny" else "unavailable"


def _machine_operator_feature_state() -> str:
    try:
        from .mso.machine_operator_adapter import (
            DEFAULT_MACHINE_OPERATOR_ADAPTER,
            OpenClawGatewayMachineOperatorAdapter,
            StubMachineOperatorAdapter,
            requests as machine_operator_requests,
        )
    except Exception:
        return "unknown"

    if isinstance(DEFAULT_MACHINE_OPERATOR_ADAPTER, StubMachineOperatorAdapter):
        return "unavailable"
    if isinstance(DEFAULT_MACHINE_OPERATOR_ADAPTER, OpenClawGatewayMachineOperatorAdapter):
        if machine_operator_requests is None:
            return "unavailable"
        return "available" if bool(OPENCLAW_GATEWAY_URL.strip()) else "unavailable"
    return "unknown"


def _authority_status_for_mode(operational_mode: str) -> str:
    if operational_mode == "NORMAL":
        return "active"
    if operational_mode == "FROZEN":
        return "blocked"
    if operational_mode in {"DEGRADED", "RESTRICTED"}:
        return "degraded"
    return "unknown"


def _recent_event_payloads(snapshot: Any, limit: int = 10) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for transition in snapshot.recent_task_transitions[:limit]:
        events.append(
            {
                "type": "task_transition",
                "ts": transition.at,
                "task_id": transition.task_id,
                "domain": transition.domain or None,
                "action": transition.action or None,
                "status": transition.to_status,
                "reason": transition.reason or None,
            }
        )

    for decision in snapshot.recent_governance_decisions[:limit]:
        events.append(
            {
                "type": "governance",
                "ts": decision.created_at,
                "action": decision.action,
                "domain": decision.target_domain or None,
                "target_action": decision.target_action or None,
                "execution_mode": decision.effective_execution_mode,
                "justification": decision.justification,
            }
        )

    events.sort(key=lambda item: item.get("ts", ""), reverse=True)
    return events[:limit]


def build_agents_registry_response() -> dict[str, Any]:
    """Build a stable, read-only projection of the canonical agent registry."""
    tasks = list_tasks()
    revocations = list_active_revocations()
    agents = []

    for agent in list_agents():
        domain = agent.get("domain")
        status = _agent_status_for_domain(domain, tasks)
        if status not in _ACTIVE_AGENT_STATUSES:
            status = "unknown"
        last_task = _last_task_for_domain(domain, tasks)

        agents.append(
            {
                "id": agent.get("name", ""),
                "name": agent.get("name", ""),
                "domain": domain or None,
                "description": agent.get("description") or None,
                "status": status,
                "capabilities": list(agent.get("capability_scope") or []),
                "last_execution_at": _last_execution_at(last_task),
                "last_result": _last_result(last_task),
                "policy_restricted": _policy_restricted(domain, revocations),
                # Registry entries are governed execution boundaries, so authority is required.
                "requires_authority": True,
                "requires_review": bool(agent.get("requires_review", False)),
            }
        )

    return {
        "ok": True,
        "agents": agents,
    }


def build_system_capabilities_response() -> dict[str, Any]:
    """Build a conservative capability/status view for UI observability."""
    registered = list_registered_capabilities()
    grants = list_temporary_grants()
    revocations = list_active_revocations()

    capability_keys = {
        (record.action, record.domain)
        for record in registered
    }
    capability_keys.update((grant.action, grant.domain) for grant in grants)
    capability_keys.update((revocation.action, revocation.domain) for revocation in revocations)

    capabilities = []
    for action, domain in sorted(capability_keys, key=lambda item: ((item[1] or ""), item[0])):
        resolved = check_capability(action, domain)
        capabilities.append(
            {
                "id": action,
                "domain": None if domain in {"", "*"} else domain,
                "mode": resolved.mode or None,
                "status": _capability_status(action, domain),
                "requires_confirmation": resolved.requires_confirmation,
            }
        )

    return {
        "ok": True,
        "features": {
            "authority_artifact": True,
            "replay_prevention": True,
            "runner_enforced": True,
            "code_apply_mode": APPLY_EXECUTION_MODE if APPLY_EXECUTION_MODE in _KNOWN_CODE_APPLY_MODES else "unknown",
            "machine_operator": _machine_operator_feature_state(),
        },
        "domains": sorted({item["domain"] for item in capabilities if item["domain"]}),
        "capabilities": capabilities,
    }


def build_mso_state_response() -> dict[str, Any]:
    """Build a compact MSO/system-state projection for UI status surfaces."""
    snapshot = build_system_state_snapshot()
    restrictions: list[str] = []

    if snapshot.operational_mode != "NORMAL":
        detail = snapshot.operational_mode_reason or snapshot.operational_mode_source or "active_override"
        restrictions.append(f"operational_mode:{snapshot.operational_mode}:{detail}")

    restrictions.extend(
        f"revocation:{item.domain}:{item.action}:{item.reason}"
        for item in snapshot.active_capability_revocations
    )

    pending_confirmations = sum(
        1 for task in snapshot.pending_tasks if getattr(task, "execution_mode", "") == EXECUTION_MODE_CONFIRM
    )

    return {
        "ok": True,
        "operational_mode": snapshot.operational_mode,
        "authority_status": _authority_status_for_mode(snapshot.operational_mode),
        "governance": {
            "frozen": snapshot.operational_mode == "FROZEN",
            "restrictions": restrictions,
        },
        "agents_available": len(build_agents_registry_response()["agents"]),
        "pending_confirmations": pending_confirmations,
        "active_executions": len(snapshot.running_executions),
        "recent_events": _recent_event_payloads(snapshot),
    }
