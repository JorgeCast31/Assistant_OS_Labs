"""
Capability Token Verifier — Sprint 12.

Two entry points:
  verify_token(token, binding) → bool
  consume_token(token)         → None

Verification is fail-closed: any deviation from the happy path returns False.
The function is pure with respect to its inputs (same inputs → same output)
except for the wall-clock / monotonic check and the registry read.

Verification steps (in order)
------------------------------
  1. Registry presence and status:
       token_id must be in _token_registry with status == ACTIVE.
       Missing → denied (never issued, or registry was cleared for testing).
       CONSUMED → denied (single-use enforcement).
       EXPIRED  → denied (already expired by a prior call to verify_token).

  2. Expiry:
       time.monotonic() > token.expires_at → expired.
       Side-effect: registry status is updated to EXPIRED.

  3. Binding match:
       All five binding fields must match exactly:
         principal_id, subject_state, action_type, capability, operation_key.
       delegated_seat_ref must also match when present.
       Any mismatch → denied.

consume_token
-------------
Marks the token as CONSUMED in the registry.  After this call, a subsequent
verify_token on the same token returns False (step 1 catches CONSUMED).

Non-negotiable constraints
--------------------------
- Fail-closed: any check that cannot be satisfied → False.
- No LLM involvement.
- No I/O (registry is process memory).
"""

from __future__ import annotations

import time

from .token_models import CapabilityToken, OperationBinding, TokenStatus


# ---------------------------------------------------------------------------
# verify_token
# ---------------------------------------------------------------------------

def verify_token(token: CapabilityToken, binding: OperationBinding) -> bool:
    """
    Verify a capability token against an OperationBinding.

    Returns True iff ALL of the following hold:
      1. token_id is registered with status ACTIVE (not missing/consumed/expired).
      2. Current monotonic time has not exceeded token.expires_at.
      3. All binding fields (principal_id, subject_state, action_type,
         capability, operation_key) match the token fields exactly.

    Returns False immediately on the first failing check (fail-closed).
    On expiry detection (step 2), the registry is updated to EXPIRED.

    Parameters
    ----------
    token   : CapabilityToken — the token to verify.
    binding : OperationBinding — the expected binding for the current operation.

    Returns
    -------
    bool — True if verification passes; False otherwise.
    """
    # Lazy import to avoid circular dependency at module load time.
    from .token_issuer import _token_registry

    # ── Step 1: registry status ───────────────────────────────────────────
    stored_status = _token_registry.get(token.token_id)
    if stored_status != TokenStatus.ACTIVE.value:
        # Missing (never issued, or _reset_registry() cleared it),
        # CONSUMED (already spent), or EXPIRED (prior call detected expiry).
        return False

    # ── Step 2: expiry ────────────────────────────────────────────────────
    if time.monotonic() > token.expires_at:
        # Mark expired so subsequent calls hit step 1 immediately.
        _token_registry[token.token_id] = TokenStatus.EXPIRED.value
        return False

    # ── Step 3: binding match ─────────────────────────────────────────────
    if (
        token.principal_id  != binding.principal_id
        or token.subject_state != binding.subject_state
        or token.action_type   != binding.action_type
        or token.capability    != binding.capability
        or token.operation_key != binding.operation_key
        or token.delegated_seat_ref != binding.delegated_seat_ref
    ):
        return False

    return True


# ---------------------------------------------------------------------------
# consume_token
# ---------------------------------------------------------------------------

def consume_token(token: CapabilityToken) -> None:
    """
    Mark a capability token as consumed (single-use enforcement).

    After this call, verify_token returns False for the same token_id
    because step 1 sees CONSUMED, not ACTIVE.

    Parameters
    ----------
    token : CapabilityToken — the token to consume.

    Side effects
    ------------
    Updates _token_registry[token.token_id] = "consumed".
    No-op if the token_id is not in the registry (already consumed or expired).
    """
    from .token_issuer import _token_registry
    _token_registry[token.token_id] = TokenStatus.CONSUMED.value
