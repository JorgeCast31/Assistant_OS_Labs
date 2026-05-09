"""Police Token-Bound Gate Implementation — S-POLICE-CORE-03"""

from .gate_models import PoliceDecision, PoliceGateRequest, PoliceOutcome, PoliceReason


def check(request: PoliceGateRequest) -> PoliceDecision:
    """Police Gate: validate token and authorization context before execution."""

    # V1: Token reference must be present and non-empty
    if not request.token_ref:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.TOKEN_MISSING,
            detail="Token reference missing. Execution requires valid token.",
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

    # V4: Binding reference should be present (token-to-action binding)
    if not request.binding_ref:
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.BINDING_REF_MISSING,
            detail="Token binding reference missing.",
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

    # All validations passed
    return PoliceDecision(
        execution_id=request.execution_id,
        trace_id=request.trace_id,
        outcome=PoliceOutcome.PERMITTED,
        reason=PoliceReason.ALLOWED,
        detail=f"Token-bound authorization validated. Governance: {request.governance_ref}, Policy: {request.policy_decision_ref}, Capability: {request.capability_name}",
        permitted=True,
    )
