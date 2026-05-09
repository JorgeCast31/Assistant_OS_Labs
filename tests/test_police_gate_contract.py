import dataclasses
import inspect
from datetime import datetime
from pathlib import Path

import pytest

from assistant_os.police.enforcement import check
from assistant_os.police.gate_models import (
    PoliceDecision,
    PoliceGateRequest,
    PoliceOutcome,
    PoliceReason,
)
from assistant_os.police.models import PoliceEvaluation, PoliceEvaluationType, RiskLevel


ROOT = Path(__file__).resolve().parents[1]
POLICE_INIT = ROOT / "assistant_os" / "police" / "__init__.py"


def _decision(**overrides):
    values = {
        "execution_id": "exec-1",
        "trace_id": "trace-1",
        "outcome": PoliceOutcome.PERMITTED,
        "reason": PoliceReason.ALLOWED,
        "detail": "Allowed by future token-bound gate.",
        "permitted": True,
    }
    values.update(overrides)
    return PoliceDecision(**values)


def test_police_outcome_values_are_exact():
    assert PoliceOutcome.PERMITTED.value == "permitted"
    assert PoliceOutcome.DENIED.value == "denied"
    assert PoliceOutcome.DEFERRED.value == "deferred"


def test_police_outcome_values_are_distinct_from_evaluation_type_values():
    gate_values = {outcome.value for outcome in PoliceOutcome}
    evaluation_values = {outcome.value for outcome in PoliceEvaluationType}

    assert gate_values.isdisjoint(evaluation_values)


def test_police_reason_values_are_exact():
    assert PoliceReason.ALLOWED.value == "allowed"
    assert PoliceReason.TOKEN_MISSING.value == "token_missing"
    assert PoliceReason.TOKEN_INVALID.value == "token_invalid"
    assert PoliceReason.TOKEN_EXPIRED.value == "token_expired"
    assert PoliceReason.TOKEN_ALREADY_CONSUMED.value == "token_already_consumed"
    assert PoliceReason.BINDING_MISMATCH.value == "binding_mismatch"
    assert PoliceReason.BINDING_REF_MISSING.value == "binding_ref_missing"
    assert PoliceReason.PLAN_BINDING_FAILURE.value == "plan_binding_failure"
    assert PoliceReason.GOVERNANCE_REF_MISSING.value == "governance_ref_missing"
    assert PoliceReason.POLICY_DECISION_REF_MISSING.value == "policy_decision_ref_missing"
    assert PoliceReason.CAPABILITY_OUT_OF_SCOPE.value == "capability_out_of_scope"
    assert PoliceReason.TEMPORAL_RESTRICTION.value == "temporal_restriction"
    assert PoliceReason.CONFIRMATION_REQUIRED.value == "confirmation_required"
    assert PoliceReason.GATE_NOT_IMPLEMENTED.value == "gate_not_implemented"


def test_police_decision_is_frozen():
    decision = _decision()

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.permitted = False


def test_police_decision_requires_non_empty_detail():
    with pytest.raises(ValueError, match="detail"):
        _decision(detail="")


def test_police_decision_permitted_true_iff_allow():
    allow = _decision(outcome=PoliceOutcome.PERMITTED, permitted=True)
    deny = _decision(
        outcome=PoliceOutcome.DENIED,
        reason=PoliceReason.TOKEN_INVALID,
        detail="Token is invalid.",
        permitted=False,
    )
    confirmation = _decision(
        outcome=PoliceOutcome.DEFERRED,
        reason=PoliceReason.CONFIRMATION_REQUIRED,
        detail="Confirmation is required.",
        permitted=False,
    )

    assert allow.permitted is True
    assert deny.permitted is False
    assert confirmation.permitted is False


def test_deny_with_permitted_true_is_rejected():
    with pytest.raises(ValueError, match="permitted"):
        _decision(
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.TOKEN_INVALID,
            detail="Token is invalid.",
            permitted=True,
        )


def test_requires_confirmation_with_permitted_true_is_rejected():
    with pytest.raises(ValueError, match="permitted"):
        _decision(
            outcome=PoliceOutcome.DEFERRED,
            reason=PoliceReason.CONFIRMATION_REQUIRED,
            detail="Confirmation is required.",
            permitted=True,
        )


def test_allow_with_permitted_false_is_rejected():
    with pytest.raises(ValueError, match="permitted"):
        _decision(outcome=PoliceOutcome.PERMITTED, permitted=False)


def test_police_gate_request_uses_refs_not_token_objects():
    fields = dataclasses.fields(PoliceGateRequest)
    names = {field.name for field in fields}

    assert "token_ref" in names
    assert "binding_ref" in names
    assert "authorized_plan_ref" in names
    assert "token" not in names
    assert "binding" not in names
    assert "authorized_plan" not in names


def test_police_gate_request_timestamp_is_timezone_aware():
    request = PoliceGateRequest(
        execution_id="exec-1",
        operation_key="op.read",
        token_ref="token-ref-1",
        binding_ref="binding-ref-1",
        authorized_plan_ref="plan-ref-1",
        capability_name="read",
        governance_ref="governance-ref-1",
        policy_decision_ref="policy-ref-1",
        trace_id="trace-1",
    )

    assert isinstance(request.created_at, datetime)
    assert request.created_at.tzinfo is not None
    assert request.created_at.utcoffset() is not None


