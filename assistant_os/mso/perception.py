"""MSO Economic Perception Frame — SPRINT-ALPHA-02.

Produces a bounded, read-only grounding context for MSO cognitive generation.
All subsystem reads are isolated with try/except. No source read can raise
out of build_economic_perception_frame(). No execution. No side effects.

Safety invariants (enforced by design, never delegated to any subsystem):
  - execution_allowed = False  (always, hardcoded at return site)
  - can_execute_now  = False  (always, hardcoded at return site)
  - execution_closed = True   (always, hardcoded at return site)
  - No queue/task/governance state is mutated.
  - No network calls.
  - No new LLM calls.
"""
from __future__ import annotations

from ..contracts import now_iso

_AUTHORITY_POSTURE = (
    "Toda ejecucion requiere: PolicyDecision -> CapabilityToken -> "
    "OperationBinding -> AuthorizedPlan -> PoliceGate."
)
_LIMITATIONS = (
    "You cannot execute. You cannot issue tokens. "
    "You cannot approve plans. "
    "You can describe, reason, inspect, propose, and explain."
)
_MAX_ITEMS = 5


# ---------------------------------------------------------------------------
# Per-source readers — each accepts a mutable warnings list, appends on failure,
# and always returns a safe default. Never raises out.
# ---------------------------------------------------------------------------

def _read_operational_mode(warnings: list[str]) -> str:
    try:
        from ..operability import build_mso_state_response
        state = build_mso_state_response()
        return state.get("operational_mode", "UNKNOWN")
    except Exception as exc:
        warnings.append(f"operational_mode unavailable: {exc}")
        return "UNKNOWN"


def _read_seat_provider(warnings: list[str]) -> str:
    try:
        from .seat_model_provider_registry import describe_seated_provider
        return describe_seated_provider()
    except Exception as exc:
        warnings.append(f"seat_provider unavailable: {exc}")
        return "No cognitive provider is currently seated/configured."


def _read_prepared_actions(warnings: list[str]) -> list[dict]:
    try:
        from .prepared_action_queue import list_pending_confirmable_action_dicts
        items = list_pending_confirmable_action_dicts()
        return items[:_MAX_ITEMS]
    except Exception as exc:
        warnings.append(f"prepared_actions unavailable: {exc}")
        return []


def _read_capabilities_summary(warnings: list[str]) -> dict:
    try:
        from ..operability import build_system_capabilities_response
        caps = build_system_capabilities_response()
        domains = caps.get("domains") or []
        features = caps.get("features") or {}
        capabilities = caps.get("capabilities") or []
        active = [c["id"] for c in capabilities if c.get("status") == "active"][:_MAX_ITEMS]
        return {
            "domains": domains,
            "active_capabilities": active,
            "machine_operator": features.get("machine_operator", "unknown"),
            "runner_enforced": bool(features.get("runner_enforced")),
        }
    except Exception as exc:
        warnings.append(f"capabilities_summary unavailable: {exc}")
        return {}


def _read_recent_governance(warnings: list[str]) -> list[dict]:
    try:
        from .governance_surface import get_recent_governance
        decisions = get_recent_governance(limit=_MAX_ITEMS)
        result: list[dict] = []
        for d in (decisions or [])[:_MAX_ITEMS]:
            if isinstance(d, dict):
                result.append(d)
            elif hasattr(d, "__dict__"):
                result.append(d.__dict__.copy())
            else:
                result.append({"raw": str(d)})
        return result
    except Exception as exc:
        warnings.append(f"recent_governance unavailable: {exc}")
        return []


def _read_active_tasks_brief(warnings: list[str]) -> list[dict]:
    try:
        from .governance_surface import get_active_tasks
        tasks = get_active_tasks()
        result: list[dict] = []
        for t in (tasks or [])[:_MAX_ITEMS]:
            result.append({
                "task_id": getattr(t, "task_id", ""),
                "domain": getattr(t, "domain", ""),
                "status": getattr(t, "status", ""),
                "last_known_action": getattr(t, "last_known_action", ""),
                "created_at": getattr(t, "created_at", ""),
            })
        return result
    except Exception as exc:
        warnings.append(f"active_tasks_brief unavailable: {exc}")
        return []


