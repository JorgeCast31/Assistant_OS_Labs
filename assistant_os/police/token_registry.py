"""Police-internal token registry — S-POLICE-CORE-04.

Minimal process-local registry for Police Gate token lifecycle validation.
Isolated from the capability token layer (authority isolation contract forbids
police files from importing assistant_os.capabilities).

Police gate works with string refs (token_ref), not actual token objects.
This registry maps token_ref → {status, binding_ref} so the gate can validate:
  - Token is known (not TOKEN_INVALID)
  - Token has not expired (TOKEN_EXPIRED)
  - Token has not been spent / single-use (TOKEN_ALREADY_CONSUMED)
  - Token binding matches expected binding (BINDING_MISMATCH)

Status values
-------------
_STATUS_ACTIVE  = "active"   Ready for validation.
_STATUS_EXPIRED = "expired"  TTL exceeded; set externally or by the issuer.
_STATUS_SPENT   = "spent"    Single-use consumed; set by the gate on PERMITTED.

Non-negotiable constraints
--------------------------
- No I/O — process memory only.
- No imports from assistant_os.capabilities, sandbox, policy, mso, or core.
- Fail-closed: unknown token_ref → TOKEN_INVALID (caller handles the denial).
"""
from __future__ import annotations

_STATUS_ACTIVE  = "active"
_STATUS_EXPIRED = "expired"
_STATUS_SPENT   = "spent"

# token_ref (str) → {"status": str, "binding_ref": str | None}
_registry: dict[str, dict[str, str | None]] = {}


def register_token(
    token_ref: str,
    *,
    status: str = _STATUS_ACTIVE,
    binding_ref: str | None = None,
) -> None:
    """Register a token reference in the police registry.

    Parameters
    ----------
    token_ref   : Opaque string reference identifying the token.
    status      : Initial lifecycle status (default: ACTIVE).
    binding_ref : Expected binding reference for this token, or None for
                  unconstrained (any binding_ref in the request is accepted).
    """
    _registry[token_ref] = {"status": status, "binding_ref": binding_ref}


def _lookup(token_ref: str) -> dict[str, str | None] | None:
    """Return the registry entry for token_ref, or None if unknown.

    None signals that the token ref was never registered → TOKEN_INVALID.
    """
    return _registry.get(token_ref)


def _mark_spent(token_ref: str) -> None:
    """Mark a registered token as spent (single-use enforcement).

    Called by the gate immediately after issuing a PERMITTED decision.
    Subsequent calls with the same token_ref will see status=_STATUS_SPENT
    and be denied with TOKEN_ALREADY_CONSUMED.

    No-op if token_ref is not in the registry.
    """
    entry = _registry.get(token_ref)
    if entry is not None:
        _registry[token_ref] = {"status": _STATUS_SPENT, "binding_ref": entry["binding_ref"]}


def _reset_for_testing() -> None:
    """Clear all registry entries.

    FOR TEST USE ONLY — provides isolation between test cases.
    Never call from production code.
    """
    _registry.clear()
