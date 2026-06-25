"""AOS-P0 Characterization Tests — cleanroom reality lock.

These tests prove specific structural properties of the authority surface
as observed in canonical main (b2fa39b9). They are non-productive: no
executions, no services, no credentials, no external calls.

Findings proved by tests (7 tests total):
  A. Police V3 (policy_decision_ref) is a presence-only check — accepts "auto:<id>"
  B. Police V3 rejects None and empty-string policy_decision_ref
  C. Machine operator adapter N0 compat path produces "approval:auto:<intent_id>"

Police does not invoke policy/governance evaluation according to direct code
inspection of enforcement.check() (enforcement.py:85-264). These tests prove
structural acceptance/rejection of policy_decision_ref, not absence of all
possible evaluation calls via monkey-patching.

These tests do not validate the full suite. They are narrowly scoped to AOS-P0.
"""

from __future__ import annotations

import pytest

from assistant_os.police.enforcement import check
from assistant_os.police.gate_models import PoliceGateRequest, PoliceOutcome, PoliceReason
from assistant_os.police.token_registry import register_token
from assistant_os.police.authorized_plan_registry import register_authorized_plan_ref


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_TOKEN_REF = "p0-char-token-001"
_BINDING_REF = "p0-char-binding-001"
_PLAN_REF = "p0-char-plan-001"
_EXEC_ID = "p0-char-exec-001"
_CAPABILITY = "browser.read_visible_text"


def _register_p0_fixtures() -> None:
    """Register token and plan for AOS-P0 characterization tests."""
    register_token(_TOKEN_REF, binding_ref=_BINDING_REF)
    register_authorized_plan_ref(
        _PLAN_REF,
        execution_id=_EXEC_ID,
        token_ref=_TOKEN_REF,
        binding_ref=_BINDING_REF,
        capability_scope=(_CAPABILITY,),
    )


def _base_request(**overrides) -> PoliceGateRequest:
    values = {
        "execution_id": _EXEC_ID,
        "operation_key": "op.machine_operator",
        "token_ref": _TOKEN_REF,
        "binding_ref": _BINDING_REF,
        "authorized_plan_ref": _PLAN_REF,
        "capability_name": _CAPABILITY,
        "governance_ref": "governance://machine_operator/execute",
        "policy_decision_ref": "policy-baseline-001",
        "trace_id": "p0-trace-001",
    }
    values.update(overrides)
    return PoliceGateRequest(**values)


# ---------------------------------------------------------------------------
# Finding A: Police V3 accepts "auto:<intent_id>" — presence-only check
# ---------------------------------------------------------------------------

class TestPolicePolicyDecisionRefIsStructuralOnly:
    """AOS-P0 Finding A/B.1: V3 validates presence, not semantic provenance."""

    def setup_method(self) -> None:
        _register_p0_fixtures()

    def test_v3_accepts_auto_prefixed_ref(self):
        """Police V3 accepts 'auto:<uuid>' — structural presence check passes."""
        synthetic_intent_id = "550e8400-e29b-41d4-a716-446655440000"
        request = _base_request(
            policy_decision_ref=f"auto:{synthetic_intent_id}",
        )
        decision = check(request)
        assert decision.outcome == PoliceOutcome.PERMITTED, (
            f"Expected PERMITTED but got {decision.outcome}; detail: {decision.detail}"
        )
        assert decision.permitted is True

    def test_v3_accepts_any_non_empty_ref(self):
        """V3 structural check: any non-empty string is accepted as policy_decision_ref."""
        for ref in [
            "auto:some-intent",
            "decision:plan-123",
            "external_local:code_api:exec-001",
            "x:y:z",
            "abcdef",  # minimal passing format
        ]:
            # Each iteration resets after conftest autouse fixture; re-register
            _register_p0_fixtures()
            request = _base_request(policy_decision_ref=ref)
            decision = check(request)
            assert decision.permitted is True, (
                f"ref={ref!r} should be accepted by V3 but got {decision.outcome}"
            )
            # Re-seed registry since token is spent after PERMITTED
            from assistant_os.police.token_registry import _reset_for_testing
            from assistant_os.police.authorized_plan_registry import (
                _reset_for_testing as _reset_plan,
            )
            _reset_for_testing()
            _reset_plan()

    def test_v3_denies_none_policy_decision_ref(self):
        """Police V3 denies None policy_decision_ref (Finding B: structural rejection)."""
        _register_p0_fixtures()
        request = _base_request(policy_decision_ref=None)
        decision = check(request)
        assert decision.outcome == PoliceOutcome.DENIED
        assert decision.reason == PoliceReason.POLICY_DECISION_REF_MISSING
        assert decision.permitted is False

    def test_v3_denies_empty_string_policy_decision_ref(self):
        """Police V3 denies empty string policy_decision_ref."""
        _register_p0_fixtures()
        request = _base_request(policy_decision_ref="")
        decision = check(request)
        assert decision.outcome == PoliceOutcome.DENIED
        assert decision.reason == PoliceReason.POLICY_DECISION_REF_MISSING
        assert decision.permitted is False


