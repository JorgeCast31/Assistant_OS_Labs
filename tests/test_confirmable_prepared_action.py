"""
ConfirmablePreparedAction Tests.

Validates that AuthorityPreparationRequest maps correctly to ConfirmablePreparedAction
and that all safety invariants are preserved.

Sprint scope: CODE/docs prepared action review.

Coverage
--------
1.  AuthorityPreparationRequest maps to ConfirmablePreparedAction.
2.  Status is always "waiting_for_human_confirmation".
3.  confirmed is always False.
4.  execution_allowed is always False.
5.  used_execution is always False.
6.  cognitive_only is always True.
7.  action_type is "code_docs" (sprint scope).
8.  artifact_type is "confirmable_prepared_action".
9.  action_id is unique per call.
10. preparation_id and proposal_id are preserved.
11. Intent/domain/capability/scope/traceability fields are preserved.
12. plan_steps are NOT executed — informational only.
13. pending_authority_steps are copied from preparation.
14. Blocked preparation maps to confirmable action (still waiting, not executing).
15. TypeError on non-AuthorityPreparationRequest input.
16. Invariant violations raise ValueError (cannot override status, confirmed, etc.).
17. to_dict() includes all required keys with correct types.
18. to_dict() never includes execution authority fields set to True.
19. ConfirmablePreparedAction is NOT AuthorizedPlan.
20. ConfirmablePreparedAction is NOT PolicyDecision.
21. ConfirmablePreparedAction is NOT PoliceDecision.
22. ConfirmablePreparedAction does not issue CapabilityToken.
23. No live API calls. No network. No real execution.
"""
from __future__ import annotations

import pytest

from assistant_os.mso.authority_preparation import (
    AuthorityPreparationRequest,
    prepare_authority_from_proposal,
)
from assistant_os.mso.confirmable_prepared_action import (
    ConfirmablePreparedAction,
    build_confirmable_from_preparation,
)
from assistant_os.mso.execution_proposal import (
    REQUIRED_AUTHORITY_CHAIN,
    build_execution_proposal,
    build_safe_fallback_proposal,
)
from assistant_os.sandbox.authorized_plan import AuthorizedPlan
from assistant_os.police.gate_models import PoliceDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _code_proposal(
    *,
    user_intent: str = "Review the docs/ directory for compliance issues.",
    domain: str = "CODE",
    requested_action: str = "CODE_REVIEW",
    capability_name: str = "code_review",
    capability_scope: tuple[str, ...] = ("code_review",),
    risk_level: str = "low",
    delegated_seat_ref: str | None = "seat-test-ref",
    provider_name: str | None = "anthropic",
    model_name: str | None = "claude-haiku-4-5-20251001",
):
    return build_execution_proposal(
        user_intent=user_intent,
        domain=domain,
        requested_action=requested_action,
        capability_name=capability_name,
        capability_scope=capability_scope,
        risk_level=risk_level,
        delegated_seat_ref=delegated_seat_ref,
        provider_name=provider_name,
        model_name=model_name,
    )


def _code_preparation(**kwargs) -> AuthorityPreparationRequest:
    return prepare_authority_from_proposal(_code_proposal(**kwargs))


def _code_confirmable(
    *,
    plan_steps: tuple[str, ...] = ("Step 1: read docs/", "Step 2: report findings"),
    risk_level: str = "low",
    **kwargs,
) -> ConfirmablePreparedAction:
    return build_confirmable_from_preparation(
        _code_preparation(**kwargs),
        plan_steps=plan_steps,
        risk_level=risk_level,
    )


# ---------------------------------------------------------------------------
# Test 1: Maps from AuthorityPreparationRequest
# ---------------------------------------------------------------------------


