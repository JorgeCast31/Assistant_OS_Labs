"""Regression tests for Police Gate token-bound enforcement (S-POLICE-CORE-03).

S-POLICE-CORE-03 is now implemented. `test_token_missing_denies` and
`test_all_checks_pass_allows` are promoted to normal regression tests.
Remaining tests stay xfail for behaviors not yet fully wired.
"""
import pytest

from assistant_os.police.enforcement import check
from assistant_os.police.gate_models import (
    PoliceGateRequest,
    PoliceOutcome,
    PoliceReason,
)

_XFAIL_PENDING = pytest.mark.xfail(
    reason="Token-bound enforcement.check is not implemented until S-POLICE-CORE-03",
    strict=True,
)


def _request(**overrides):
    values = {
        "execution_id": "exec-1",
        "operation_key": "op.write",
        "token_ref": "token-ref-1",
        "binding_ref": "binding-ref-1",
        "authorized_plan_ref": "plan-ref-1",
        "capability_name": "write",
        "governance_ref": "governance-ref-1",
        "policy_decision_ref": "policy-ref-1",
        "trace_id": "trace-1",
    }
    values.update(overrides)
    return PoliceGateRequest(**values)


def test_token_missing_denies():
    decision = check(_request(token_ref=None))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.TOKEN_MISSING


@_XFAIL_PENDING
def test_invalid_token_denies():
    decision = check(_request(token_ref="invalid-token-ref"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.TOKEN_INVALID


@_XFAIL_PENDING
def test_expired_token_denies():
    decision = check(_request(token_ref="expired-token-ref"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.TOKEN_EXPIRED


@_XFAIL_PENDING
def test_consumed_token_denies():
    decision = check(_request(token_ref="consumed-token-ref"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.TOKEN_ALREADY_CONSUMED


@_XFAIL_PENDING
def test_binding_mismatch_denies():
    decision = check(_request(binding_ref="mismatched-binding-ref"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.BINDING_MISMATCH


@_XFAIL_PENDING
def test_plan_binding_failure_denies():
    decision = check(_request(authorized_plan_ref="unbound-plan-ref"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.PLAN_BINDING_FAILURE


@_XFAIL_PENDING
def test_capability_out_of_scope_denies():
    decision = check(_request(capability_name="admin.write"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.CAPABILITY_OUT_OF_SCOPE


@_XFAIL_PENDING
def test_temporal_restriction_denies_or_requires_confirmation():
    decision = check(_request(active_restriction_refs=("time-window-ref",)))

    assert decision.outcome in {
        PoliceOutcome.DENIED,
        PoliceOutcome.DEFERRED,
    }
    assert decision.reason is PoliceReason.TEMPORAL_RESTRICTION


def test_all_checks_pass_allows():
    decision = check(_request())

    assert decision.outcome is PoliceOutcome.PERMITTED
    assert decision.reason is PoliceReason.ALLOWED
    assert decision.permitted is True


@_XFAIL_PENDING
def test_token_consumed_exactly_once():
    first_decision = check(_request(token_ref="single-use-token-ref"))
    second_decision = check(_request(token_ref="single-use-token-ref"))

    assert first_decision.outcome is PoliceOutcome.PERMITTED
    assert second_decision.outcome is PoliceOutcome.DENIED
    assert second_decision.reason is PoliceReason.TOKEN_ALREADY_CONSUMED
