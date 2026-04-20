"""
Grant Models — Sprint 13.

Pure data types for the explicit grant layer.
No logic, no I/O, no LLM.

Design
------
The grant layer sits between the capability check (Sprint 9) and the
final APPROVED/DENIED decision inside policy_engine.evaluate_policy().

Evaluation order inside evaluate_policy (S13 updated):
  1. subject_state hard stop
  2. guard_decision hard stop
  3. required_capability(action_type)
  4. capability evaluation
  5. grant lookup  ← NEW (this sprint)
  6. DEGRADED path
  7. APPROVED

Step 5 rule:
  - grant found → proceed to step 6 / 7
  - no grant found → DENIED(NO_APPLICABLE_GRANT)

The check is only enforced when the grant store is non-empty.
An empty store is treated as "permissive" to preserve backward
compatibility with Sprint 9–12 tests that pre-date the grant layer.

Types
-----
Grant
    Immutable record of a granted permission.  is_active and expires_at
    control whether the grant is currently valid.

GrantQuery
    Immutable snapshot of the inputs used to look up a grant.  Built
    inside evaluate_policy from PolicyContext fields.

Non-negotiable constraints
--------------------------
- No DB / persistence (process memory, Sprint scope).
- No provenance metadata yet.
- No attenuation (grants cannot be further restricted after issuance).
- No revocation engine yet (set is_active=False to revoke manually).
- Fail-closed: any matching deviation → no grant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Grant
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Grant:
    """
    Immutable grant record.

    A Grant authorizes a specific principal to perform a specific action
    (identified by action_type + capability) on operations whose context_id
    (operation_key) matches the scope_prefix.

    Fields
    ------
    grant_id      : Stable unique identifier (UUID string).
    principal_id  : Who the grant is for.  Must match exactly.
    action_type   : Abstract action class ("read", "write", "execute", …).
                    Must match exactly.  "" is not a wildcard — it matches
                    only requests with action_type="" (legacy/NL callers).
    capability    : Capability.value required for action_type, or None.
                    None matches queries where no capability is required
                    (e.g., "read" → required_capability returns None).
                    Must match exactly.
    scope_prefix  : Prefix filter against the operation_key (context_id).
                    Empty string "" matches any operation_key (no restriction).
                    Non-empty: grant applies only when
                    operation_key.startswith(scope_prefix).
    is_active     : False means the grant has been manually revoked.
                    Inactive grants are never returned by find_applicable_grant.
    issued_at     : time.time() at grant creation.
    expires_at    : Optional expiry as a time.time() timestamp.
                    None means the grant never expires.
                    An expired grant is never returned by find_applicable_grant.
    """

    grant_id:     str
    principal_id: str
    action_type:  str
    capability:   Optional[str]
    scope_prefix: str
    is_active:    bool
    issued_at:    float
    expires_at:   Optional[float] = None


# ---------------------------------------------------------------------------
# GrantQuery
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GrantQuery:
    """
    Immutable snapshot of the authorization inputs used to look up a grant.

    Built inside evaluate_policy from the PolicyContext immediately after
    capability evaluation (step 4) and used in step 5 (grant lookup).

    Fields
    ------
    principal_id  : From PolicyContext.principal_id.
    action_type   : From PolicyContext.action_type.
    capability    : required_capability(action_type).value, or None.
                    Matches only grants whose capability field equals this.
    operation_key : From PolicyContext.operation_key (= context_id in the
                    orchestrator).  Compared against Grant.scope_prefix.
    """

    principal_id:  str
    action_type:   str
    capability:    Optional[str]
    operation_key: str