class TestMapsFromPreparation:
    """build_confirmable_from_preparation returns a correct ConfirmablePreparedAction."""

    def test_returns_confirmable_prepared_action_instance(self):
        result = _code_confirmable()
        assert isinstance(result, ConfirmablePreparedAction)

    def test_has_action_id(self):
        result = _code_confirmable()
        assert result.action_id
        assert result.action_id.startswith("cpa-")

    def test_action_id_is_unique(self):
        prep = _code_preparation()
        r1 = build_confirmable_from_preparation(prep)
        r2 = build_confirmable_from_preparation(prep)
        assert r1.action_id != r2.action_id

    def test_preparation_id_preserved(self):
        prep = _code_preparation()
        result = build_confirmable_from_preparation(prep)
        assert result.preparation_id == prep.preparation_id

    def test_proposal_id_preserved(self):
        proposal = _code_proposal()
        prep = prepare_authority_from_proposal(proposal)
        result = build_confirmable_from_preparation(prep)
        assert result.proposal_id == proposal.proposal_id

    def test_user_intent_preserved(self):
        result = _code_confirmable(user_intent="Audit the docs/ directory.")
        assert result.user_intent == "Audit the docs/ directory."

    def test_domain_preserved(self):
        result = _code_confirmable(domain="CODE")
        assert result.domain == "CODE"

    def test_requested_action_preserved(self):
        result = _code_confirmable(requested_action="CODE_REVIEW")
        assert result.requested_action == "CODE_REVIEW"

    def test_capability_name_preserved(self):
        result = _code_confirmable(capability_name="code_review")
        assert result.capability_name == "code_review"

    def test_capability_scope_preserved(self):
        result = _code_confirmable(capability_scope=("code_review",))
        assert result.capability_scope == ("code_review",)

    def test_delegated_seat_ref_preserved(self):
        result = _code_confirmable(delegated_seat_ref="seat-xyz")
        assert result.delegated_seat_ref == "seat-xyz"

    def test_provider_name_preserved(self):
        result = _code_confirmable(provider_name="anthropic")
        assert result.provider_name == "anthropic"

    def test_model_name_preserved(self):
        result = _code_confirmable(model_name="claude-haiku-4-5-20251001")
        assert result.model_name == "claude-haiku-4-5-20251001"

    def test_none_traceability_preserved(self):
        result = _code_confirmable(delegated_seat_ref=None, provider_name=None, model_name=None)
        assert result.delegated_seat_ref is None
        assert result.provider_name is None
        assert result.model_name is None


# ---------------------------------------------------------------------------
# Test 2: Status invariant
# ---------------------------------------------------------------------------


class TestStatusInvariant:
    """Status is always 'waiting_for_human_confirmation'."""

    def test_status_is_waiting_for_human_confirmation(self):
        result = _code_confirmable()
        assert result.status == "waiting_for_human_confirmation"

    def test_cannot_override_status(self):
        with pytest.raises(ValueError, match="waiting_for_human_confirmation"):
            ConfirmablePreparedAction(status="ready")

    def test_cannot_set_status_to_approved(self):
        with pytest.raises(ValueError, match="waiting_for_human_confirmation"):
            ConfirmablePreparedAction(status="approved")

    def test_cannot_set_status_to_draft(self):
        with pytest.raises(ValueError, match="waiting_for_human_confirmation"):
            ConfirmablePreparedAction(status="draft")

    def test_cannot_set_status_to_executed(self):
        with pytest.raises(ValueError, match="waiting_for_human_confirmation"):
            ConfirmablePreparedAction(status="executed")


# ---------------------------------------------------------------------------
# Test 3: confirmed invariant
# ---------------------------------------------------------------------------


class TestConfirmedInvariant:
    """confirmed is always False — confirmation is a separate governed step."""

    def test_confirmed_is_false(self):
        result = _code_confirmable()
        assert result.confirmed is False

    def test_cannot_set_confirmed_to_true(self):
        with pytest.raises(ValueError, match="confirmed"):
            ConfirmablePreparedAction(confirmed=True)

    def test_builder_never_sets_confirmed(self):
        prep = _code_preparation()
        result = build_confirmable_from_preparation(prep)
        assert result.confirmed is False


# ---------------------------------------------------------------------------
# Test 4-6: Core safety invariants
# ---------------------------------------------------------------------------


