"""System Assistant — read-only observation layer.

This module provides observe_system() which reads existing state from
read-only sources and returns a structured SystemSnapshot.

INVARIANTS — never violated by this module:
  - Does NOT call any domain pipeline.
  - Does NOT call any agent entrypoint.
  - Does NOT call Kernel handle_request().
  - Does NOT call MSO governance / evaluation methods.
  - MAY read governance surfaces as passive read-only observability
    (governance_surface.py read facades only); does NOT evaluate, decide,
    or infer MSO activity or health from those reads.
  - Does NOT issue, consume, or validate capability tokens.
  - Does NOT write to audit_store.
  - Does NOT mutate ExecutionRegistry or any mutable state.
  - Does NOT modify sovereign_state_store or operational mode.
  - Does NOT produce execution_mode, GovernanceVerdict, or PolicyDecision.

Failure behaviour:
  - Individual source failure → warning entry in snapshot; other sources continue.
  - Total unexpected failure at the top level → snapshot with status "unavailable".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Public contract
# ---------------------------------------------------------------------------

class SystemSnapshot(TypedDict, total=False):
    """Read-only observation snapshot.

    All fields are optional (total=False) so partial snapshots are valid
    when sources are unavailable.
    """

    generated_at: str
    status: str                                   # "ok" | "partial" | "unavailable"
    operational_mode: str | None                  # override mode or None if not set
    agents: list[dict[str, Any]]                  # read-only agent metadata summaries
    capabilities: list[dict[str, Any]]            # read-only capability records
    tasks_summary: dict[str, int]                 # counts by status
    warnings: list[str]                           # non-fatal source errors
    governance_status_summary: dict[str, Any] | None   # compact read from governance_surface
    recent_governance: list[dict[str, Any]] | None     # lightweight recent decisions
    code_readiness_summary: dict[str, Any] | None      # compact CODE readiness (counts, not full caps)


# ---------------------------------------------------------------------------
# Internal per-source readers — isolated so tests can patch individually.
# ---------------------------------------------------------------------------

def _read_operational_mode() -> str | None:
    """Read the current operational mode override. Returns None if not set."""
    from assistant_os.mso.system_state import get_operational_mode_override
    mode, _ = get_operational_mode_override()
    return mode


def _read_agents_summary() -> list[dict[str, Any]]:
    """Return read-only metadata for all registered agents.

    Reads name, domain, version, description, and capability_scope only.
    Never calls entrypoints.
    """
    from assistant_os.agents.registry import list_agents
    result = []
    for agent in list_agents():
        result.append({
            "name": agent.get("name"),
            "domain": agent.get("domain"),
            "version": agent.get("version"),
            "description": agent.get("description"),
            "capability_scope": list(agent.get("capability_scope") or []),
        })
    return result


def _read_capabilities_summary() -> list[dict[str, Any]]:
    """Return read-only summary of registered capabilities."""
    from assistant_os.mso.capability_registry import list_registered_capabilities
    result = []
    for record in list_registered_capabilities():
        result.append({
            "action": getattr(record, "action", None),
            "domain": getattr(record, "domain", None),
            "mode": getattr(record, "mode", None),
            "allowed": getattr(record, "allowed", None),
        })
    return result


def _read_tasks_summary() -> dict[str, int]:
    """Return a count of tasks by status. Read-only; no mutations."""
    from assistant_os.mso.task_registry import list_tasks
    all_tasks = list_tasks()
    summary: dict[str, int] = {}
    for task in all_tasks:
        status = getattr(task, "status", "unknown") or "unknown"
        summary[status] = summary.get(status, 0) + 1
    return summary


def _read_governance_status_summary() -> dict[str, Any]:
    """Read operational mode and key governance counts from governance_surface.

    Passive read-only; does not evaluate, decide, or imply MSO activity or health.
    """
    from assistant_os.mso.governance_surface import get_governance_summary, get_operational_mode
    summary = get_governance_summary()
    mode, _mode_reason, mode_source = get_operational_mode()
    return {
        "source": "mso_governance_status",
        "operational_mode": mode,
        "operational_mode_source": mode_source,
        "hardened_domain_count": len(summary.hardened_domains),
        "active_revocation_count": summary.active_revocation_count,
        "active_grant_count": summary.active_grant_count,
        "recent_anomaly_count": summary.recent_anomaly_count,
        "ephemeral": True,
        "note": "Governance status is operational runtime state, not MSO activity or health.",
    }


def _read_code_readiness_summary() -> dict[str, Any]:
    """Return a COMPACT CODE readiness snapshot.

    Passive read-only; does NOT execute, mutate, or imply CODE authority.
    The full capability list is intentionally NOT embedded here — only counts.
    Callers wanting the full list should hit ``/code/readiness`` directly.
    """
    from assistant_os.codeops.readiness import get_code_readiness
    full = get_code_readiness()
    return {
        "source": "code_readiness",
        "domain": full.get("domain", "CODE"),
        "feature_enabled": bool(full.get("feature_enabled", False)),
        "code_api_reachable": bool(full.get("code_api_reachable", False)),
        "apply_execution_mode": full.get("apply_execution_mode", "unknown"),
        "apply_real_enabled": bool(full.get("apply_real_enabled", False)),
        "runner_backend_probed": bool(full.get("runner_backend_probed", False)),
        "runner_backend_available": full.get("runner_backend_available", None),
        "code_capability_allowed_count": int(full.get("code_capability_allowed_count", 0) or 0),
        "code_capability_confirm_only_count": int(full.get("code_capability_confirm_only_count", 0) or 0),
        "code_capability_blocked_count": int(full.get("code_capability_blocked_count", 0) or 0),
        "note": full.get("note", "Readiness is not authority."),
    }


def _read_recent_governance_summary(limit: int = 3) -> list[dict[str, Any]]:
    """Return recent governance decisions as lightweight dicts.

    Passive read-only; does not evaluate, decide, or imply MSO activity or health.
    Handles both dataclass-shaped and dict-shaped nested reason objects.
    """
    from assistant_os.mso.governance_surface import get_recent_governance
    decisions = get_recent_governance(limit=limit)
    result = []
    for d in decisions:
        reasons = getattr(d, "reasons", None) or []
        reason_text: str | None = None
        if reasons:
            first = reasons[0]
            if isinstance(first, dict):
                reason_text = first.get("detail") or first.get("code") or None
            else:
                reason_text = getattr(first, "detail", None) or getattr(first, "code", None) or None
        if not reason_text:
            reason_text = getattr(d, "justification", None) or None
        result.append({
            "governance_ref": d.governance_ref,
            "created_at": d.created_at,
            "action": d.action,
            "target_domain": d.target_domain,
            "target_action": d.target_action,
            "risk_level": d.risk_level,
            "operational_mode": d.operational_mode,
            "effective_execution_mode": d.effective_execution_mode,
            "reason": reason_text,
        })
    return result


# ---------------------------------------------------------------------------
# Public observer function
# ---------------------------------------------------------------------------

def observe_system() -> SystemSnapshot:
    """Return a read-only snapshot of observable system state.

    Each source is collected independently. A source failure produces a
    warning entry but does not prevent other sources from being read.

    Returns a SystemSnapshot dict. Never raises.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    snapshot: SystemSnapshot = {
        "generated_at": generated_at,
        "status": "ok",
        "warnings": warnings,
    }

    # --- operational_mode ---
    try:
        snapshot["operational_mode"] = _read_operational_mode()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"operational_mode source unavailable: {exc}")
        snapshot["operational_mode"] = None

    # --- agents ---
    try:
        snapshot["agents"] = _read_agents_summary()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"agents source unavailable: {exc}")
        snapshot["agents"] = []

    # --- capabilities ---
    try:
        snapshot["capabilities"] = _read_capabilities_summary()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"capabilities source unavailable: {exc}")
        snapshot["capabilities"] = []

    # --- tasks summary ---
    try:
        snapshot["tasks_summary"] = _read_tasks_summary()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"tasks source unavailable: {exc}")
        snapshot["tasks_summary"] = {}

    # --- governance status summary ---
    try:
        snapshot["governance_status_summary"] = _read_governance_status_summary()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Governance status unavailable: {exc}")
        snapshot["governance_status_summary"] = None

    # --- recent governance ---
    try:
        snapshot["recent_governance"] = _read_recent_governance_summary()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Recent governance unavailable: {exc}")
        snapshot["recent_governance"] = None

    # --- CODE readiness summary (compact, counts only) ---
    try:
        snapshot["code_readiness_summary"] = _read_code_readiness_summary()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"CODE readiness unavailable: {exc}")
        snapshot["code_readiness_summary"] = None

    # Degrade status if any warnings were recorded.
    if warnings:
        snapshot["status"] = "partial"

    return snapshot
