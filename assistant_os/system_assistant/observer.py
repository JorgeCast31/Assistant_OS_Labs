"""System Assistant — read-only observation layer.

This module provides observe_system() which reads existing state from
read-only sources and returns a structured SystemSnapshot.

INVARIANTS — never violated by this module:
  - Does NOT call any domain pipeline.
  - Does NOT call any agent entrypoint.
  - Does NOT call Kernel handle_request().
  - Does NOT call MSO governance / evaluation methods.
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
    status: str                         # "ok" | "partial" | "unavailable"
    operational_mode: str | None        # override mode or None if not set
    agents: list[dict[str, Any]]        # read-only agent metadata summaries
    capabilities: list[dict[str, Any]]  # read-only capability records
    tasks_summary: dict[str, int]       # counts by status
    warnings: list[str]                 # non-fatal source errors


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

    # Degrade status if any warnings were recorded.
    if warnings:
        snapshot["status"] = "partial"

    return snapshot