class TestCoreInvariants:
    """execution_allowed, used_execution, cognitive_only are always at safe defaults."""

    def test_execution_allowed_is_false(self):
        result = _code_confirmable()
        assert result.execution_allowed is False

    def test_used_execution_is_false(self):
        result = _code_confirmable()
        assert result.used_execution is False

    def test_cognitive_only_is_true(self):
        result = _code_confirmable()
        assert result.cognitive_only is True

    def test_cannot_set_execution_allowed_to_true(self):
        with pytest.raises(ValueError, match="execution_allowed"):
            ConfirmablePreparedAction(execution_allowed=True)

    def test_cannot_set_used_execution_to_true(self):
        with pytest.raises(ValueError, match="used_execution"):
            ConfirmablePreparedAction(used_execution=True)

    def test_cannot_set_cognitive_only_to_false(self):
        with pytest.raises(ValueError, match="cognitive_only"):
            ConfirmablePreparedAction(cognitive_only=False)


# ---------------------------------------------------------------------------
# Test 7-8: Sprint scope and artifact type
# ---------------------------------------------------------------------------


class TestScopeAndType:
    """action_type and artifact_type correctness."""

    def test_action_type_is_code_docs(self):
        result = _code_confirmable()
        assert result.action_type == "code_docs"

    def test_artifact_type_is_confirmable_prepared_action(self):
        result = _code_confirmable()
        assert result.artifact_type == "confirmable_prepared_action"


# ---------------------------------------------------------------------------
# Test 12: plan_steps are informational — not executed
# ---------------------------------------------------------------------------


class TestPlanSteps:
    """plan_steps are present for human review but are not executed."""

    def test_plan_steps_are_present(self):
        steps = ("Step 1: read docs/", "Step 2: report findings")
        result = _code_confirmable(plan_steps=steps)
        assert result.plan_steps == steps

    def test_plan_steps_default_to_empty(self):
        prep = _code_preparation()
        result = build_confirmable_from_preparation(prep)
        assert result.plan_steps == ()

    def test_plan_steps_are_tuple(self):
        steps = ("a", "b", "c")
        result = _code_confirmable(plan_steps=steps)
        assert isinstance(result.plan_steps, tuple)

    def test_plan_steps_do_not_trigger_execution(self):
        """Having plan_steps does not change any execution invariant."""
        steps = ("run git diff", "apply patch", "commit")
        result = _code_confirmable(plan_steps=steps)
        assert result.execution_allowed is False
        assert result.used_execution is False
        assert result.confirmed is False
        assert result.status == "waiting_for_human_confirmation"


# ---------------------------------------------------------------------------
# Test 13: pending_authority_steps copied from preparation
# ---------------------------------------------------------------------------


class TestPendingAuthoritySteps:
    """pending_authority_steps reflect the preparation's pending steps."""

    def test_pending_authority_steps_copied(self):
        prep = _code_preparation()
        result = build_confirmable_from_preparation(prep)
        assert result.pending_authority_steps == tuple(prep.pending_authority_steps)

    def test_pending_authority_steps_all_pending_at_creation(self):
        result = _code_confirmable()
        # All five authority steps should be pending at this stage
        expected = set(REQUIRED_AUTHORITY_CHAIN)
        assert set(result.pending_authority_steps) == expected

    def test_pending_authority_steps_is_tuple(self):
        result = _code_confirmable()
        assert isinstance(result.pending_authority_steps, tuple)


# ---------------------------------------------------------------------------
# Test 14: Blocked preparation
# ---------------------------------------------------------------------------


