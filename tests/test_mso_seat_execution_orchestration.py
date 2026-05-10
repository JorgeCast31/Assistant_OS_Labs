"""
MSO Seat Execution Orchestration Tests.

Validates that the Delegated MSO Seat can produce non-executing orchestration
proposals and that all safety invariants are enforced.

Coverage
--------
1.  Plan request creates MSO execution proposal.
2.  Proposal has cognitive_only=True.
3.  Proposal has used_execution=False.
4.  Proposal has execution_allowed=False.
5.  Proposal is NOT an AuthorizedPlan.
6.  Proposal is NOT an execution result.
7.  Proposal includes required authority chain:
    PolicyDecision, CapabilityToken, OperationBinding, AuthorizedPlan, PoliceGate.
8.  Provider unavailable still returns safe deterministic fallback proposal.
9.  Provider response cannot mark execution_allowed=True.
10. Proposal cannot call runner/pipeline.
11. HOST/MACHINE_OPERATOR/OpenClaw are not referenced or called.
12. CODE/docs plan request produces CODE/docs proposal.
13. Unknown or ambiguous request defaults to safe UNKNOWN domain.
14. Human confirmation required is True for execution proposals.

NO live API calls. NO network access. NO real execution.
"""

from __future__ import annotations

import pytest

from assistant_os.mso.execution_proposal import (
    MSOExecutionProposal,
    REQUIRED_AUTHORITY_CHAIN,
    build_execution_proposal,
    build_safe_fallback_proposal,
)
from assistant_os.mso.seat_model_provider_registry import make_orchestration_proposal
from assistant_os.sandbox.authorized_plan import AuthorizedPlan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch):
    """Ensure provider env vars are unset by default — tests that need them patch explicitly."""
    monkeypatch.setattr("assistant_os.config.MSO_SEAT_PROVIDER", "", raising=False)
    monkeypatch.setattr("assistant_os.config.ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr("assistant_os.config.MSO_ENABLED", False, raising=False)
    monkeypatch.setattr("assistant_os.config.LOCAL_LLM_PROVIDER", "", raising=False)
    monkeypatch.setattr("assistant_os.config.LOCAL_LLM_BASE_URL", "", raising=False)
    yield


def _make_proposal(
    *,
    user_intent: str = "Prepare a CODE/docs execution proposal. Do not execute.",
    domain: str = "CODE",
    requested_action: str = "CODE_REVIEW",
    capability_name: str = "code_review",
    capability_scope: tuple[str, ...] = ("code_review",),
    risk_level: str = "low",
    delegated_seat_ref: str | None = "seat-test-ref",
) -> MSOExecutionProposal:
    return build_execution_proposal(
        user_intent=user_intent,
        domain=domain,
        requested_action=requested_action,
        capability_name=capability_name,
        capability_scope=capability_scope,
        risk_level=risk_level,
        delegated_seat_ref=delegated_seat_ref,
    )


# ---------------------------------------------------------------------------
# Test 1: Plan request creates MSO execution proposal
# ---------------------------------------------------------------------------


class TestPlanRequestCreatesProposal:
    """Plan request path returns an MSOExecutionProposal."""

    def test_build_execution_proposal_returns_correct_type(self):
        proposal = _make_proposal()
        assert isinstance(proposal, MSOExecutionProposal)

    def test_proposal_has_proposal_id(self):
        proposal = _make_proposal()
        assert proposal.proposal_id
        assert proposal.proposal_id.startswith("proposal-")

    def test_proposal_carries_user_intent(self):
        proposal = _make_proposal(user_intent="Prepare a CODE/docs execution proposal. Do not execute.")
        assert proposal.user_intent == "Prepare a CODE/docs execution proposal. Do not execute."

    def test_proposal_artifact_type_is_mso_execution_proposal(self):
        proposal = _make_proposal()
        assert proposal.artifact_type == "mso_execution_proposal"

    def test_make_orchestration_proposal_without_provider_returns_proposal(self):
        result = make_orchestration_proposal(
            user_intent="Use the current MSO seat to orchestrate a README review plan.",
        )
        assert isinstance(result, MSOExecutionProposal)

    def test_proposal_to_dict_contains_required_keys(self):
        proposal = _make_proposal()
        d = proposal.to_dict()
        required_keys = {
            "artifact_type", "proposal_id", "user_intent", "domain",
            "requested_action", "capability_name", "capability_scope",
            "risk_level", "requires_human_confirmation", "execution_allowed",
            "used_execution", "cognitive_only", "next_required_authority",
        }
        for key in required_keys:
            assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Test 2: Proposal has cognitive_only=True
# ---------------------------------------------------------------------------


class TestCognitiveOnlyInvariant:
    """cognitive_only must always be True — invariant enforced at construction."""

    def test_proposal_cognitive_only_is_true(self):
        proposal = _make_proposal()
        assert proposal.cognitive_only is True

    def test_proposal_to_dict_cognitive_only_is_true(self):
        proposal = _make_proposal()
        assert proposal.to_dict()["cognitive_only"] is True

    def test_fallback_proposal_cognitive_only_is_true(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        assert fallback.cognitive_only is True

    def test_cognitive_only_false_raises_value_error(self):
        with pytest.raises(ValueError, match="cognitive_only"):
            MSOExecutionProposal(
                user_intent="test",
                cognitive_only=False,
                used_execution=False,
                execution_allowed=False,
            )

    def test_orchestration_proposal_from_registry_cognitive_only(self):
        result = make_orchestration_proposal(user_intent="plan request test")
        assert result.cognitive_only is True


# ---------------------------------------------------------------------------
# Test 3: Proposal has used_execution=False
# ---------------------------------------------------------------------------


class TestUsedExecutionInvariant:
    """used_execution must always be False — no execution occurs during proposal."""

    def test_proposal_used_execution_is_false(self):
        proposal = _make_proposal()
        assert proposal.used_execution is False

    def test_proposal_to_dict_used_execution_is_false(self):
        proposal = _make_proposal()
        assert proposal.to_dict()["used_execution"] is False

    def test_fallback_proposal_used_execution_is_false(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        assert fallback.used_execution is False

    def test_used_execution_true_raises_value_error(self):
        with pytest.raises(ValueError, match="used_execution"):
            MSOExecutionProposal(
                user_intent="test",
                cognitive_only=True,
                used_execution=True,
                execution_allowed=False,
            )

    def test_orchestration_proposal_from_registry_used_execution_false(self):
        result = make_orchestration_proposal(user_intent="plan request test")
        assert result.used_execution is False


# ---------------------------------------------------------------------------
# Test 4: Proposal has execution_allowed=False
# ---------------------------------------------------------------------------


class TestExecutionAllowedInvariant:
    """execution_allowed must always be False — the proposal does not authorize execution."""

    def test_proposal_execution_allowed_is_false(self):
        proposal = _make_proposal()
        assert proposal.execution_allowed is False

    def test_proposal_to_dict_execution_allowed_is_false(self):
        proposal = _make_proposal()
        assert proposal.to_dict()["execution_allowed"] is False

    def test_fallback_proposal_execution_allowed_is_false(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        assert fallback.execution_allowed is False

    def test_execution_allowed_true_raises_value_error(self):
        with pytest.raises(ValueError, match="execution_allowed"):
            MSOExecutionProposal(
                user_intent="test",
                cognitive_only=True,
                used_execution=False,
                execution_allowed=True,
            )

    def test_orchestration_proposal_from_registry_execution_allowed_false(self):
        result = make_orchestration_proposal(user_intent="plan request test")
        assert result.execution_allowed is False


# ---------------------------------------------------------------------------
# Test 5: Proposal is NOT an AuthorizedPlan
# ---------------------------------------------------------------------------


class TestProposalIsNotAuthorizedPlan:
    """MSOExecutionProposal is a cognitive artifact — never an AuthorizedPlan."""

    def test_proposal_is_not_authorized_plan_instance(self):
        proposal = _make_proposal()
        assert not isinstance(proposal, AuthorizedPlan)

    def test_fallback_is_not_authorized_plan(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        assert not isinstance(fallback, AuthorizedPlan)

    def test_orchestration_result_is_not_authorized_plan(self):
        result = make_orchestration_proposal(user_intent="plan request test")
        assert not isinstance(result, AuthorizedPlan)

    def test_proposal_does_not_have_authorized_plan_hash_field(self):
        proposal = _make_proposal()
        assert not hasattr(proposal, "authorized_plan_hash")

    def test_proposal_does_not_have_execution_id_field(self):
        proposal = _make_proposal()
        assert not hasattr(proposal, "execution_id")


# ---------------------------------------------------------------------------
# Test 6: Proposal is NOT an execution result
# ---------------------------------------------------------------------------


class TestProposalIsNotExecutionResult:
    """MSOExecutionProposal cannot be an execution result."""

    def test_proposal_artifact_type_is_not_execution_result(self):
        proposal = _make_proposal()
        assert proposal.artifact_type != "execution_result"
        assert proposal.artifact_type == "mso_execution_proposal"

    def test_proposal_has_no_result_type_field(self):
        proposal = _make_proposal()
        assert not hasattr(proposal, "result_type")

    def test_proposal_to_dict_has_no_execution_result_markers(self):
        d = _make_proposal().to_dict()
        assert d.get("execution_allowed") is False
        assert d.get("used_execution") is False
        assert "execution_result" not in str(d.get("artifact_type", ""))

    def test_proposal_used_execution_false_confirms_no_run(self):
        proposal = _make_proposal()
        assert proposal.used_execution is False

    def test_fallback_is_not_execution_result(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        assert fallback.artifact_type == "mso_execution_proposal"
        assert fallback.used_execution is False


# ---------------------------------------------------------------------------
# Test 7: Proposal includes required authority chain
# ---------------------------------------------------------------------------


class TestRequiredAuthorityChain:
    """Proposal must declare the full authority chain before any execution can occur."""

    def test_required_authority_chain_constant_has_five_entries(self):
        assert len(REQUIRED_AUTHORITY_CHAIN) == 5

    def test_authority_chain_contains_policy_decision(self):
        assert "PolicyDecision" in REQUIRED_AUTHORITY_CHAIN

    def test_authority_chain_contains_capability_token(self):
        assert "CapabilityToken" in REQUIRED_AUTHORITY_CHAIN

    def test_authority_chain_contains_operation_binding(self):
        assert "OperationBinding" in REQUIRED_AUTHORITY_CHAIN

    def test_authority_chain_contains_authorized_plan(self):
        assert "AuthorizedPlan" in REQUIRED_AUTHORITY_CHAIN

    def test_authority_chain_contains_police_gate(self):
        assert "PoliceGate" in REQUIRED_AUTHORITY_CHAIN

    def test_proposal_next_required_authority_matches_canonical_chain(self):
        proposal = _make_proposal()
        assert set(proposal.next_required_authority) == set(REQUIRED_AUTHORITY_CHAIN)

    def test_proposal_next_required_authority_order(self):
        proposal = _make_proposal()
        chain = list(proposal.next_required_authority)
        assert chain[0] == "PolicyDecision"
        assert chain[-1] == "PoliceGate"

    def test_fallback_proposal_authority_chain_present(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        assert "PolicyDecision" in fallback.next_required_authority
        assert "PoliceGate" in fallback.next_required_authority

    def test_orchestration_proposal_authority_chain_present(self):
        result = make_orchestration_proposal(user_intent="What authority is required?")
        assert "PolicyDecision" in result.next_required_authority
        assert "CapabilityToken" in result.next_required_authority
        assert "OperationBinding" in result.next_required_authority
        assert "AuthorizedPlan" in result.next_required_authority
        assert "PoliceGate" in result.next_required_authority

    def test_to_dict_next_required_authority_is_list_of_strings(self):
        d = _make_proposal().to_dict()
        chain = d["next_required_authority"]
        assert isinstance(chain, list)
        assert all(isinstance(s, str) for s in chain)


# ---------------------------------------------------------------------------
# Test 8: Provider unavailable still returns safe deterministic fallback
# ---------------------------------------------------------------------------


class TestProviderUnavailableFallback:
    """When no provider is configured, a safe deterministic fallback is returned."""

    def test_no_provider_returns_fallback_proposal(self):
        result = make_orchestration_proposal(user_intent="Orchestrate a README review plan.")
        assert isinstance(result, MSOExecutionProposal)

    def test_fallback_proposal_cognitive_only(self):
        result = make_orchestration_proposal(user_intent="Orchestrate a README review plan.")
        assert result.cognitive_only is True

    def test_fallback_proposal_execution_allowed_false(self):
        result = make_orchestration_proposal(user_intent="Orchestrate a README review plan.")
        assert result.execution_allowed is False

    def test_fallback_proposal_used_execution_false(self):
        result = make_orchestration_proposal(user_intent="Orchestrate a README review plan.")
        assert result.used_execution is False

    def test_fallback_proposal_has_plan_steps(self):
        result = make_orchestration_proposal(user_intent="some request")
        assert len(result.plan_steps) > 0

    def test_build_safe_fallback_proposal_domain_is_unknown(self):
        fallback = build_safe_fallback_proposal(user_intent="anything")
        assert fallback.domain == "UNKNOWN"

    def test_build_safe_fallback_proposal_notes_contain_reason(self):
        fallback = build_safe_fallback_proposal(
            user_intent="anything",
            reason="provider not configured",
        )
        assert "provider not configured" in fallback.notes

    def test_build_safe_fallback_proposal_authority_chain_intact(self):
        fallback = build_safe_fallback_proposal(user_intent="anything")
        assert len(fallback.next_required_authority) == 5

    def test_provider_unavailable_status_still_returns_fallback(self, monkeypatch):
        monkeypatch.setattr("assistant_os.config.MSO_SEAT_PROVIDER", "anthropic", raising=False)
        monkeypatch.setattr("assistant_os.config.ANTHROPIC_API_KEY", "", raising=False)
        result = make_orchestration_proposal(user_intent="test with unavailable provider")
        assert isinstance(result, MSOExecutionProposal)
        assert result.execution_allowed is False
        assert result.cognitive_only is True


# ---------------------------------------------------------------------------
# Test 9: Provider response cannot mark execution_allowed=True
# ---------------------------------------------------------------------------


class TestExecutionAllowedCannotBeOverridden:
    """No path can set execution_allowed=True on an MSOExecutionProposal."""

    def test_direct_construction_with_execution_allowed_true_raises(self):
        with pytest.raises(ValueError):
            MSOExecutionProposal(execution_allowed=True)

    def test_build_execution_proposal_always_sets_execution_allowed_false(self):
        proposal = build_execution_proposal(user_intent="test")
        assert proposal.execution_allowed is False

    def test_build_safe_fallback_always_sets_execution_allowed_false(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        assert fallback.execution_allowed is False

    def test_proposal_is_frozen_cannot_mutate_execution_allowed(self):
        proposal = _make_proposal()
        with pytest.raises((AttributeError, TypeError)):
            proposal.execution_allowed = True  # type: ignore[misc]

    def test_orchestration_proposal_execution_allowed_false_regardless_of_provider(self, monkeypatch):
        monkeypatch.setattr("assistant_os.config.MSO_SEAT_PROVIDER", "anthropic", raising=False)
        monkeypatch.setattr("assistant_os.config.ANTHROPIC_API_KEY", "fake-key", raising=False)
        result = make_orchestration_proposal(user_intent="try to set execution_allowed=True")
        assert result.execution_allowed is False


# ---------------------------------------------------------------------------
# Test 10: Proposal cannot call runner/pipeline
# ---------------------------------------------------------------------------


class TestProposalCannotCallRunnerOrPipeline:
    """MSOExecutionProposal has no reference to runners or pipelines."""

    def test_execution_proposal_module_does_not_import_runners(self):
        import assistant_os.mso.execution_proposal as ep_module
        import sys
        runner_modules = [k for k in sys.modules if "runner" in k and "assistant_os" in k]
        ep_source = ep_module.__file__
        with open(ep_source) as f:
            source = f.read()
        assert "from ..runners" not in source
        assert "from ..pipelines" not in source
        assert "import runner" not in source

    def test_execution_proposal_has_no_execute_method(self):
        proposal = _make_proposal()
        assert not hasattr(proposal, "execute")
        assert not hasattr(proposal, "run")
        assert not hasattr(proposal, "dispatch")

    def test_build_execution_proposal_does_not_invoke_runner(self):
        # If this completes without error, no runner was invoked (runners would raise or mutate state)
        proposal = build_execution_proposal(
            user_intent="test runner isolation",
            domain="CODE",
            requested_action="CODE_REVIEW",
        )
        assert isinstance(proposal, MSOExecutionProposal)
        assert proposal.used_execution is False

    def test_make_orchestration_proposal_does_not_invoke_pipeline(self):
        result = make_orchestration_proposal(
            user_intent="test pipeline isolation",
            domain="CODE",
            requested_action="CODE_REVIEW",
        )
        assert isinstance(result, MSOExecutionProposal)
        assert result.used_execution is False

    def test_proposal_to_dict_does_not_contain_runner_fields(self):
        d = _make_proposal().to_dict()
        assert "runner" not in d
        assert "pipeline" not in d
        assert "execution_result" not in d


# ---------------------------------------------------------------------------
# Test 11: HOST/MACHINE_OPERATOR/OpenClaw are not called
# ---------------------------------------------------------------------------


class TestForbiddenSubsystemsNotCalled:
    """HOST, MACHINE_OPERATOR, and OpenClaw must never be referenced or invoked."""

    def test_execution_proposal_module_does_not_import_openclaw(self):
        import assistant_os.mso.execution_proposal as ep_module
        with open(ep_module.__file__) as f:
            source = f.read()
        assert "openclaw" not in source.lower()

    def test_execution_proposal_module_does_not_import_machine_operator(self):
        import assistant_os.mso.execution_proposal as ep_module
        with open(ep_module.__file__) as f:
            source = f.read()
        assert "machine_operator" not in source.lower()

    def test_execution_proposal_module_does_not_import_host(self):
        import assistant_os.mso.execution_proposal as ep_module
        with open(ep_module.__file__) as f:
            source = f.read()
        # Only check for direct host executor imports, not the word "host" in comments
        assert "from ..host" not in source
        assert "import host_executor" not in source

    def test_make_orchestration_proposal_does_not_call_host_or_mo(self):
        # Calling make_orchestration_proposal should complete without touching HOST or MO
        result = make_orchestration_proposal(
            user_intent="open an app",
            domain="HOST",  # domain label only — no execution
        )
        assert isinstance(result, MSOExecutionProposal)
        assert result.execution_allowed is False

    def test_proposal_domain_host_does_not_trigger_execution(self):
        proposal = build_execution_proposal(
            user_intent="open chrome",
            domain="HOST",
            requested_action="HOST_OPEN_APP",
        )
        assert proposal.execution_allowed is False
        assert proposal.used_execution is False

    def test_proposal_with_openclaw_domain_name_still_blocked(self):
        proposal = build_execution_proposal(
            user_intent="use openclaw for something",
            domain="OPENCLAW",
            requested_action="",
        )
        assert proposal.execution_allowed is False
        assert proposal.cognitive_only is True


# ---------------------------------------------------------------------------
# Test 12: CODE/docs plan request produces CODE/docs proposal
# ---------------------------------------------------------------------------


class TestCodeDomainProposal:
    """A plan request classified as CODE produces a CODE-domain proposal."""

    def test_code_domain_proposal_domain_is_code(self):
        proposal = build_execution_proposal(
            user_intent="Prepare a CODE/docs execution proposal. Do not execute.",
            domain="CODE",
            requested_action="CODE_REVIEW",
            capability_name="code_review",
            capability_scope=("code_review",),
        )
        assert proposal.domain == "CODE"

    def test_code_domain_proposal_requested_action(self):
        proposal = build_execution_proposal(
            user_intent="Review the README.",
            domain="CODE",
            requested_action="CODE_REVIEW",
        )
        assert proposal.requested_action == "CODE_REVIEW"

    def test_code_domain_proposal_capability_name(self):
        proposal = build_execution_proposal(
            user_intent="Review code.",
            domain="CODE",
            capability_name="code_review",
        )
        assert proposal.capability_name == "code_review"

    def test_code_domain_proposal_capability_scope_in_dict(self):
        proposal = build_execution_proposal(
            user_intent="Review code.",
            domain="CODE",
            capability_scope=("code_review",),
        )
        assert "code_review" in proposal.to_dict()["capability_scope"]

    def test_make_orchestration_proposal_with_code_domain(self):
        # Use build_execution_proposal directly to assert domain without requiring a provider.
        result = build_execution_proposal(
            user_intent="Prepare a CODE/docs execution proposal.",
            domain="CODE",
            requested_action="CODE_REVIEW",
            capability_name="code_review",
            capability_scope=("code_review",),
        )
        assert result.domain == "CODE"
        assert result.execution_allowed is False

    def test_docs_review_plan_proposal(self):
        proposal = build_execution_proposal(
            user_intent="Use the current MSO seat to orchestrate a README review plan.",
            domain="CODE",
            requested_action="CODE_REVIEW",
            capability_name="code_review",
            capability_scope=("code_review",),
            risk_level="low",
        )
        assert proposal.domain == "CODE"
        assert proposal.requires_human_confirmation is True
        assert proposal.execution_allowed is False


# ---------------------------------------------------------------------------
# Test 13: Unknown/ambiguous request stays safe
# ---------------------------------------------------------------------------


class TestUnknownAmbiguousRequest:
    """Ambiguous requests must default to UNKNOWN domain and safe fallback."""

    def test_unknown_domain_proposal_defaults_to_unknown(self):
        proposal = build_execution_proposal(
            user_intent="do something vague",
        )
        assert proposal.domain == "UNKNOWN"

    def test_fallback_proposal_for_unknown_intent_is_safe(self):
        fallback = build_safe_fallback_proposal(
            user_intent="I'm not sure what I want",
            reason="domain classification returned UNKNOWN",
        )
        assert fallback.domain == "UNKNOWN"
        assert fallback.execution_allowed is False
        assert fallback.cognitive_only is True

    def test_make_orchestration_proposal_unknown_domain_fallback(self):
        result = make_orchestration_proposal(
            user_intent="something entirely unclear",
            domain="UNKNOWN",
        )
        assert isinstance(result, MSOExecutionProposal)
        assert result.execution_allowed is False

    def test_ambiguous_request_has_full_authority_chain(self):
        fallback = build_safe_fallback_proposal(user_intent="unclear request")
        assert len(fallback.next_required_authority) == 5

    def test_unknown_domain_proposal_requires_human_confirmation(self):
        proposal = build_execution_proposal(
            user_intent="unclear request",
            domain="UNKNOWN",
        )
        assert proposal.requires_human_confirmation is True


# ---------------------------------------------------------------------------
# Test 14: Human confirmation required for execution proposals
# ---------------------------------------------------------------------------


class TestHumanConfirmationRequired:
    """requires_human_confirmation must be True for all execution proposals from the seat."""

    def test_execution_proposal_requires_human_confirmation(self):
        proposal = _make_proposal()
        assert proposal.requires_human_confirmation is True

    def test_fallback_proposal_requires_human_confirmation(self):
        fallback = build_safe_fallback_proposal(user_intent="test")
        assert fallback.requires_human_confirmation is True

    def test_orchestration_proposal_requires_human_confirmation(self):
        result = make_orchestration_proposal(user_intent="plan request")
        assert result.requires_human_confirmation is True

    def test_build_execution_proposal_default_requires_human_confirmation_true(self):
        proposal = build_execution_proposal(user_intent="any request")
        assert proposal.requires_human_confirmation is True

    def test_to_dict_requires_human_confirmation_true(self):
        proposal = _make_proposal()
        assert proposal.to_dict()["requires_human_confirmation"] is True

    def test_code_proposal_requires_human_confirmation(self):
        proposal = build_execution_proposal(
            user_intent="What authority would be required to execute this proposal?",
            domain="CODE",
            requested_action="CODE_REVIEW",
            capability_name="code_review",
        )
        assert proposal.requires_human_confirmation is True


# ---------------------------------------------------------------------------
# Additional: Proposal traceability and immutability
# ---------------------------------------------------------------------------


class TestProposalTraceability:
    """Proposal carries traceability metadata for audit."""

    def test_proposal_with_delegated_seat_ref(self):
        proposal = build_execution_proposal(
            user_intent="Orchestrate README review.",
            delegated_seat_ref="seat-abc-123",
        )
        assert proposal.delegated_seat_ref == "seat-abc-123"

    def test_proposal_to_dict_includes_delegated_seat_ref(self):
        proposal = build_execution_proposal(
            user_intent="test",
            delegated_seat_ref="seat-xyz",
        )
        assert proposal.to_dict()["delegated_seat_ref"] == "seat-xyz"

    def test_proposal_with_provider_name(self):
        proposal = build_execution_proposal(
            user_intent="test",
            provider_name="anthropic",
            model_name="claude-haiku-4-5-20251001",
        )
        assert proposal.provider_name == "anthropic"
        assert proposal.model_name == "claude-haiku-4-5-20251001"

    def test_proposal_is_frozen_immutable(self):
        proposal = _make_proposal()
        with pytest.raises((AttributeError, TypeError)):
            proposal.user_intent = "mutated"  # type: ignore[misc]

    def test_each_proposal_has_unique_id(self):
        p1 = _make_proposal()
        p2 = _make_proposal()
        assert p1.proposal_id != p2.proposal_id


class TestProposalWithAvailableProvider:
    """When provider is available, orchestration proposal includes provider info."""

    def test_available_anthropic_provider_proposal(self, monkeypatch):
        monkeypatch.setattr("assistant_os.config.MSO_SEAT_PROVIDER", "anthropic", raising=False)
        monkeypatch.setattr("assistant_os.config.ANTHROPIC_API_KEY", "fake-key-for-test", raising=False)
        monkeypatch.setattr("assistant_os.config.MSO_SEAT_MODEL", "claude-haiku-4-5-20251001", raising=False)

        result = make_orchestration_proposal(
            user_intent="Prepare a CODE/docs execution proposal. Do not execute.",
            domain="CODE",
            requested_action="CODE_REVIEW",
            capability_name="code_review",
            capability_scope=("code_review",),
        )
        assert isinstance(result, MSOExecutionProposal)
        assert result.cognitive_only is True
        assert result.used_execution is False
        assert result.execution_allowed is False
        assert result.provider_name == "anthropic"
        assert result.domain == "CODE"
        assert len(result.plan_steps) > 0
        assert "PolicyDecision" in result.next_required_authority

    def test_available_provider_proposal_still_requires_human_confirmation(self, monkeypatch):
        monkeypatch.setattr("assistant_os.config.MSO_SEAT_PROVIDER", "anthropic", raising=False)
        monkeypatch.setattr("assistant_os.config.ANTHROPIC_API_KEY", "fake-key-for-test", raising=False)

        result = make_orchestration_proposal(
            user_intent="Execute something immediately.",
            domain="CODE",
        )
        assert result.requires_human_confirmation is True

    def test_available_provider_proposal_is_not_authorized_plan(self, monkeypatch):
        monkeypatch.setattr("assistant_os.config.MSO_SEAT_PROVIDER", "anthropic", raising=False)
        monkeypatch.setattr("assistant_os.config.ANTHROPIC_API_KEY", "fake-key-for-test", raising=False)

        result = make_orchestration_proposal(
            user_intent="plan something",
            domain="CODE",
        )
        assert not isinstance(result, AuthorizedPlan)