def _read_recent_failures(warnings: list[str]) -> list[dict]:
    try:
        from .governance_surface import get_recent_failures
        tasks = get_recent_failures(limit=_MAX_ITEMS)
        result: list[dict] = []
        for t in (tasks or [])[:_MAX_ITEMS]:
            result.append({
                "task_id": getattr(t, "task_id", ""),
                "domain": getattr(t, "domain", ""),
                "status": getattr(t, "status", ""),
                "error_type": getattr(t, "error_type", ""),
                "error_message": getattr(t, "error_message", ""),
                "created_at": getattr(t, "created_at", ""),
            })
        return result
    except Exception as exc:
        warnings.append(f"recent_failures unavailable: {exc}")
        return []


# ---------------------------------------------------------------------------
# next_safe_step derivation — pure function, no I/O
# ---------------------------------------------------------------------------

def _derive_next_safe_step(operational_mode: str, prepared_count: int) -> str:
    if operational_mode not in ("NORMAL", "UNKNOWN"):
        return (
            f"Resuelve la restriccion de gobernanza. "
            f"Modo operacional: {operational_mode}."
        )
    if prepared_count > 0:
        return (
            f"Revisa {prepared_count} accion(es) preparada(s) en la cola de confirmacion. "
            "Cada accion incluye una linea de autoridad de 11 etapas. "
            "La ejecucion permanece cerrada."
        )
    return (
        "Crea un plan_request para iniciar un flujo gobernado. "
        "No hay acciones pendientes de confirmacion."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_economic_perception_frame() -> dict:
    """Build a bounded, read-only economic perception frame for MSO cognitive generation.

    All subsystem reads are isolated. Never raises. Returns safe defaults on
    any subsystem failure and records the failure in perception_warnings.

    Execution boundary is hardcoded at the return site — cannot be overridden
    by any subsystem read or exception path.
    """
    warnings: list[str] = []

    operational_mode = _read_operational_mode(warnings)
    seat_provider = _read_seat_provider(warnings)
    prepared_actions = _read_prepared_actions(warnings)
    capabilities_summary = _read_capabilities_summary(warnings)
    recent_governance = _read_recent_governance(warnings)
    active_tasks_brief = _read_active_tasks_brief(warnings)
    recent_failures = _read_recent_failures(warnings)

    prepared_count = len(prepared_actions)
    next_safe_step = _derive_next_safe_step(operational_mode, prepared_count)

    return {
        # Identity
        "version": "alpha-02",
        "generated_at": now_iso(),
        # Execution boundary — immutable; hardcoded here, not derived from any source
        "execution_allowed": False,
        "can_execute_now": False,
        "execution_closed": True,
        # Operational posture
        "operational_mode": operational_mode,
        "seat_provider": seat_provider,
        "authority_posture": _AUTHORITY_POSTURE,
        "next_safe_step": next_safe_step,
        "limitations": _LIMITATIONS,
        # Prepared actions (bounded to _MAX_ITEMS)
        "prepared_actions_count": prepared_count,
        "prepared_actions_summary": prepared_actions,
        "confirm_pending_count": prepared_count,
        "confirm_pending_summary": prepared_actions,
        # Capabilities
        "capabilities_summary": capabilities_summary,
        # Governance (bounded to _MAX_ITEMS)
        "recent_governance": recent_governance,
        # Tasks (bounded to _MAX_ITEMS each)
        "active_tasks_brief": active_tasks_brief,
        "recent_failures": recent_failures,
        # Session history — deferred; no session store available in this sprint
        "session_history_available": False,
        "session_history": [],
        # Diagnostics
        "perception_warnings": warnings,
    }


__all__ = ["build_economic_perception_frame"]
