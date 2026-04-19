"""
Capability Gate — Sprint 9.

Deterministic, fail-closed gate for MO (MACHINE_OPERATOR) execution capabilities.

Design
------
This module answers a single question:
  "Given a subject's lifecycle state, is this specific MO capability permitted?"

It is orthogonal to the identity guard:
  - Identity guard:   (subject_state, ActionType)  → GuardDecision (ALLOW/DENY/DEGRADED)
  - Capability gate:  (subject_state, Capability)  → bool

The identity guard is lifecycle-level and coarse-grained (read/write/execute).
The capability gate is MO-execution-level and fine-grained (execute_code/write_files).
Both checks must pass for MO execution to proceed.

Principles
----------
- No LLM involvement — purely static lookup table.
- No external config or DSL — rules are code, auditable here.
- Fail-closed: unknown subject_state → no capabilities allowed.
- Unknown action_type → no specific capability required (non-MO actions pass through).
- Does not duplicate identity guard logic; sits downstream of it.

Integration
-----------
Called from orchestrator.handle_request() AFTER all identity guard checks
(guard_decision already stamped on request), BEFORE execution dispatch.

Usage
-----
    cap = required_capability(req.get("action_type", ""))
    if cap is not None and not evaluate_capability(req.get("subject_state", ""), cap):
        return make_domain_result(ok=False, result_type="denied", ...)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Capability — specific MO execution capabilities
# ---------------------------------------------------------------------------

class Capability(str, Enum):
    """
    Specific MO execution capabilities.

    Values are intentionally short, lowercase strings so they can be used
    as literal tokens in AuthorizedPlan.capability_scope without a separate
    constant registry.

    EXECUTE_CODE : Execute arbitrary code in an isolated container.
    WRITE_FILES  : Write, patch, or replace files in a workspace.
    """

    EXECUTE_CODE = "execute_code"
    WRITE_FILES  = "write_files"


# ---------------------------------------------------------------------------
# ActionType → Capability mapping
# ---------------------------------------------------------------------------

# Maps ActionType string values (from policy_engine.ActionType) to the
# specific Capability required for that action.
#
# Actions not listed here (e.g. "read", "network", "policy") require no
# specific MO capability and pass through the gate unconditionally.
_ACTION_CAPABILITY_MAP: dict[str, Capability] = {
    "execute": Capability.EXECUTE_CODE,
    "write":   Capability.WRITE_FILES,
}


def required_capability(action_type: str) -> Optional[Capability]:
    """
    Return the Capability required for action_type, or None.

    None means no specific MO capability is required — the gate passes
    unconditionally for that action type (e.g. "read").

    Parameters
    ----------
    action_type : ActionType string value from the request (e.g. "execute").

    Returns
    -------
    Capability if the action requires a specific capability; None otherwise.
    """
    return _ACTION_CAPABILITY_MAP.get(action_type)


# ---------------------------------------------------------------------------
# Capability matrix — subject_state → allowed capabilities
# ---------------------------------------------------------------------------

# Static, exhaustive matrix.  Any state not listed maps to an empty frozenset
# (fail-closed: unknown states are denied all MO capabilities).
#
# Relationship to identity guard policy table (policy_engine.py):
#   The identity guard already denies EXECUTE for quarantined, suspended, and
#   terminated subjects.  The capability gate provides a redundant, independent
#   second layer at the capability level.  "Defence in depth" — not duplication.
_CAPABILITY_MATRIX: dict[str, frozenset[Capability]] = {
    "active":      frozenset({Capability.EXECUTE_CODE, Capability.WRITE_FILES}),
    "quarantined": frozenset({Capability.WRITE_FILES}),  # no code execution
    "suspended":   frozenset(),
    "terminated":  frozenset(),
}


def evaluate_capability(subject_state: str, capability: Capability) -> bool:
    """
    Deterministic, fail-closed capability check.

    Returns True iff subject_state permits capability.

    Parameters
    ----------
    subject_state : Subject lifecycle state string (e.g. "active", "quarantined").
    capability    : The specific Capability to check.

    Returns
    -------
    bool — True if allowed, False if denied.
    False for any subject_state not in the matrix (fail-closed).
    """
    allowed = _CAPABILITY_MATRIX.get(subject_state, frozenset())
    return capability in allowed