def test_police_decision_timestamp_is_timezone_aware():
    decision = _decision()

    assert isinstance(decision.checked_at, datetime)
    assert decision.checked_at.tzinfo is not None
    assert decision.checked_at.utcoffset() is not None


def test_police_decision_and_police_evaluation_are_distinct_types():
    assert PoliceDecision is not PoliceEvaluation
    assert not issubclass(PoliceDecision, PoliceEvaluation)
    assert not issubclass(PoliceEvaluation, PoliceDecision)


def test_police_decision_is_not_police_evaluation_instance():
    assert not isinstance(_decision(), PoliceEvaluation)


def test_police_evaluation_is_not_police_decision_instance():
    evaluation = PoliceEvaluation(
        request_id="req-1",
        outcome=PoliceEvaluationType.ALLOW,
        reason="Allowed.",
        risk_level=RiskLevel.LOW,
    )

    assert not isinstance(evaluation, PoliceDecision)


def test_police_init_does_not_export_gate_types():
    source = POLICE_INIT.read_text(encoding="utf-8")

    assert "PoliceDecision" not in source
    assert "PoliceOutcome" not in source
    assert "PoliceReason" not in source
    assert "PoliceGateRequest" not in source
    assert "enforcement" not in source
    assert "harness" not in source
    assert "apply_police_gate" not in source
    assert "check" not in source


def test_police_decision_source_does_not_contain_v0_scope_fields():
    source = inspect.getsource(PoliceDecision)

    assert "allowed_tools" not in source
    assert "denied_tools" not in source
    assert "allowed_environments" not in source
    assert "denied_environments" not in source


def test_enforcement_check_denies_missing_token_ref():
    """Test that check() denies requests with missing token_ref (direct-call bypass)."""
    request = PoliceGateRequest(
        execution_id="exec-1",
        operation_key="op.host_execute",
        token_ref=None,  # Direct-call path lacks token
        binding_ref=None,
        authorized_plan_ref=None,
        capability_name="host.notepad",
        governance_ref=None,
        policy_decision_ref=None,
        trace_id="trace-1",
    )

    decision = check(request)

    assert decision.outcome == PoliceOutcome.DENIED
    assert decision.reason == PoliceReason.TOKEN_MISSING
    assert decision.permitted is False


def test_enforcement_check_denies_missing_governance_ref():
    """Test that check() denies requests with missing governance_ref."""
    request = PoliceGateRequest(
        execution_id="exec-1",
        operation_key="op.host_execute",
        token_ref="token-1",
        binding_ref=None,
        authorized_plan_ref=None,
        capability_name="host.notepad",
        governance_ref=None,  # Missing MSO governance context
        policy_decision_ref=None,
        trace_id="trace-1",
    )

    decision = check(request)

    assert decision.outcome == PoliceOutcome.DENIED
    assert decision.reason == PoliceReason.GOVERNANCE_REF_MISSING
    assert decision.permitted is False


def test_enforcement_check_denies_missing_policy_decision_ref():
    """Test that check() denies requests with missing policy_decision_ref."""
    request = PoliceGateRequest(
        execution_id="exec-1",
        operation_key="op.host_execute",
        token_ref="token-1",
        binding_ref=None,
        authorized_plan_ref=None,
        capability_name="host.notepad",
        governance_ref="governance-1",
        policy_decision_ref=None,  # Missing policy decision context
        trace_id="trace-1",
    )

    decision = check(request)

    assert decision.outcome == PoliceOutcome.DENIED
    assert decision.reason == PoliceReason.POLICY_DECISION_REF_MISSING
    assert decision.permitted is False


def test_enforcement_check_denies_missing_binding_ref():
    """Test that check() denies requests with missing binding_ref."""
    request = PoliceGateRequest(
        execution_id="exec-1",
        operation_key="op.host_execute",
        token_ref="token-1",
        binding_ref=None,  # Missing token-to-action binding
        authorized_plan_ref=None,
        capability_name="host.notepad",
        governance_ref="governance-1",
        policy_decision_ref="policy-1",
        trace_id="trace-1",
    )

    decision = check(request)

    assert decision.outcome == PoliceOutcome.DENIED
    assert decision.reason == PoliceReason.BINDING_REF_MISSING
    assert decision.permitted is False


def test_enforcement_check_permits_complete_authorization_context():
    """Test that check() permits when all authorization context is present."""
    request = PoliceGateRequest(
        execution_id="exec-1",
        operation_key="op.host_execute",
        token_ref="token-1",
        binding_ref="binding-1",
        authorized_plan_ref="plan-1",
        capability_name="host.notepad",
        governance_ref="governance-1",
        policy_decision_ref="policy-1",
        trace_id="trace-1",
    )

    decision = check(request)

    assert decision.outcome == PoliceOutcome.PERMITTED
    assert decision.reason == PoliceReason.ALLOWED
    assert decision.permitted is True
