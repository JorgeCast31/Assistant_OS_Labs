"""
Mission Control Status — read-model aggregation layer.

S-MISSION-CONTROL-TRUTH-CONTRACTS-ALPHA-01 / Task 2

Three public functions that aggregate existing MSO read-model data into
canonical truth-contract dicts for Mission Control surfaces.

INVARIANTS (enforced here, never relaxed)
-----------------------------------------
- execution_allowed  = False  (always)
- used_execution     = False  (always)
- runner_reachable_from_ui = False  (always)
- source             = "backend_read_model"  (always)

These functions are read-only. No Runner calls, no Police bypass,
no token issuance, no AuthorityArtifact creation, no execution path.

Degradation contract
--------------------
If any upstream call fails, the corresponding section degrades to
"unavailable" or an honest empty state. Success is NEVER fabricated.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# 1. build_mission_control_status
# ---------------------------------------------------------------------------


def build_mission_control_status() -> dict[str, Any]:
    """
    Aggregate entity_status, seat_status, prepared_action_queue, and
    authority counts into a single truth-contract dict.

    State derivation:
      - "available"   if both entity_status and seat_status are reachable
      - "partial"     if exactly one is reachable
      - "unavailable" if neither is reachable

    Returns
    -------
    dict
        Truth-contract dict. Never raises.
    """
    # -- Entity status -------------------------------------------------------
    entity_ok = False
    try:
        from .entity_status import build_mso_entity_status
        build_mso_entity_status()
        entity_ok = True
    except Exception:
        entity_ok = False

    entity_status_str = "available" if entity_ok else "unavailable"

    # -- Seat status ---------------------------------------------------------
    seat_ok = False
    try:
        from .seat_status import build_mso_seat_status
        seat_result = build_mso_seat_status()
        # Seat status always returns a dict; treat as available unless it
        # explicitly signals an error (the function itself is fail-soft).
        seat_ok = "error" not in seat_result
    except Exception:
        seat_ok = False

    seat_status_str = "available" if seat_ok else "unavailable"

    # -- Prepared action queue count -----------------------------------------
    prepared_actions_count = 0
    try:
        from .prepared_action_queue import list_pending_confirmable_action_dicts
        prepared_actions_count = len(list_pending_confirmable_action_dicts())
    except Exception:
        prepared_actions_count = 0

    # -- Authority status ----------------------------------------------------
    authority_status_str = "unavailable"
    authority_counts: dict[str, Any] = {}
    try:
        from .authority_status import get_authority_status
        auth = get_authority_status()
        authority_status_str = auth.get("source", "authority_status")
        authority_counts = dict(auth.get("counts", {}))
    except Exception:
        authority_status_str = "unavailable"
        authority_counts = {}

    # -- Derive overall state ------------------------------------------------
    available_count = sum([entity_ok, seat_ok])
    if available_count == 2:
        state = "available"
    elif available_count == 1:
        state = "partial"
    else:
        state = "unavailable"

    overall_ok = available_count > 0

    return {
        "ok": overall_ok,
        "source": "backend_read_model",
        "execution_allowed": False,
        "used_execution": False,
        "runner_reachable_from_ui": False,
        "mission_control": {
            "state": state,
            "mode": "read_model",
            "execution_allowed": False,
            "used_execution": False,
        },
        "mso": {
            "entity_status": entity_status_str,
            "seat_status": seat_status_str,
            "boundary": "sovereign",
        },
        "queues": {
            "prepared_actions_count": prepared_actions_count,
            "confirm_pending_count": 0,  # confirm queue not separate at this layer
        },
        "authority": {
            "status": authority_status_str,
            "counts": authority_counts,
        },
        "outcome": {
            "status": "unavailable",  # no live outcome data at this layer
        },
    }


# ---------------------------------------------------------------------------
# 2. build_mission_control_readiness
# ---------------------------------------------------------------------------


def build_mission_control_readiness() -> dict[str, Any]:
    """
    Aggregate the agent registry into a readiness truth-contract dict.

    Each registered agent is exposed as an "arm" with:
      - execution_status   = "unavailable"  (no live arm status; never fabricated)
      - can_execute_without_mso = False     (always)
      - requires_authority = True           (always)

    Overall system state:
      - "available"   if list_agents() returns one or more agents
      - "partial"     if list_agents() returns an empty list (registry OK but empty)
      - "unavailable" if list_agents() raises

    Returns
    -------
    dict
        Truth-contract dict. Never raises.
    """
    arms: list[dict[str, Any]] = []
    overall = "unavailable"

    try:
        from ..agents.registry import list_agents
        agents = list_agents()

        if agents:
            overall = "available"
        else:
            overall = "partial"  # registry reachable but empty

        for agent in agents:
            # AgentDefinition is a plain dict — access via keys
            name = agent.get("name") or f"agent_{id(agent)}"
            arms.append(
                {
                    "id": name,
                    "label": name,
                    "available": True,             # registered = available as resource
                    "execution_status": "unavailable",  # no live status — honest
                    "readiness_source": "agent_registry",
                    "can_execute_without_mso": False,   # ALWAYS False
                    "requires_authority": True,          # ALWAYS True
                }
            )
    except Exception:
        overall = "unavailable"
        arms = []

    overall_ok = overall in ("available", "partial")

    return {
        "ok": overall_ok,
        "source": "backend_read_model",
        "execution_allowed": False,
        "used_execution": False,
        "runner_reachable_from_ui": False,
        "arms": arms,
        "system": {
            "overall": overall,
        },
    }


# ---------------------------------------------------------------------------
# 3. build_orchestration_snapshot
# ---------------------------------------------------------------------------


def build_orchestration_snapshot() -> dict[str, Any]:
    """
    Aggregate the prepared action queue into an orchestration snapshot dict.

    - runs and threads are always [] — there is no live execution
    - prepared_actions is derived from the queue (honest read-model)
    - A run must NEVER have status: "running" — if nothing is running, return empty

    Returns
    -------
    dict
        Truth-contract dict. Never raises.
    """
    prepared_actions: list[dict[str, Any]] = []

    try:
        from .prepared_action_queue import list_pending_confirmable_action_dicts
        raw_entries = list_pending_confirmable_action_dicts()

        for entry in raw_entries:
            # Resolve a stable ID — prefer queue_entry_id, fall back to prepared_action_id
            entry_id = (
                entry.get("queue_entry_id")
                or entry.get("prepared_action_id")
                or "unknown"
            )

            # Truncate user_intent to first 60 chars for surface transport
            raw_intent: str | None = entry.get("user_intent") or None
            intent: str | None = raw_intent[:60] if raw_intent else None

            prepared_actions.append(
                {
                    "id": entry_id,
                    "status": "prepared",
                    "domain": entry.get("domain") or None,
                    "intent": intent,
                }
            )
    except Exception:
        prepared_actions = []

    return {
        "ok": True,
        "source": "backend_read_model",
        "execution_allowed": False,
        "used_execution": False,
        "runner_reachable_from_ui": False,
        "runs": [],       # no live runs — honest empty
        "threads": [],    # no live threads — honest empty
        "prepared_actions": prepared_actions,
        "confirm_pending": [],  # no separate confirm queue at this layer yet
        "live_execution": False,
        "event_stream_connected": False,
    }
