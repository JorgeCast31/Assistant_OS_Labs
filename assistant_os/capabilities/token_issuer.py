"""
Capability Token Issuer — Sprint 12.

Single entry point for creating CapabilityTokens.  Also owns the
process-local token registry that tracks live status.

Design
------
issue_token(binding, ttl_seconds) → CapabilityToken

Called by the orchestrator immediately after PolicyDecision.APPROVED.
The token is registered in _token_registry as ACTIVE at issuance.

Process-local registry
----------------------
_token_registry: dict[str, str]
    Maps token_id → current status value (one of TokenStatus values).
    This is the authoritative live state; the status field on the
    CapabilityToken dataclass is only a snapshot at issuance.

    Shared with token_verifier.py, which imports it to check and update
    status (consume, expire).

Non-negotiable constraints
--------------------------
- No HMAC signing (plain UUIDs).
- No persistence (process memory only).
- No attenuation (tokens are not further restricted after issuance).
- Fail-closed: a token not in the registry is treated as denied.
"""

from __future__ import annotations

import time
import uuid

from .token_models import CapabilityToken, OperationBinding, TokenStatus


# ---------------------------------------------------------------------------
# Process-local registry
# ---------------------------------------------------------------------------

# token_id (str) → current TokenStatus.value (str)
# Authoritative live state for all issued tokens.
# Imported by token_verifier to read and update status.
_token_registry: dict[str, str] = {}


# ---------------------------------------------------------------------------
# issue_token
# ---------------------------------------------------------------------------

def issue_token(
    binding: OperationBinding,
    ttl_seconds: float = 300.0,
) -> CapabilityToken:
    """
    Issue a CapabilityToken for the given OperationBinding.

    Called only after PolicyDecision.APPROVED — the orchestrator ensures
    this invariant.  The token is registered as ACTIVE immediately.

    Parameters
    ----------
    binding     : OperationBinding — immutable fingerprint of the authorized
                  operation (principal, state, action_type, capability, key).
    ttl_seconds : Token time-to-live in seconds.  Default 300 s (5 min).
                  The token is invalid (verify_token → False) after expiry.

    Returns
    -------
    CapabilityToken — frozen dataclass.  status field is always ACTIVE at
    construction.  Authoritative live status is in _token_registry.

    Side effects
    ------------
    Registers the new token_id → ACTIVE in _token_registry.
    """
    now = time.monotonic()
    token = CapabilityToken(
        token_id=str(uuid.uuid4()),
        principal_id=binding.principal_id,
        subject_state=binding.subject_state,
        action_type=binding.action_type,
        capability=binding.capability,
        operation_key=binding.operation_key,
        issued_at=now,
        expires_at=now + ttl_seconds,
        status=TokenStatus.ACTIVE,
    )
    _token_registry[token.token_id] = TokenStatus.ACTIVE.value
    return token


# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------

def _reset_registry() -> None:
    """
    Clear the token registry.

    FOR TEST USE ONLY — provides isolation between test cases.
    Never call from production code.
    """
    _token_registry.clear()