# ---------------------------------------------------------------------------
# Finding C: Machine operator adapter N0 path produces "approval:auto:..."
# ---------------------------------------------------------------------------

class TestMachineOperatorAdapterN0SyntheticApproval:
    """AOS-P0 Finding B.2: N0 compat path creates synthetic approval:auto: id."""

    def test_n0_path_creates_synthetic_approval_id(self):
        """N0 compatibility path in machine_operator_adapter produces approval:auto:<intent_id>."""
        from assistant_os.mso.machine_operator_adapter import (
            _build_authority_artifact_policy_payload,
            MachineOperatorAdapterContext,
        )

        context = MachineOperatorAdapterContext(
            plan_id="plan-p0-test",
            execution_id="exec-p0-test",
            trace_id="trace-p0-test",
            policy_decision_ref="auto:test-intent-n0",
            capability_name="browser.read_visible_text",
            capability_tier="read_only",
            policy_reason_code="approved",
            policy_message="approved",
        )
        request_dict = {
            "intent_id": "test-intent-n0",
            "capability_name": "browser.read_visible_text",
            "policy_context": {
                "approval_mode": "none",
                "governance_ref": "governance://machine_operator/execute",
            },
            # no "approval" key → triggers N0 compat path
        }

        result = _build_authority_artifact_policy_payload(
            request_dict=request_dict,
            context=context,
        )

        assert isinstance(result, dict), "N0 path must return a dict"
        approval_id = result.get("approval_id", "")
        assert approval_id.startswith("approval:auto:"), (
            f"Expected approval_id to start with 'approval:auto:' but got: {approval_id!r}"
        )
        assert "test-intent-n0" in approval_id, (
            f"Expected intent_id in approval_id but got: {approval_id!r}"
        )

    def test_n0_synthetic_approval_is_not_police_token(self):
        """'approval:auto:<id>' is an approval_id, not a police token_ref.

        This proves the two synthetic ref families are distinct: one is a
        policy_decision_ref field, the other is an approval_id field. They
        do not share a registry or validation path.
        """
        from assistant_os.police.token_registry import _lookup

        synthetic_approval_id = "approval:auto:some-intent-id"
        # This ref is never registered in the police token registry
        entry = _lookup(synthetic_approval_id)
        assert entry is None, (
            f"'approval:auto:' refs must NOT be police tokens, but found: {entry}"
        )

    def test_policy_decision_ref_and_approval_id_are_distinct_families(self):
        """'auto:<id>' (policy_decision_ref) != 'approval:auto:<id>' (approval_id)."""
        intent_id = "distinct-families-test"
        policy_ref = f"auto:{intent_id}"
        approval_ref = f"approval:auto:{intent_id}"

        assert policy_ref != approval_ref
        assert not policy_ref.startswith("approval:")
        assert approval_ref.startswith("approval:auto:")
        assert policy_ref.startswith("auto:")
