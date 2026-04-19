"""
AssistantOS — Policy Engine (F4)

A minimal, deterministic policy engine that decides access based on BOTH
the subject's lifecycle state and the type of operation being requested.

Design principles
-----------------
- Pure function at the core: same inputs → same output, always.
- No external state, no I/O, no randomness, no LLM.
- No side effects: the engine does not log, mutate, or call services.
- No domain coupling: operates on abstract ActionType, not FIN/WORK strings.
- Fail-closed: unknown state or action type → DENY.
- Simple: the entire policy is one static lookup table.

Decision basis
--------------
    (SubjectState, ActionType) → GuardDecision

    SubjectState captures the subject's lifecycle:
        Active      — normal operation
        Quarantined — isolated; partial read access
        Suspended   — halted; no access
        Terminated  — closed; no access

    ActionType captures the abstract class of operation:
        READ    — observe state, query data, read resources
        WRITE   — mutate state, create/update/delete records
        EXECUTE — commit and run a previously staged plan
        NETWORK — call external services or APIs
        POLICY  — modify governance, configuration, or access rules

Policy table (4 states × 5 action types):

    ┌─────────────┬────────┬──────────┬─────────┬─────────┬────────┐
    │ State       │ READ   │ WRITE    │ EXECUTE │ NETWORK │ POLICY │
    ├─────────────┼────────┼──────────┼─────────┼─────────┼────────┤
    │ Active      │ ALLOW  │ ALLOW    │ ALLOW   │ ALLOW   │ ALLOW  │
    │ Quarantined │ DEGRAD │ DEGRAD   │ DENY    │ DENY    │ DENY   │
    │ Suspended   │ DENY   │ DENY     │ DENY    │ DENY    │ DENY   │
    │ Terminated  │ DENY   │ DENY     │ DENY    │ DENY    │ DENY   │
    └─────────────┴────────┴──────────┴─────────┴─────────┴────────┘

    DEGRAD = DEGRADED (partial access; enforcement downstream)

Backward compatibility with F2/F3
----------------------------------
    Quarantined × READ  → DEGRADED  (same as F2: read flagged, not blocked)
    Quarantined × WRITE → DEGRADED  (same as F2: write blocked downstream)
    Suspended   × any   → DENY      (same as F2: full denial)
    Terminated  × any   → DENY      (same as F2: full denial)

    New semantics added in F4 (no equivalent in F2):
    Quarantined × EXECUTE → DENY    (committing plans blocked outright)
    Quarantined × NETWORK → DENY    (external calls blocked outright)
    Quarantined × POLICY  → DENY    (governance changes blocked outright)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .identity import Principal, SubjectState
    from .identity_guard import GuardDecision


# ---------------------------------------------------------------------------
# ActionType
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    """
    Abstract classification of the operation being requested.

    Callers map their concrete operation strings (ACTION_* constants,
    classifier intent labels, domain names) to one of these abstract types
    before passing them to the policy engine.  The engine never sees
    domain-specific strings like "FIN_EXPENSE" or "WORK_CREATE".

    Variants:
        READ    — Observe, query, inspect.  Does not mutate state.
                  Examples: WORK_QUERY, CODE_EXPLAIN, FIN_PLAN, passthrough.
        WRITE   — Create, update, or delete records.  Mutates state.
                  Examples: FIN_EXPENSE, WORK_CREATE, CODE_FIX.
        EXECUTE — Commit and execute a previously staged/confirmed plan.
                  More consequential than WRITE: triggers external actions.
                  Examples: FIN_COMMIT, FIN_BATCH, FIN_CONFIRM, WORK_CONFIRM.
        NETWORK — Call an external service, API, or webhook.
                  Examples: future HTTP tool, external API bridge.
        POLICY  — Modify governance rules, access configuration, or
                  system-level settings.
                  Examples: future admin commands, agent policy changes.
    """
    READ    = "read"
    WRITE   = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    POLICY  = "policy"


# ---------------------------------------------------------------------------
# PolicyContext (placeholder for F4.5+)
# ---------------------------------------------------------------------------

@dataclass
class PolicyContext:
    """
    Optional resource context passed alongside the action.

    Currently a placeholder — the engine does not use it for decisions.
    Reserved for F4.5+ when resource-level policies are introduced
    (e.g., "can this principal write to THIS specific resource?").

    Fields:
        resource_id   — Identifier of the target resource (task id, doc id…).
        resource_type — Type tag for the resource ("task", "expense", …).
        extra         — Extensible bag for future context fields.
    """
    resource_id:   Optional[str] = None
    resource_type: Optional[str] = None
    extra:         dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Policy table — the single source of truth for access decisions
# ---------------------------------------------------------------------------

# Import here for the table definition; guarded under TYPE_CHECKING above
# for the function signatures.  At runtime we import lazily to avoid
# circular imports at module load time.

def _build_policy_table() -> "dict[tuple, str]":
    """
    Build and return the immutable policy table.

    Keys:   (SubjectState.value, ActionType.value)
    Values: GuardDecision.value  ("allow" | "deny" | "degraded")

    Using string keys keeps the table JSON-compatible and avoids importing
    enum classes at module load (which would create circular import risk).
    """
    return {
        # ── Active — full access for all action types ─────────────────────
        ("active", "read"):    "allow",
        ("active", "write"):   "allow",
        ("active", "execute"): "allow",
        ("active", "network"): "allow",
        ("active", "policy"):  "allow",

        # ── Quarantined — read/write degraded; execute/network/policy denied ─
        ("quarantined", "read"):    "degraded",
        ("quarantined", "write"):   "degraded",
        ("quarantined", "execute"): "deny",
        ("quarantined", "network"): "deny",
        ("quarantined", "policy"):  "deny",

        # ── Suspended — complete denial ───────────────────────────────────
        ("suspended", "read"):    "deny",
        ("suspended", "write"):   "deny",
        ("suspended", "execute"): "deny",
        ("suspended", "network"): "deny",
        ("suspended", "policy"):  "deny",

        # ── Terminated — complete denial ──────────────────────────────────
        ("terminated", "read"):    "deny",
        ("terminated", "write"):   "deny",
        ("terminated", "execute"): "deny",
        ("terminated", "network"): "deny",
        ("terminated", "policy"):  "deny",
    }


# Module-level singleton — built once, never mutated.
_POLICY_TABLE: "dict[tuple, str]" = _build_policy_table()


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------

def evaluate_policy(
    principal: "Principal",
    subject_state: "SubjectState",
    action_type: ActionType,
    context: Optional[PolicyContext] = None,
) -> "GuardDecision":
    """
    Evaluate the policy and return a GuardDecision.

    This is the ONLY function where the access decision is made.
    It is pure: no side effects, no I/O, no mutable state.

    The ``context`` parameter is accepted for forward compatibility but is
    not used in the current decision.  Future versions may use it for
    resource-level decisions (F4.5+).

    Args:
        principal:     The acting party (used for future attribute-based rules).
        subject_state: Lifecycle state of the subject at request time.
        action_type:   Abstract class of the operation being requested.
        context:       Optional resource context (currently unused).

    Returns:
        GuardDecision — ALLOW, DENY, or DEGRADED.
        Falls back to DENY on any lookup miss (fail-closed).
    """
    from .identity_guard import GuardDecision  # local to avoid circular at module level

    key = (subject_state.value, action_type.value)
    raw = _POLICY_TABLE.get(key)

    if raw is None:
        # Unknown (state, action) combination — fail closed.
        return GuardDecision.DENY

    return GuardDecision(raw)


# ---------------------------------------------------------------------------
# ActionType inference — maps concrete operation strings to abstract types
# ---------------------------------------------------------------------------

# String prefixes that identify EXECUTE operations (commit / run staged plans).
# Checked before WRITE because some execute operations share write prefixes.
_EXECUTE_PREFIXES: tuple[str, ...] = (
    "FIN_COMMIT", "FIN_BATCH", "FIN_CONFIRM",
    "WORK_CONFIRM", "WORK_APPROVE",
    "CODE_COMMIT", "CODE_PUSH", "CODE_DEPLOY",
    "EXECUTE", "CONFIRM", "COMMIT", "DEPLOY",
)

# String prefixes that identify WRITE operations (create / update / delete).
_WRITE_PREFIXES: tuple[str, ...] = (
    # WORK domain
    "WORK_CREATE", "WORK_UPDATE", "WORK_DELETE", "WORK_EDIT",
    "WORK_ASSIGN", "WORK_CLOSE", "WORK_REOPEN",
    # FIN domain
    "FIN_EXPENSE", "FIN_CREATE", "FIN_UPDATE", "FIN_DELETE",
    "FIN_RECORD", "FIN_APPROVE", "FIN_REJECT",
    # CODE domain
    "CODE_FIX", "CODE_CREATE", "CODE_UPDATE", "CODE_DELETE",
    # Generic cross-domain
    "CREATE", "UPDATE", "DELETE", "WRITE", "SUBMIT",
)

# String prefixes that identify NETWORK operations.
_NETWORK_PREFIXES: tuple[str, ...] = (
    "NETWORK", "HTTP", "API_CALL", "EXTERNAL", "WEBHOOK",
)

# String prefixes that identify POLICY / ADMIN operations.
_POLICY_PREFIXES: tuple[str, ...] = (
    "POLICY", "ADMIN", "CONFIG", "GOVERNANCE", "GRANT", "REVOKE",
)


def infer_action_type(action: Optional[str]) -> ActionType:
    """
    Infer an abstract ActionType from a concrete operation string.

    Mapping is done by prefix matching against canonical lists.
    Check order: EXECUTE → WRITE → NETWORK → POLICY → READ (default).

    EXECUTE is checked first because some EXECUTE operations (e.g.
    FIN_COMMIT) share prefixes with WRITE operations (FIN_*).

    The default is READ — callers that don't know the action type get the
    most permissive (non-write) classification, which is safe because
    downstream enforcement handles DEGRADED write blocking separately.

    Args:
        action: An ACTION_* constant string, classifier intent, or domain name.
                None / empty string → READ.

    Returns:
        ActionType — abstract classification.
    """
    if not action:
        return ActionType.READ

    upper = action.upper()

    if any(upper.startswith(p) for p in _EXECUTE_PREFIXES):
        return ActionType.EXECUTE

    if any(upper.startswith(p) for p in _WRITE_PREFIXES):
        return ActionType.WRITE

    if any(upper.startswith(p) for p in _NETWORK_PREFIXES):
        return ActionType.NETWORK

    if any(upper.startswith(p) for p in _POLICY_PREFIXES):
        return ActionType.POLICY

    return ActionType.READ


# ---------------------------------------------------------------------------
# Policy reason strings — human-readable explanations per decision
# ---------------------------------------------------------------------------

def policy_reason(
    subject_state: "SubjectState",
    action_type: ActionType,
    decision: "GuardDecision",
) -> str:
    """
    Return a human-readable reason string for a policy decision.

    Kept in the policy engine so the vocabulary for decisions lives in one
    place.  Reasons are informational — not used for access control logic.

    Args:
        subject_state: The state that drove the decision.
        action_type:   The operation type that was evaluated.
        decision:      The resulting decision.

    Returns:
        A non-empty explanation string.
    """
    from .identity_guard import GuardDecision  # local to avoid circular

    state_val = subject_state.value
    action_val = action_type.value

    if decision == GuardDecision.ALLOW:
        return f"Subject is active; {action_val} access granted."

    if decision == GuardDecision.DEGRADED:
        return (
            f"Subject is quarantined; {action_val} access is in degraded mode. "
            "Write operations will be blocked; read operations are permitted."
        )

    # DENY — vary by state for clarity
    if state_val == "suspended":
        return (
            f"Subject is suspended; {action_val} operation denied. "
            "No operations are permitted until the session is released."
        )
    if state_val == "terminated":
        return (
            f"Subject session has been terminated; {action_val} operation denied. "
            "No further operations are permitted."
        )
    if state_val == "quarantined":
        return (
            f"Subject is quarantined; {action_val} operation denied. "
            "Only read and write operations are permitted in degraded mode."
        )

    # Unknown state
    return (
        f"Policy denied {action_val} for subject in state '{state_val}'. "
        "Unknown state; failing closed."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "ActionType",
    "PolicyContext",
    "evaluate_policy",
    "infer_action_type",
    "policy_reason",
]
