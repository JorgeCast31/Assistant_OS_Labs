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
        build_mso_entity_status()  # called for reachability probe only; result intentionally discarded
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
        # "available" here means the seat module is reachable and returned a valid
        # dict — not that a cognitive seat is configured. A seat with no configured
        # provider (availability="not_configured") is still counted as reachable.
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
        authority_status_str = "unavailable" if "error" in auth else "available"
        authority_counts = dict(auth.get("counts", {}))
    except Exception:
        authority_status_str = "unavailable"
        authority_counts = {}

    # -- Outcome status (read-only, fail-soft) -----------------------------------
    # build_outcome_status() with no IDs returns found=False, status="not_found"
    # immediately (all _find_* helpers return None when no IDs are supplied).
    # This is more honest than hardcoding "unavailable".
    outcome_info: dict[str, Any] = {
        "status": "unavailable",
        "found": False,
        "execution_closed": True,
        "sources_checked": [],
    }
    try:
        from .outcome_status import build_outcome_status
        raw_outcome = build_outcome_status()  # no IDs → not_found
        outcome_info = {
            "status": raw_outcome.get("outcome", {}).get("status", "unknown"),
            "found": bool(raw_outcome.get("found", False)),
            "execution_closed": True,  # ALWAYS True — no execution from UI
            "sources_checked": list(raw_outcome.get("sources", {}).keys()),
        }
    except Exception:
        outcome_info = {
            "status": "unavailable",
            "found": False,
            "execution_closed": True,
            "sources_checked": [],
        }

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
        "outcome": outcome_info,
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
    - confirm_pending reflects the same queue entries viewed as awaiting human confirmation
    - A run must NEVER have status: "running" — if nothing is running, return empty

    Returns
    -------
    dict
        Truth-contract dict. Never raises.
    """
    prepared_actions: list[dict[str, Any]] = []
    confirm_pending_items: list[dict[str, Any]] = []

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

            # Confirm pending: same entry viewed as awaiting human confirmation.
            # human_confirmation_status is always "pending" for queue entries.
            # execution_allowed and can_execute_now are always False (dataclass invariants).
            confirm_pending_items.append(
                {
                    "id": entry_id,
                    "status": "awaiting_confirmation",
                    "domain": entry.get("domain") or None,
                    "intent": intent,
                    "requested_action": entry.get("requested_action") or None,
                    "execution_allowed": False,   # ALWAYS False
                    "can_execute_now": False,      # ALWAYS False
                }
            )
    except Exception:
        prepared_actions = []
        confirm_pending_items = []

    return {
        "ok": True,
        "source": "backend_read_model",
        "execution_allowed": False,
        "used_execution": False,
        "runner_reachable_from_ui": False,
        "runs": [],        # no live runs — honest empty
        "threads": [],     # no live threads — honest empty
        "prepared_actions": prepared_actions,
        "confirm_pending": confirm_pending_items,
        "live_execution": False,
        "event_stream_connected": False,
    }


# ---------------------------------------------------------------------------
# 4. build_authority_trace_stage_list
# ---------------------------------------------------------------------------


def build_authority_trace_stage_list(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Map a build_authority_trace_snapshot() result to a UI-ready stages list.

    Each stage gets:
      - id          : stage key from AUTHORITY_CHAIN
      - label       : human-readable name
      - state       : 'available' | 'architectural' | 'unavailable'
      - evidence_ref: honest metadata string where available, None otherwise

    State rules:
      - mso_kernel         → always "available" (MSO is always present)
      - intent_contract    → "available" if snapshot.request.available else "architectural"
      - policy             → "available" if snapshot.policy.available else "architectural"
      - governance         → "available" if snapshot.governance.available else "architectural"
      - capability_token   → "available" if snapshot.capability.available else "architectural"
      - police_gate        → always "available" (wired into chain)
      - authority_artifact → always "available" (wired into chain)
      - runner             → always "architectural" (closed from UI — never reachable)
      - outcome            → "available" if snapshot.outcome.available else "unavailable"

    Evidence refs are populated honestly from snapshot data where present.
    Never fabricated. Returns a list even if snapshot is empty or malformed.

    Returns
    -------
    list[dict[str, Any]]
        9-element stages list. Never raises.
    """
    from .authority_trace import AUTHORITY_CHAIN

    # Safely extract nested stage data from snapshot
    def _stage(key: str) -> dict[str, Any]:
        val = snapshot.get(key, {})
        return val if isinstance(val, dict) else {}

    request_data    = _stage("request")
    policy_data     = _stage("policy")
    governance_data = _stage("governance")
    capability_data = _stage("capability")
    police_data     = _stage("police")
    artifact_data   = _stage("artifact")
    outcome_data    = _stage("outcome")

    # Each entry: (label, state, evidence_ref)
    stage_specs: dict[str, tuple[str, str, str | None]] = {
        "mso_kernel": (
            "MSO Kernel",
            "available",  # MSO is always present — never architectural
            "kernel_boundary:true · orchestrator_owned:true",
        ),
        "intent_contract": (
            "Intent Contract",
            "available" if request_data.get("available") else "architectural",
            "execution_intent:false",  # no execution intent at architectural rest
        ),
        "policy": (
            "PolicyDecision",
            "available" if policy_data.get("available") else "architectural",
            None,
        ),
        "governance": (
            "Governance",
            "available" if governance_data.get("available") else "architectural",
            None,
        ),
        "capability_token": (
            "CapabilityToken",
            "available" if capability_data.get("available") else "architectural",
            None,
        ),
        "police_gate": (
            "Police Gate",
            "available",  # always wired into the authority chain
            f"decision_visibility:{police_data.get('decision_visibility', 'not_persisted_yet')}",
        ),
        "authority_artifact": (
            "AuthorityArtifact",
            "available",  # always wired into the authority chain
            (
                f"artifact_version:{artifact_data.get('artifact_version', 'unknown')}"
                f" · authority_source:{artifact_data.get('authority_source', 'unknown')}"
            ),
        ),
        "runner": (
            "Runner",
            "architectural",  # ALWAYS closed from UI — runner_reachable_from_ui:false
            "fail_closed:true · executed:false · runner_reachable_from_ui:false",
        ),
        "outcome": (
            "Outcome",
            "available" if outcome_data.get("available") else "unavailable",
            "execution_closed:true",
        ),
    }

    stages: list[dict[str, Any]] = []
    for stage_id in AUTHORITY_CHAIN:
        label, state, evidence_ref = stage_specs.get(
            stage_id,
            (stage_id, "architectural", None),
        )
        stages.append(
            {
                "id": stage_id,
                "label": label,
                "state": state,
                "evidence_ref": evidence_ref,
            }
        )
    return stages