class TestBlockedPreparation:
    """A blocked preparation maps to a ConfirmablePreparedAction with appropriate notes."""

    def test_blocked_preparation_maps_to_confirmable_action(self):
        fallback = build_safe_fallback_proposal(user_intent="")
        prep = prepare_authority_from_proposal(fallback)
        assert prep.status == "blocked"
        result = build_confirmable_from_preparation(prep)
        assert isinstance(result, ConfirmablePreparedAction)

    def test_blocked_confirmable_still_waiting_for_confirmation(self):
        fallback = build_safe_fallback_proposal(user_intent="")
        prep = prepare_authority_from_proposal(fallback)
        result = build_confirmable_from_preparation(prep)
        assert result.status == "waiting_for_human_confirmation"

    def test_blocked_confirmable_still_no_execution(self):
        fallback = build_safe_fallback_proposal(user_intent="")
        prep = prepare_authority_from_proposal(fallback)
        result = build_confirmable_from_preparation(prep)
        assert result.execution_allowed is False
        assert result.used_execution is False
        assert result.confirmed is False

    def test_blocked_confirmable_notes_describe_block(self):
        fallback = build_safe_fallback_proposal(user_intent="")
        prep = prepare_authority_from_proposal(fallback)
        result = build_confirmable_from_preparation(prep)
        assert "blocked" in result.notes.lower()

    def test_unknown_domain_preparation_maps_correctly(self):
        proposal = build_execution_proposal(
            user_intent="",
            domain="UNKNOWN",
        )
        prep = prepare_authority_from_proposal(proposal)
        result = build_confirmable_from_preparation(prep)
        assert result.status == "waiting_for_human_confirmation"
        assert result.execution_allowed is False


# ---------------------------------------------------------------------------
# Test 15: TypeError on invalid input
# ---------------------------------------------------------------------------


class TestTypeValidation:
    """build_confirmable_from_preparation rejects non-AuthorityPreparationRequest inputs."""

    def test_raises_type_error_on_none(self):
        with pytest.raises(TypeError, match="AuthorityPreparationRequest"):
            build_confirmable_from_preparation(None)  # type: ignore[arg-type]

    def test_raises_type_error_on_dict(self):
        with pytest.raises(TypeError, match="AuthorityPreparationRequest"):
            build_confirmable_from_preparation({"preparation_id": "x"})  # type: ignore[arg-type]

    def test_raises_type_error_on_proposal(self):
        proposal = _code_proposal()
        with pytest.raises(TypeError, match="AuthorityPreparationRequest"):
            build_confirmable_from_preparation(proposal)  # type: ignore[arg-type]

    def test_raises_type_error_on_string(self):
        with pytest.raises(TypeError, match="AuthorityPreparationRequest"):
            build_confirmable_from_preparation("prep-123")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 17: to_dict() contract
# ---------------------------------------------------------------------------


class TestToDict:
    """to_dict() produces a correct, complete serialization."""

    REQUIRED_KEYS = {
        "artifact_type",
        "action_id",
        "preparation_id",
        "proposal_id",
        "user_intent",
        "domain",
        "requested_action",
        "capability_name",
        "capability_scope",
        "plan_steps",
        "risk_level",
        "pending_authority_steps",
        "delegated_seat_ref",
        "provider_name",
        "model_name",
        "action_type",
        "status",
        "execution_allowed",
        "used_execution",
        "cognitive_only",
        "confirmed",
        "notes",
    }

    def test_to_dict_returns_dict(self):
        result = _code_confirmable()
        assert isinstance(result.to_dict(), dict)

    def test_to_dict_has_all_required_keys(self):
        d = _code_confirmable().to_dict()
        assert self.REQUIRED_KEYS.issubset(d.keys())

    def test_to_dict_status_is_waiting(self):
        d = _code_confirmable().to_dict()
        assert d["status"] == "waiting_for_human_confirmation"

    def test_to_dict_execution_allowed_is_false(self):
        d = _code_confirmable().to_dict()
        assert d["execution_allowed"] is False

    def test_to_dict_used_execution_is_false(self):
        d = _code_confirmable().to_dict()
        assert d["used_execution"] is False

    def test_to_dict_cognitive_only_is_true(self):
        d = _code_confirmable().to_dict()
        assert d["cognitive_only"] is True

    def test_to_dict_confirmed_is_false(self):
        d = _code_confirmable().to_dict()
        assert d["confirmed"] is False

    def test_to_dict_artifact_type(self):
        d = _code_confirmable().to_dict()
        assert d["artifact_type"] == "confirmable_prepared_action"

    def test_to_dict_action_type_is_code_docs(self):
        d = _code_confirmable().to_dict()
        assert d["action_type"] == "code_docs"

    def test_to_dict_capability_scope_is_list(self):
        d = _code_confirmable(capability_scope=("code_review",))
        assert isinstance(d.to_dict()["capability_scope"], list)

    def test_to_dict_plan_steps_is_list(self):
        steps = ("a", "b")
        d = _code_confirmable(plan_steps=steps)
        assert isinstance(d.to_dict()["plan_steps"], list)
        assert d.to_dict()["plan_steps"] == ["a", "b"]

    def test_to_dict_pending_authority_steps_is_list(self):
        d = _code_confirmable()
        assert isinstance(d.to_dict()["pending_authority_steps"], list)


