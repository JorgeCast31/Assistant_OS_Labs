"""
MSO Seat Authority Preparation Tests.

Validates that MSOExecutionProposal maps correctly to AuthorityPreparationRequest
and that all safety invariants are preserved throughout the mapping.

Coverage
--------
1.  MSOExecutionProposal maps to AuthorityPreparationRequest.
2.  Preparation is cognitive_only=True.
3.  Preparation has used_execution=False.
4.  Preparation has execution_allowed=False.
5.  Preparation is not AuthorizedPlan.
6.  Preparation is not PolicyDecision.
7.  Preparation is not PoliceDecision.
8.  Preparation does not issue CapabilityToken.
9.  Preparation does not call PoliceGate.
10. Preparation does not call runner/pipeline.
11. Preparation preserves delegated_seat_ref.
12. Preparation preserves provider metadata.
13. Preparation includes required authority chain.
14. Preparation requires human confirmation.
15. Missing/ambiguous proposal data produces blocked/draft preparation, not execution.
16. CODE/docs proposal maps to CODE/docs authority preparation.

NO live API calls. NO network access. NO real execution.
"""

from __future__ import annotations

import pytest

from assistant_os.mso.authority_preparation import (
    AuthorityPreparationRequest,
    prepare_authority_from_proposal,
)
from assistant_os.mso.execution_proposal import (
    MSOExecutionProposal,
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
    user_intent: str = "Prepare a CODE/docs execution proposal. Do not execute.",
    domain: str = "CODE",
    requested_action: str = "CODE_REVIEW",
    capability_name: str = "code_review",
    capability_scope: tuple[str, ...] = ("code_review",),
    risk_level: str = "low",
    delegated_seat_ref: str | None = "seat-test-ref",
    provider_name: str | None = "anthropic",
    model_name: str | None = "claude-haiku-4-5-20251001",
) -> MSOExecutionProposal:
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


def _prep_from_code_proposal(**kwargs) -> AuthorityPreparationRequest:
    return prepare_authority_from_proposal(_code_proposal(**kwargs))


# ---------------------------------------------------------------------------
# Test 1: MSOExecutionProposal maps to AuthorityPreparationRequest
# ---------------------------------------------------------------------------


