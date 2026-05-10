"""Police Token-Bound Gate Implementation — S-POLICE-CORE-04"""

from collections.abc import Callable

from .authorized_plan_registry import _lookup as _lookup_authorized_plan
from .gate_models import PoliceDecision, PoliceGateRequest, PoliceOutcome, PoliceReason
from .token_registry import _lookup, _mark_spent, _STATUS_EXPIRED, _STATUS_SPENT

_DelegatedSeatValidator = Callable[[str, str | None], tuple[bool, str]]
_delegated_seat_validator: _DelegatedSeatValidator | None = None


def configure_delegated_seat_validator(
    validator: _DelegatedSeatValidator | None,
) -> None:
    """Install the process-local delegated-seat validator used by the gate."""
    global _delegated_seat_validator
    _delegated_seat_validator = validator


def _reset_delegated_seat_validator_for_testing() -> None:
    """Clear the delegated-seat validator between tests."""
    configure_delegated_seat_validator(None)


def _plan_binding_denied(request: PoliceGateRequest, detail: str) -> PoliceDecision:
    return PoliceDecision(
        execution_id=request.execution_id,
        trace_id=request.trace_id,
        outcome=PoliceOutcome.DENIED,
        reason=PoliceReason.PLAN_BINDING_FAILURE,
        detail=detail,
        permitted=False,
    )


def _delegated_seat_denied(request: PoliceGateRequest, detail: str) -> PoliceDecision:
    return PoliceDecision(
        execution_id=request.execution_id,
        trace_id=request.trace_id,
        outcome=PoliceOutcome.DENIED,
        reason=PoliceReason.DELEGATED_SEAT_INVALID,
        detail=detail,
        permitted=False,
    )


def _capability_denied(request: PoliceGateRequest, detail: str) -> PoliceDecision:
    return PoliceDecision(
        execution_id=request.execution_id,
        trace_id=request.trace_id,
        outcome=PoliceOutcome.DENIED,
        reason=PoliceReason.CAPABILITY_OUT_OF_SCOPE,
        detail=detail,
        permitted=False,
    )


def _validate_delegated_seat(request: PoliceGateRequest) -> PoliceDecision | None:
    seat_ref = request.delegated_seat_ref
    if not seat_ref:
        if request.delegated_seat_required:
            return _delegated_seat_denied(
                request,
                "Delegated seat reference missing. This request requires seat context.",
            )
        return None

    if _delegated_seat_validator is None:
        return _delegated_seat_denied(
            request,
            "Delegated seat reference cannot be validated by this process.",
        )

    is_valid, detail = _delegated_seat_validator(
        seat_ref,
        request.delegated_seat_action,
    )
    if not is_valid:
        return _delegated_seat_denied(request, detail)

    return None


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

    # V4.6: Plan reference must be known and bound to this request.
    if not request.authorized_plan_ref:
        return _plan_binding_denied(
            request,
            "Authorized plan reference missing. Plan binding is required.",
        )

    _plan_entry = _lookup_authorized_plan(request.authorized_plan_ref)
    if _plan_entry is None:
        return _plan_binding_denied(
            request,
            "Authorized plan reference is not recognized. Plan was never registered.",
        )

    if _plan_entry.get("status") != "active":
        return _plan_binding_denied(
            request,
            "Authorized plan reference is not active.",
        )

    if _plan_entry.get("execution_id") != request.execution_id:
        return _plan_binding_denied(
            request,
            "Authorized plan execution_id does not match this request.",
        )

    if _plan_entry.get("token_ref") != request.token_ref:
        return _plan_binding_denied(
            request,
            "Authorized plan token_ref does not match this request.",
        )

    if _plan_entry.get("binding_ref") != request.binding_ref:
        return _plan_binding_denied(
            request,
            "Authorized plan binding_ref does not match this request.",
        )

    seat_decision = _validate_delegated_seat(request)
    if seat_decision is not None:
        return seat_decision

    plan_seat_ref = _plan_entry.get("delegated_seat_ref")
    if request.delegated_seat_ref and plan_seat_ref != request.delegated_seat_ref:
        return _plan_binding_denied(
            request,
            "Authorized plan delegated_seat_ref does not match this request.",
        )

    # V5: Capability name must be present and included in the bound scope.
    capability_name = request.capability_name.strip() if isinstance(request.capability_name, str) else ""
    if not capability_name:
        return _capability_denied(request, "Capability name missing.")

    capability_scope = _plan_entry.get("capability_scope")
    if not isinstance(capability_scope, tuple) or not capability_scope:
        return _capability_denied(
            request,
            "Authorized plan has no Police-visible capability scope.",
        )

    if capability_name not in capability_scope:
        return _capability_denied(
            request,
            "Capability is outside the authorized plan scope.",
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