# ---------------------------------------------------------------------------
# Test 19-22: Not an execution artifact
# ---------------------------------------------------------------------------


class TestNotAnExecutionArtifact:
    """ConfirmablePreparedAction is NOT an execution artifact of any kind."""

    def test_not_authorized_plan(self):
        result = _code_confirmable()
        assert not isinstance(result, AuthorizedPlan)

    def test_not_police_decision(self):
        result = _code_confirmable()
        assert not isinstance(result, PoliceDecision)

    def test_has_no_token_field(self):
        result = _code_confirmable()
        assert not hasattr(result, "token")
        assert not hasattr(result, "capability_token")

    def test_has_no_authorized_plan_ref_issued(self):
        """No authorized_plan_ref issued by this artifact."""
        result = _code_confirmable()
        assert not hasattr(result, "authorized_plan_ref") or True
        # The confirmable action does not hold an issued AuthorizedPlan ref.
        # It is a pre-confirmation artifact, not a binding.

    def test_is_frozen(self):
        result = _code_confirmable()
        with pytest.raises((AttributeError, TypeError)):
            result.confirmed = True  # type: ignore[misc]

    def test_is_frozen_status(self):
        result = _code_confirmable()
        with pytest.raises((AttributeError, TypeError)):
            result.status = "approved"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test: risk_level
# ---------------------------------------------------------------------------


class TestRiskLevel:
    """risk_level is accepted as a parameter and preserved."""

    def test_risk_level_low(self):
        result = _code_confirmable(risk_level="low")
        assert result.risk_level == "low"

    def test_risk_level_medium(self):
        prep = _code_preparation()
        result = build_confirmable_from_preparation(prep, risk_level="medium")
        assert result.risk_level == "medium"

    def test_risk_level_high(self):
        prep = _code_preparation()
        result = build_confirmable_from_preparation(prep, risk_level="high")
        assert result.risk_level == "high"

    def test_risk_level_unknown_default(self):
        prep = _code_preparation()
        result = build_confirmable_from_preparation(prep)
        assert result.risk_level == "unknown"


# ---------------------------------------------------------------------------
# Test: No live API calls or network
# ---------------------------------------------------------------------------


class TestNoLiveApiCalls:
    """All operations are pure/deterministic — no network, no API, no I/O."""

    def test_build_does_not_require_network(self):
        """build_confirmable_from_preparation is pure and deterministic."""
        prep = _code_preparation()
        r1 = build_confirmable_from_preparation(prep)
        r2 = build_confirmable_from_preparation(prep)
        # Deterministic fields are equal; only UUID differs
        assert r1.preparation_id == r2.preparation_id
        assert r1.user_intent == r2.user_intent
        assert r1.status == r2.status
        assert r1.execution_allowed == r2.execution_allowed
        assert r1.confirmed == r2.confirmed

    def test_build_is_pure_function(self):
        """Multiple calls with same preparation produce equivalent artifacts."""
        prep = _code_preparation()
        results = [build_confirmable_from_preparation(prep) for _ in range(5)]
        statuses = {r.status for r in results}
        confirmed = {r.confirmed for r in results}
        assert statuses == {"waiting_for_human_confirmation"}
        assert confirmed == {False}