class TestProposalMapsToPreparation:
    """prepare_authority_from_proposal returns a correct AuthorityPreparationRequest."""

    def test_returns_authority_preparation_request_instance(self):
        result = _prep_from_code_proposal()
        assert isinstance(result, AuthorityPreparationRequest)

    def test_preparation_has_preparation_id(self):
        result = _prep_from_code_proposal()
        assert result.preparation_id
        assert result.preparation_id.startswith("prep-")

    def test_preparation_id_is_unique(self):
        p = _code_proposal()
        r1 = prepare_authority_from_proposal(p)
        r2 = prepare_authority_from_proposal(p)
        assert r1.preparation_id != r2.preparation_id

    def test_proposal_id_is_copied(self):
        p = _code_proposal()
        r = prepare_authority_from_proposal(p)
        assert r.proposal_id == p.proposal_id

    def test_artifact_type_is_authority_preparation_request(self):
        result = _prep_from_code_proposal()
        assert result.artifact_type == "authority_preparation_request"

    def test_to_dict_contains_required_keys(self):
        result = _prep_from_code_proposal()
        d = result.to_dict()
        required = {
            "artifact_type", "preparation_id", "proposal_id", "user_intent",
            "domain", "requested_action", "capability_name", "capability_scope",
            "requires_human_confirmation", "required_authority_chain",
            "policy_decision_ref", "capability_token_ref", "operation_binding_ref",
            "authorized_plan_ref", "police_decision_ref", "status",
            "execution_allowed", "used_execution", "cognitive_only",
            "pending_authority_steps", "all_authority_pending",
        }
        for key in required:
            assert key in d, f"Missing key in to_dict(): {key!r}"

    def test_type_error_if_not_proposal(self):
        with pytest.raises(TypeError, match="MSOExecutionProposal"):
            prepare_authority_from_proposal("not a proposal")  # type: ignore[arg-type]

    def test_type_error_if_none(self):
        with pytest.raises(TypeError, match="MSOExecutionProposal"):
            prepare_authority_from_proposal(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 2: Preparation is cognitive_only=True
# ---------------------------------------------------------------------------


class TestCognitiveOnlyInvariant:
    """cognitive_only must always be True throughout the preparation path."""

    def test_preparation_cognitive_only_is_true(self):
        result = _prep_from_code_proposal()
        assert result.cognitive_only is True

    def test_to_dict_cognitive_only_true(self):
        result = _prep_from_code_proposal()
        assert result.to_dict()["cognitive_only"] is True

    def test_fallback_proposal_preparation_cognitive_only(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        prep = prepare_authority_from_proposal(fallback)
        assert prep.cognitive_only is True

    def test_direct_construction_cognitive_only_false_raises(self):
        with pytest.raises(ValueError, match="cognitive_only"):
            AuthorityPreparationRequest(cognitive_only=False)

    def test_unknown_domain_preparation_still_cognitive_only(self):
        p = build_execution_proposal(user_intent="unclear request", domain="UNKNOWN")
        prep = prepare_authority_from_proposal(p)
        assert prep.cognitive_only is True


# ---------------------------------------------------------------------------
# Test 3: Preparation has used_execution=False
# ---------------------------------------------------------------------------


class TestUsedExecutionInvariant:
    """used_execution must always be False — no execution occurs during preparation."""

    def test_preparation_used_execution_is_false(self):
        result = _prep_from_code_proposal()
        assert result.used_execution is False

    def test_to_dict_used_execution_false(self):
        result = _prep_from_code_proposal()
        assert result.to_dict()["used_execution"] is False

    def test_fallback_preparation_used_execution_false(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        prep = prepare_authority_from_proposal(fallback)
        assert prep.used_execution is False

    def test_direct_construction_used_execution_true_raises(self):
        with pytest.raises(ValueError, match="used_execution"):
            AuthorityPreparationRequest(used_execution=True)


# ---------------------------------------------------------------------------
# Test 4: Preparation has execution_allowed=False
# ---------------------------------------------------------------------------


class TestExecutionAllowedInvariant:
    """execution_allowed must always be False — preparation does not authorize execution."""

    def test_preparation_execution_allowed_is_false(self):
        result = _prep_from_code_proposal()
        assert result.execution_allowed is False

    def test_to_dict_execution_allowed_false(self):
        result = _prep_from_code_proposal()
        assert result.to_dict()["execution_allowed"] is False

    def test_direct_construction_execution_allowed_true_raises(self):
        with pytest.raises(ValueError, match="execution_allowed"):
            AuthorityPreparationRequest(execution_allowed=True)

    def test_preparation_is_frozen_cannot_mutate_execution_allowed(self):
        prep = _prep_from_code_proposal()
        with pytest.raises((AttributeError, TypeError)):
            prep.execution_allowed = True  # type: ignore[misc]

    def test_fallback_preparation_execution_allowed_false(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        prep = prepare_authority_from_proposal(fallback)
        assert prep.execution_allowed is False


# ---------------------------------------------------------------------------
# Test 5: Preparation is not AuthorizedPlan
# ---------------------------------------------------------------------------


class TestPreparationIsNotAuthorizedPlan:
    """AuthorityPreparationRequest is a cognitive artifact — never an AuthorizedPlan."""

    def test_not_authorized_plan_instance(self):
        result = _prep_from_code_proposal()
        assert not isinstance(result, AuthorizedPlan)

    def test_does_not_have_authorized_plan_hash(self):
        result = _prep_from_code_proposal()
        assert not hasattr(result, "authorized_plan_hash")

    def test_does_not_have_execution_id(self):
        result = _prep_from_code_proposal()
        assert not hasattr(result, "execution_id")

    def test_does_not_have_runtime_profile(self):
        result = _prep_from_code_proposal()
        assert not hasattr(result, "runtime_profile")

    def test_artifact_type_is_not_authorized_plan(self):
        result = _prep_from_code_proposal()
        assert result.artifact_type != "authorized_plan"


# ---------------------------------------------------------------------------
# Test 6: Preparation is not PolicyDecision
# ---------------------------------------------------------------------------


class TestPreparationIsNotPolicyDecision:
    """AuthorityPreparationRequest is not a PolicyDecision."""

    def test_does_not_have_policy_verdict_field(self):
        result = _prep_from_code_proposal()
        assert not hasattr(result, "verdict")

    def test_does_not_have_approved_field(self):
        result = _prep_from_code_proposal()
        assert not hasattr(result, "approved")

    def test_policy_decision_ref_is_none_pending(self):
        result = _prep_from_code_proposal()
        assert result.policy_decision_ref is None

    def test_to_dict_policy_decision_ref_is_none(self):
        result = _prep_from_code_proposal()
        assert result.to_dict()["policy_decision_ref"] is None

    def test_artifact_type_is_not_policy_decision(self):
        result = _prep_from_code_proposal()
        assert result.artifact_type != "policy_decision"


# ---------------------------------------------------------------------------
# Test 7: Preparation is not PoliceDecision
# ---------------------------------------------------------------------------


class TestPreparationIsNotPoliceDecision:
    """AuthorityPreparationRequest is not a PoliceDecision."""

    def test_not_police_decision_instance(self):
        result = _prep_from_code_proposal()
        assert not isinstance(result, PoliceDecision)

    def test_does_not_have_outcome_field(self):
        result = _prep_from_code_proposal()
        assert not hasattr(result, "outcome")

    def test_does_not_have_permitted_field(self):
        result = _prep_from_code_proposal()
        assert not hasattr(result, "permitted")

    def test_police_decision_ref_is_none_pending(self):
        result = _prep_from_code_proposal()
        assert result.police_decision_ref is None

    def test_artifact_type_is_not_police_decision(self):
        result = _prep_from_code_proposal()
        assert result.artifact_type != "police_decision"


# ---------------------------------------------------------------------------
# Test 8: Preparation does not issue CapabilityToken
# ---------------------------------------------------------------------------


class TestPreparationDoesNotIssueToken:
    """prepare_authority_from_proposal never issues a CapabilityToken."""

    def test_capability_token_ref_is_none(self):
        result = _prep_from_code_proposal()
        assert result.capability_token_ref is None

    def test_to_dict_capability_token_ref_is_none(self):
        result = _prep_from_code_proposal()
        assert result.to_dict()["capability_token_ref"] is None

    def test_authority_module_does_not_import_token_issuer(self):
        import assistant_os.mso.authority_preparation as ap_module
        with open(ap_module.__file__) as f:
            source = f.read()
        assert "token_issuer" not in source
        assert "issue_token" not in source

    def test_prepare_does_not_create_token_side_effect(self):
        from assistant_os.capabilities.token_issuer import _token_registry
        before = set(_token_registry.keys())
        _prep_from_code_proposal()
        after = set(_token_registry.keys())
        assert after == before, "prepare_authority_from_proposal must not issue tokens"

    def test_operation_binding_ref_is_none(self):
        result = _prep_from_code_proposal()
        assert result.operation_binding_ref is None


# ---------------------------------------------------------------------------
# Test 9: Preparation does not call PoliceGate
# ---------------------------------------------------------------------------


class TestPreparationDoesNotCallPolice:
    """prepare_authority_from_proposal never calls the PoliceGate."""

    def test_police_decision_ref_is_none(self):
        result = _prep_from_code_proposal()
        assert result.police_decision_ref is None

    def test_authority_module_does_not_import_enforcement(self):
        import assistant_os.mso.authority_preparation as ap_module
        with open(ap_module.__file__) as f:
            source = f.read()
        assert "from ..police" not in source
        assert "import enforcement" not in source
        assert "police.check" not in source

    def test_all_authority_refs_pending(self):
        result = _prep_from_code_proposal()
        assert result.policy_decision_ref is None
        assert result.capability_token_ref is None
        assert result.operation_binding_ref is None
        assert result.authorized_plan_ref is None
        assert result.police_decision_ref is None

    def test_all_authority_pending_property_true(self):
        result = _prep_from_code_proposal()
        assert result.all_authority_pending is True

    def test_pending_authority_steps_lists_all_five(self):
        result = _prep_from_code_proposal()
        steps = result.pending_authority_steps
        assert len(steps) == 5
        assert "PolicyDecision" in steps
        assert "CapabilityToken" in steps
        assert "OperationBinding" in steps
        assert "AuthorizedPlan" in steps
        assert "PoliceGate" in steps


# ---------------------------------------------------------------------------
# Test 10: Preparation does not call runner/pipeline
# ---------------------------------------------------------------------------


class TestPreparationDoesNotCallRunner:
    """prepare_authority_from_proposal never calls a runner or pipeline."""

    def test_authority_module_does_not_import_runners(self):
        import assistant_os.mso.authority_preparation as ap_module
        with open(ap_module.__file__) as f:
            source = f.read()
        assert "from ..runners" not in source
        assert "from ..pipelines" not in source
        assert "import runner_service" not in source

    def test_preparation_has_no_execute_method(self):
        result = _prep_from_code_proposal()
        assert not hasattr(result, "execute")
        assert not hasattr(result, "run")
        assert not hasattr(result, "dispatch")

    def test_prepare_does_not_mutate_external_state(self):
        # Calling prepare multiple times should be idempotent (no side effects)
        p = _code_proposal()
        r1 = prepare_authority_from_proposal(p)
        r2 = prepare_authority_from_proposal(p)
        assert r1.to_dict()["status"] == r2.to_dict()["status"]
        assert r1.to_dict()["execution_allowed"] == r2.to_dict()["execution_allowed"]

    def test_to_dict_has_no_runner_fields(self):
        d = _prep_from_code_proposal().to_dict()
        assert "runner" not in d
        assert "pipeline" not in d
        assert "execution_result" not in d

    def test_used_execution_false_confirms_no_run(self):
        result = _prep_from_code_proposal()
        assert result.used_execution is False


# ---------------------------------------------------------------------------
# Test 11: Preparation preserves delegated_seat_ref
# ---------------------------------------------------------------------------


class TestSeatRefPreserved:
    """Preparation must faithfully carry delegated_seat_ref for traceability."""

    def test_seat_ref_is_copied(self):
        result = _prep_from_code_proposal(delegated_seat_ref="seat-abc-123")
        assert result.delegated_seat_ref == "seat-abc-123"

    def test_seat_ref_none_is_preserved(self):
        result = _prep_from_code_proposal(delegated_seat_ref=None)
        assert result.delegated_seat_ref is None

    def test_seat_ref_in_to_dict(self):
        result = _prep_from_code_proposal(delegated_seat_ref="seat-xyz")
        assert result.to_dict()["delegated_seat_ref"] == "seat-xyz"

    def test_seat_ref_from_fallback_is_preserved(self):
        fallback = build_safe_fallback_proposal(
            user_intent="test",
            delegated_seat_ref="seat-fallback-ref",
        )
        prep = prepare_authority_from_proposal(fallback)
        assert prep.delegated_seat_ref == "seat-fallback-ref"

    def test_seat_ref_different_proposals_preserved_independently(self):
        p1 = build_execution_proposal(user_intent="a", delegated_seat_ref="seat-1")
        p2 = build_execution_proposal(user_intent="b", delegated_seat_ref="seat-2")
        r1 = prepare_authority_from_proposal(p1)
        r2 = prepare_authority_from_proposal(p2)
        assert r1.delegated_seat_ref == "seat-1"
        assert r2.delegated_seat_ref == "seat-2"


# ---------------------------------------------------------------------------
# Test 12: Preparation preserves provider metadata
# ---------------------------------------------------------------------------


class TestProviderMetadataPreserved:
    """Preparation must carry provider_name and model_name for traceability."""

    def test_provider_name_is_copied(self):
        result = _prep_from_code_proposal(provider_name="anthropic")
        assert result.provider_name == "anthropic"

    def test_model_name_is_copied(self):
        result = _prep_from_code_proposal(model_name="claude-haiku-4-5-20251001")
        assert result.model_name == "claude-haiku-4-5-20251001"

    def test_provider_none_preserved(self):
        result = _prep_from_code_proposal(provider_name=None)
        assert result.provider_name is None

    def test_model_none_preserved(self):
        result = _prep_from_code_proposal(model_name=None)
        assert result.model_name is None

    def test_provider_name_in_to_dict(self):
        result = _prep_from_code_proposal(provider_name="llama")
        assert result.to_dict()["provider_name"] == "llama"

    def test_model_name_in_to_dict(self):
        result = _prep_from_code_proposal(model_name="mistral:7b")
        assert result.to_dict()["model_name"] == "mistral:7b"


# ---------------------------------------------------------------------------
# Test 13: Preparation includes required authority chain
# ---------------------------------------------------------------------------


class TestRequiredAuthorityChain:
    """Preparation must declare the canonical authority chain."""

    def test_required_authority_chain_has_five_steps(self):
        result = _prep_from_code_proposal()
        assert len(result.required_authority_chain) == 5

    def test_chain_contains_policy_decision(self):
        result = _prep_from_code_proposal()
        assert "PolicyDecision" in result.required_authority_chain

    def test_chain_contains_capability_token(self):
        result = _prep_from_code_proposal()
        assert "CapabilityToken" in result.required_authority_chain

    def test_chain_contains_operation_binding(self):
        result = _prep_from_code_proposal()
        assert "OperationBinding" in result.required_authority_chain

    def test_chain_contains_authorized_plan(self):
        result = _prep_from_code_proposal()
        assert "AuthorizedPlan" in result.required_authority_chain

    def test_chain_contains_police_gate(self):
        result = _prep_from_code_proposal()
        assert "PoliceGate" in result.required_authority_chain

    def test_chain_order_starts_policy_ends_police(self):
        result = _prep_from_code_proposal()
        chain = list(result.required_authority_chain)
        assert chain[0] == "PolicyDecision"
        assert chain[-1] == "PoliceGate"

    def test_chain_matches_proposal_chain(self):
        p = _code_proposal()
        prep = prepare_authority_from_proposal(p)
        assert set(prep.required_authority_chain) == set(p.next_required_authority)

    def test_to_dict_required_authority_chain_is_list(self):
        d = _prep_from_code_proposal().to_dict()
        assert isinstance(d["required_authority_chain"], list)
        assert len(d["required_authority_chain"]) == 5

    def test_to_dict_pending_authority_steps_lists_all_five(self):
        d = _prep_from_code_proposal().to_dict()
        assert len(d["pending_authority_steps"]) == 5

    def test_to_dict_all_authority_pending_is_true(self):
        d = _prep_from_code_proposal().to_dict()
        assert d["all_authority_pending"] is True


# ---------------------------------------------------------------------------
# Test 14: Preparation requires human confirmation
# ---------------------------------------------------------------------------


class TestHumanConfirmationRequired:
    """requires_human_confirmation must always be True for authority preparations from the seat."""

    def test_preparation_requires_human_confirmation(self):
        result = _prep_from_code_proposal()
        assert result.requires_human_confirmation is True

    def test_to_dict_requires_human_confirmation_true(self):
        result = _prep_from_code_proposal()
        assert result.to_dict()["requires_human_confirmation"] is True

    def test_fallback_preparation_requires_human_confirmation(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        prep = prepare_authority_from_proposal(fallback)
        assert prep.requires_human_confirmation is True

    def test_unknown_domain_preparation_requires_human_confirmation(self):
        p = build_execution_proposal(user_intent="unclear", domain="UNKNOWN")
        prep = prepare_authority_from_proposal(p)
        assert prep.requires_human_confirmation is True

    def test_notes_mention_human_confirmation_for_draft(self):
        result = _prep_from_code_proposal()
        assert "confirmation" in result.notes.lower() or "human" in result.notes.lower()


# ---------------------------------------------------------------------------
# Test 15: Missing/ambiguous data produces blocked/draft, not execution
# ---------------------------------------------------------------------------


class TestMissingDataProducesBlockedNotExecution:
    """When proposal is UNKNOWN domain or missing intent, preparation is blocked."""

    def test_unknown_domain_proposal_produces_blocked_status(self):
        p = build_execution_proposal(user_intent="something unclear", domain="UNKNOWN")
        prep = prepare_authority_from_proposal(p)
        assert prep.status == "blocked"

    def test_empty_user_intent_produces_blocked_status(self):
        p = MSOExecutionProposal(user_intent="", domain="CODE")
        prep = prepare_authority_from_proposal(p)
        assert prep.status == "blocked"

    def test_whitespace_user_intent_produces_blocked_status(self):
        p = MSOExecutionProposal(user_intent="   ", domain="CODE")
        prep = prepare_authority_from_proposal(p)
        assert prep.status == "blocked"

    def test_blocked_preparation_execution_allowed_false(self):
        p = build_execution_proposal(user_intent="unclear", domain="UNKNOWN")
        prep = prepare_authority_from_proposal(p)
        assert prep.execution_allowed is False

    def test_blocked_preparation_cognitive_only_true(self):
        p = build_execution_proposal(user_intent="unclear", domain="UNKNOWN")
        prep = prepare_authority_from_proposal(p)
        assert prep.cognitive_only is True

    def test_fallback_proposal_produces_blocked_preparation(self):
        fallback = build_safe_fallback_proposal(user_intent="test fallback")
        prep = prepare_authority_from_proposal(fallback)
        assert prep.status == "blocked"

    def test_blocked_status_notes_explain_reason(self):
        p = build_execution_proposal(user_intent="unclear", domain="UNKNOWN")
        prep = prepare_authority_from_proposal(p)
        assert "UNKNOWN" in prep.notes or "blocked" in prep.notes.lower()

    def test_code_domain_with_intent_produces_draft_status(self):
        p = _code_proposal()
        prep = prepare_authority_from_proposal(p)
        assert prep.status == "draft"

    def test_draft_status_does_not_execute(self):
        p = _code_proposal()
        prep = prepare_authority_from_proposal(p)
        assert prep.execution_allowed is False
        assert prep.used_execution is False


# ---------------------------------------------------------------------------
# Test 16: CODE/docs proposal maps to CODE/docs authority preparation
# ---------------------------------------------------------------------------


class TestCodeDomainMapping:
    """CODE-domain proposals must produce CODE-domain authority preparations."""

    def test_code_domain_is_preserved(self):
        result = _prep_from_code_proposal(domain="CODE")
        assert result.domain == "CODE"

    def test_code_review_action_is_preserved(self):
        result = _prep_from_code_proposal(requested_action="CODE_REVIEW")
        assert result.requested_action == "CODE_REVIEW"

    def test_code_review_capability_is_preserved(self):
        result = _prep_from_code_proposal(capability_name="code_review")
        assert result.capability_name == "code_review"

    def test_code_review_scope_is_preserved(self):
        result = _prep_from_code_proposal(capability_scope=("code_review",))
        assert "code_review" in result.capability_scope

    def test_user_intent_is_preserved(self):
        intent = "Prepare a CODE/docs execution proposal. Do not execute."
        result = _prep_from_code_proposal(user_intent=intent)
        assert result.user_intent == intent

    def test_code_proposal_preparation_has_draft_status(self):
        result = _prep_from_code_proposal()
        assert result.status == "draft"

    def test_code_proposal_notes_mention_domain(self):
        result = _prep_from_code_proposal()
        assert "CODE" in result.notes

    def test_code_proposal_notes_mention_action(self):
        result = _prep_from_code_proposal(requested_action="CODE_REVIEW")
        assert "CODE_REVIEW" in result.notes

    def test_readme_review_intent_preserved(self):
        intent = "Prepare this proposal for authority review. Do not execute."
        p = build_execution_proposal(
            user_intent=intent,
            domain="CODE",
            requested_action="CODE_REVIEW",
            capability_name="code_review",
        )
        prep = prepare_authority_from_proposal(p)
        assert prep.user_intent == intent
        assert prep.domain == "CODE"
        assert prep.execution_allowed is False

    def test_scope_in_to_dict(self):
        result = _prep_from_code_proposal(capability_scope=("code_review",))
        d = result.to_dict()
        assert "code_review" in d["capability_scope"]


# ---------------------------------------------------------------------------
# Additional: Immutability and traceability
# ---------------------------------------------------------------------------


class TestPreparationImmutability:
    """AuthorityPreparationRequest is frozen."""

    def test_is_frozen_cannot_mutate_status(self):
        prep = _prep_from_code_proposal()
        with pytest.raises((AttributeError, TypeError)):
            prep.status = "ready_for_authority"  # type: ignore[misc]

    def test_is_frozen_cannot_mutate_execution_allowed(self):
        prep = _prep_from_code_proposal()
        with pytest.raises((AttributeError, TypeError)):
            prep.execution_allowed = True  # type: ignore[misc]

    def test_is_frozen_cannot_mutate_police_decision_ref(self):
        prep = _prep_from_code_proposal()
        with pytest.raises((AttributeError, TypeError)):
            prep.police_decision_ref = "some-decision"  # type: ignore[misc]

    def test_two_preparations_from_same_proposal_are_independent(self):
        p = _code_proposal()
        r1 = prepare_authority_from_proposal(p)
        r2 = prepare_authority_from_proposal(p)
        assert r1.preparation_id != r2.preparation_id
        assert r1.proposal_id == r2.proposal_id


class TestPreparationFromVariousProposals:
    """prepare_authority_from_proposal handles a range of proposal types."""

    def test_fin_domain_proposal_maps_correctly(self):
        p = build_execution_proposal(
            user_intent="Prepare FIN expense authority review.",
            domain="FIN",
            requested_action="FIN_EXPENSE",
            capability_name="fin_expense",
        )
        prep = prepare_authority_from_proposal(p)
        assert prep.domain == "FIN"
        assert prep.requested_action == "FIN_EXPENSE"
        assert prep.execution_allowed is False

    def test_work_domain_proposal_maps_correctly(self):
        p = build_execution_proposal(
            user_intent="Prepare WORK task creation.",
            domain="WORK",
            requested_action="WORK_CREATE",
        )
        prep = prepare_authority_from_proposal(p)
        assert prep.domain == "WORK"
        assert prep.status == "draft"

    def test_host_domain_proposal_maps_but_stays_non_executing(self):
        p = build_execution_proposal(
            user_intent="Open an app.",
            domain="HOST",
            requested_action="HOST_OPEN_APP",
        )
        prep = prepare_authority_from_proposal(p)
        assert prep.domain == "HOST"
        assert prep.execution_allowed is False
        assert prep.used_execution is False

    def test_proposal_chain_preserved_in_preparation(self):
        p = _code_proposal()
        prep = prepare_authority_from_proposal(p)
        assert set(prep.required_authority_chain) == set(REQUIRED_AUTHORITY_CHAIN)

    def test_what_authority_still_pending_query(self):
        """Manual prompt: 'What authority is still pending before this can execute?'"""
        p = build_execution_proposal(
            user_intent="What authority is still pending before this can execute?",
            domain="CODE",
            requested_action="CODE_REVIEW",
            capability_name="code_review",
        )
        prep = prepare_authority_from_proposal(p)
        pending = prep.pending_authority_steps
        assert "PolicyDecision" in pending
        assert "CapabilityToken" in pending
        assert "OperationBinding" in pending
        assert "AuthorizedPlan" in pending
        assert "PoliceGate" in pending
        assert prep.execution_allowed is False
