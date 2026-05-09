"""Police Token-Bound Gate Implementation — S-POLICE-CORE-04"""

from .gate_models import PoliceDecision, PoliceGateRequest, PoliceOutcome, PoliceReason
from .token_registry import _lookup, _mark_spent, _STATUS_EXPIRED, _STATUS_SPENT


def check(request: PoliceGateRequest) -> PoliceDecision:
    """Police Gate: validate token and authorization context before authorization."""

    # V1: Token reference must be present and non-empty
    if not request.token_ref:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.TOKEN_MISSING,
            detail="Token reference missing. Authorization requires a valid token.",
            permitted=False,
        )

    # V1.5: Token reference must be registered in the police registry
    _entry = _lookup(request.token_ref)
    if _entry is None:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.TOKEN_INVALID,
            detail="Token reference is not recognized. Token was never registered.",
            permitted=False,
        )

    # V1.6: Token must not be expired
    if _entry["status"] == _STATUS_EXPIRED:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.TOKEN_EXPIRED,
            detail="Token has expired. A new token is required.",
            permitted=False,
        )

    # V1.7: Token must not have been spent (single-use enforcement)
    if _entry["status"] == _STATUS_SPENT:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.TOKEN_ALREADY_CONSUMED,
            detail="Token has already been spent. Single-use tokens cannot be reused.",
            permitted=False,
        )

    # V2: Governance reference must be present (MSO consulted)
    if not request.governance_ref:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.GOVERNANCE_REF_MISSING,
            detail="Governance reference missing. MSO governance context required.",
            permitted=False,
        )

    # V3: Policy decision reference must be present (policy consulted)
    if not request.policy_decision_ref:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.POLICY_DECISION_REF_MISSING,
            detail="Policy decision reference missing. Policy evaluation required.",
            permitted=False,
        )

    # V4: Binding reference must be present (token-to-action binding)
    if not request.binding_ref:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.BINDING_REF_MISSING,
            detail="Token binding reference missing.",
            permitted=False,
        )

    # V4.5: Binding reference must match the registered binding constraint
    _expected_binding = _entry["binding_ref"]
    if _expected_binding is not None and request.binding_ref != _expected_binding:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.BINDING_MISMATCH,
            detail=(
                f"Token binding mismatch. "
                f"Request binding '{request.binding_ref}' does not match "
                f"the registered binding for this token."
            ),
            permitted=False,
        )

    # V5: Capability name must be present
    if not request.capability_name:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.CAPABILITY_OUT_OF_SCOPE,
            detail="Capability name missing.",
            permitted=False,
        )

    # All validations passed — mark token as spent (single-use enforcement)
    _mark_spent(request.token_ref)

    return PoliceDecision(
        execution_id=request.execution_id,
        trace_id=request.trace_id,
        outcome=PoliceOutcome.PERMITTED,
        reason=PoliceReason.ALLOWED,
        detail=(
            f"Token-bound authorization validated. "
            f"Governance: {request.governance_ref}, "
            f"Policy: {request.policy_decision_ref}, "
            f"Capability: {request.capability_name}"
        ),
        permitted=True,
    )
