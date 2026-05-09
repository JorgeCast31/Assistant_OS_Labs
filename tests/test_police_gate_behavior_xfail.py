"""Regression tests for Police Gate token-bound enforcement.

S-POLICE-CORE-03 implemented: token_ref presence, governance_ref, policy_decision_ref,
binding_ref presence, and capability_name presence are validated.

S-POLICE-CORE-04 (this sprint): token lifecycle and binding semantics are validated
against the police-internal token registry.  The following tests are promoted:
  - test_invalid_token_denies
  - test_expired_token_denies
  - test_consumed_token_denies
  - test_binding_mismatch_denies
  - test_token_consumed_exactly_once

Remaining xfails require infrastructure not yet built:
  - CAPABILITY_OUT_OF_SCOPE: no formal schema for capability_name values
  - TEMPORAL_RESTRICTION: no temporal restriction infrastructure
"""
import pytest

from assistant_os.police.enforcement import check
from assistant_os.police.gate_models import (
    PoliceGateRequest,
    PoliceOutcome,
    PoliceReason,
)
from assistant_os.police.token_registry import (
    _reset_for_testing,
    _STATUS_EXPIRED,
    _STATUS_SPENT,
    register_token,
)
from assistant_os.police.authorized_plan_registry import register_authorized_plan_ref

_XFAIL_PENDING = pytest.mark.xfail(
    reason="Requires registry or infrastructure not yet implemented in this sprint",
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


def test_invalid_token_denies():
    # "invalid-token-ref" is not in the police registry → TOKEN_INVALID
    decision = check(_request(token_ref="invalid-token-ref"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.TOKEN_INVALID


def test_expired_token_denies():
    register_token("expired-token-ref", status=_STATUS_EXPIRED, binding_ref="binding-ref-1")

    decision = check(_request(token_ref="expired-token-ref"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.TOKEN_EXPIRED


def test_consumed_token_denies():
    register_token("consumed-token-ref", status=_STATUS_SPENT, binding_ref="binding-ref-1")

    decision = check(_request(token_ref="consumed-token-ref"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.TOKEN_ALREADY_CONSUMED


def test_binding_mismatch_denies():
    # conftest pre-seeds "token-ref-1" with binding_ref="binding-ref-1"
    # request uses a different binding → mismatch detected
    decision = check(_request(binding_ref="mismatched-binding-ref"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.BINDING_MISMATCH


def test_plan_binding_failure_denies():
    decision = check(_request(authorized_plan_ref="unbound-plan-ref"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.PLAN_BINDING_FAILURE


def test_missing_authorized_plan_ref_denies():
    decision = check(_request(authorized_plan_ref=None))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.PLAN_BINDING_FAILURE


def test_authorized_plan_ref_execution_mismatch_denies():
    register_authorized_plan_ref(
        "plan-exec-mismatch",
        execution_id="different-exec",
        token_ref="token-ref-1",
        binding_ref="binding-ref-1",
    )

    decision = check(_request(authorized_plan_ref="plan-exec-mismatch"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.PLAN_BINDING_FAILURE


def test_authorized_plan_ref_binding_mismatch_denies():
    register_authorized_plan_ref(
        "plan-binding-mismatch",
        execution_id="exec-1",
        token_ref="token-ref-1",
        binding_ref="different-binding",
    )

    decision = check(_request(authorized_plan_ref="plan-binding-mismatch"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.PLAN_BINDING_FAILURE


def test_authorized_plan_ref_token_mismatch_denies():
    register_authorized_plan_ref(
        "plan-token-mismatch",
        execution_id="exec-1",
        token_ref="different-token",
        binding_ref="binding-ref-1",
    )

    decision = check(_request(authorized_plan_ref="plan-token-mismatch"))

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


def test_registered_authorized_plan_ref_allows_when_context_is_valid():
    register_token("plan-valid-token", binding_ref="plan-valid-binding")
    register_authorized_plan_ref(
        "plan-valid-ref",
        execution_id="exec-plan-valid",
        token_ref="plan-valid-token",
        binding_ref="plan-valid-binding",
    )

    decision = check(_request(
        execution_id="exec-plan-valid",
        token_ref="plan-valid-token",
        binding_ref="plan-valid-binding",
        authorized_plan_ref="plan-valid-ref",
    ))

    assert decision.outcome is PoliceOutcome.PERMITTED
    assert decision.reason is PoliceReason.ALLOWED
    assert decision.permitted is True


def test_plan_binding_failure_does_not_consume_token():
    register_token("plan-retry-token", binding_ref="plan-retry-binding")

    first_decision = check(_request(
        execution_id="exec-plan-retry",
        token_ref="plan-retry-token",
        binding_ref="plan-retry-binding",
        authorized_plan_ref="missing-plan-ref",
    ))

    register_authorized_plan_ref(
        "plan-retry-ref",
        execution_id="exec-plan-retry",
        token_ref="plan-retry-token",
        binding_ref="plan-retry-binding",
    )
    second_decision = check(_request(
        execution_id="exec-plan-retry",
        token_ref="plan-retry-token",
        binding_ref="plan-retry-binding",
        authorized_plan_ref="plan-retry-ref",
    ))

    assert first_decision.outcome is PoliceOutcome.DENIED
    assert first_decision.reason is PoliceReason.PLAN_BINDING_FAILURE
    assert second_decision.outcome is PoliceOutcome.PERMITTED
    assert second_decision.reason is PoliceReason.ALLOWED


def test_token_consumed_exactly_once():
    # Register a fresh token for single-use enforcement.
    # conftest does not pre-seed "single-use-token-ref".
    register_token("single-use-token-ref", binding_ref="binding-ref-1")
    register_authorized_plan_ref(
        "single-use-plan-ref",
        execution_id="exec-1",
        token_ref="single-use-token-ref",
        binding_ref="binding-ref-1",
    )

    first_decision = check(_request(
        token_ref="single-use-token-ref",
        authorized_plan_ref="single-use-plan-ref",
    ))
    second_decision = check(_request(
        token_ref="single-use-token-ref",
        authorized_plan_ref="single-use-plan-ref",
    ))

    assert first_decision.outcome is PoliceOutcome.PERMITTED
    assert second_decision.outcome is PoliceOutcome.DENIED
    assert second_decision.reason is PoliceReason.TOKEN_ALREADY_CONSUMED
