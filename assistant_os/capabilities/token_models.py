"""
Capability Token Models — Sprint 12.

Pure data types for the process-local capability token layer.
No logic, no I/O, no LLM.

Design
------
The token layer sits between the Policy Engine (Sprint 10) and execution
dispatch.  Every request that earns PolicyDecision.APPROVED must also
acquire a CapabilityToken before any execution pipeline is invoked.

  PolicyDecision(APPROVED)
    → issue_token(OperationBinding) → CapabilityToken
    → verify_token(token, binding)  → bool (fail-closed)
    → consume_token(token)          → mark single-use
    → execute pipeline / _execute_confirmed_plan

Types
-----
TokenStatus
    Three-valued lifecycle: ACTIVE → CONSUMED (or EXPIRED).
    ACTIVE   — issued, not yet verified/consumed.
    CONSUMED — single-use token has been spent; re-verification returns False.
    EXPIRED  — TTL exceeded; set by verifier on detect, not by a background task.

OperationBinding
    Immutable fingerprint of what the token is authorizing:
      principal_id  — who is acting
      subject_state — snapshot of lifecycle state at issuance
      action_type   — abstract action class ("read", "write", "execute", …)
      capability    — Capability.value required, or None (e.g. for "read")
      operation_key — unique per request (context_id from the canonical request)

CapabilityToken
    Immutable at rest; mutable status is tracked in the process-local
    registry inside token_issuer.py.
    status field on the dataclass is the snapshot at issuance (always ACTIVE).
    Authoritative live status comes from the registry, not this field.

Non-negotiable constraints (mirrored from Sprint spec)
------------------------------------------------------
- No HMAC signing (process-local, not distributed).
- No persistence (in-memory only).
- No attenuation (tokens cannot be further restricted).
- Fail-closed: missing/expired/consumed/mismatched → False.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# TokenStatus
# ---------------------------------------------------------------------------

class TokenStatus(str, Enum):
    """
    Lifecycle state of a CapabilityToken.

    The authoritative value is stored in the process-local registry
    (token_issuer._token_registry), NOT in the CapabilityToken dataclass,
    because the dataclass is frozen (immutable).  The status field on
    CapabilityToken is always ACTIVE at issuance; it reflects the snapshot,
    not the live state.
    """

    ACTIVE   = "active"     # Issued, ready for verification.
    CONSUMED = "consumed"   # Spent: single-use rule enforced.
    EXPIRED  = "expired"    # TTL exceeded; set by verifier on detection.


# ---------------------------------------------------------------------------
# OperationBinding
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OperationBinding:
    """
    Immutable fingerprint of what a CapabilityToken is authorized for.

    Built from the CanonicalRequest fields immediately after a
    PolicyDecision.APPROVED is returned.  All fields are plain strings
    (no enum coupling) so the token layer is decoupled from the capability
    and policy enum types.

    Fields
    ------
    principal_id  : Identifier of the acting principal.  Empty string for
                    legacy callers that do not supply one.
    subject_state : Lifecycle state snapshot at issuance (e.g. "active").
                    Snapshot means the state is recorded at the moment the
                    token is issued; it does NOT track subsequent changes.
    action_type   : Abstract action class stamped by build_guarded_request()
                    (e.g. "read", "write", "execute").  Empty string for NL
                    or legacy callers without explicit action_type.
    capability    : Capability.value required for action_type, or None.
                    None means no specific MO capability is needed (e.g. "read").
                    Serialized from required_capability(action_type).value.
    operation_key : Unique fingerprint for this specific operation.
                    Set to context_id (the canonical request identifier),
                    which is unique per call to handle_request().
    delegated_seat_ref : Optional delegated MSO seat reference associated with
                    the authorization context. This is trace/binding metadata;
                    it does not grant execution authority.
    """

    principal_id:  str
    subject_state: str
    action_type:   str
    capability:    Optional[str]
    operation_key: str
    delegated_seat_ref: Optional[str] = None


# ---------------------------------------------------------------------------
# CapabilityToken
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilityToken:
    """
    Immutable capability token issued after PolicyDecision.APPROVED.

    Lifecycle
    ---------
    1. issue_token(binding) → CapabilityToken   (status=ACTIVE in registry)
    2. verify_token(token, binding) → bool       (checks registry + expiry + binding)
    3. consume_token(token)                      (marks CONSUMED in registry)

    Single-use enforcement: after consume_token, verify_token returns False.

    Fields
    ------
    token_id      : UUID string; unique across the process lifetime.
    principal_id  : Copied from OperationBinding at issuance.
    subject_state : Copied from OperationBinding at issuance.
    action_type   : Copied from OperationBinding at issuance.
    capability    : Copied from OperationBinding at issuance.
    operation_key : Copied from OperationBinding at issuance.
    delegated_seat_ref : Copied from OperationBinding at issuance when present.
    issued_at     : time.monotonic() at issuance.  Monotonic: unaffected by
                    wall-clock adjustments.
    expires_at    : issued_at + TTL.  Default TTL = 300 s (5 min).
    status        : Snapshot at issuance (always ACTIVE).
                    Do NOT use this field to check live status; use the registry.
    """

    token_id:      str
    principal_id:  str
    subject_state: str
    action_type:   str
    capability:    Optional[str]
    operation_key: str
    issued_at:     float        # time.monotonic() at issuance
    expires_at:    float        # issued_at + TTL seconds
    status:        TokenStatus  # always ACTIVE at construction time
    delegated_seat_ref: Optional[str] = None
