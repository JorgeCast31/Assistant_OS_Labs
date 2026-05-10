"""
Tests for MSO Seat Model Provider contracts.

Validates:
1. Provider registry accepts supported provider names
2. Unknown provider name is rejected or marked invalid
3. Anthropic provider can be configured via metadata without exposing secrets
4. Local Llama provider can be configured with local endpoint/model metadata
5. OpenAI/GPT provider is represented honestly (not_implemented)
6. Gemma provider is represented honestly (not_implemented)
7. Provider response is cognitive_only and non_executing
8. Provider cannot bypass Police/AuthorizedPlan
9. Delegated MSO Seat can carry provider metadata
10. Provider unavailable does not grant execution

NO live API calls in any test. No network access.
"""

import pytest

from assistant_os.mso.seat_model_provider import (
    MSOSeatModelProvider,
    ModelProviderName,
    ModelProviderResponse,
    SUPPORTED_PROVIDER_NAMES,
    make_unavailable_response,
    make_cognitive_response,
    validate_provider_name,
)


# ---------------------------------------------------------------------------
# Test 1: Supported provider names
# ---------------------------------------------------------------------------


class TestSupportedProviderNames:
    """Provider registry accepts all four supported names."""

    def test_supported_names_contain_anthropic(self):
        assert "anthropic" in SUPPORTED_PROVIDER_NAMES

    def test_supported_names_contain_openai(self):
        assert "openai" in SUPPORTED_PROVIDER_NAMES

    def test_supported_names_contain_llama(self):
        assert "llama" in SUPPORTED_PROVIDER_NAMES

    def test_supported_names_contain_gemma(self):
        assert "gemma" in SUPPORTED_PROVIDER_NAMES

    def test_exactly_four_supported_names(self):
        assert len(SUPPORTED_PROVIDER_NAMES) == 4

    def test_model_provider_name_enum_anthropic(self):
        assert ModelProviderName("anthropic") == ModelProviderName.ANTHROPIC

    def test_model_provider_name_enum_openai(self):
        assert ModelProviderName("openai") == ModelProviderName.OPENAI

    def test_model_provider_name_enum_llama(self):
        assert ModelProviderName("llama") == ModelProviderName.LLAMA

    def test_model_provider_name_enum_gemma(self):
        assert ModelProviderName("gemma") == ModelProviderName.GEMMA


# ---------------------------------------------------------------------------
# Test 2: Unknown provider name is rejected
# ---------------------------------------------------------------------------


class TestUnknownProviderName:
    """Unknown provider names must be rejected — fail-closed."""

    def test_validate_unknown_name_fails(self):
        ok, result = validate_provider_name("mistral")
        assert ok is False
        assert result is None

    def test_validate_empty_name_fails(self):
        ok, result = validate_provider_name("")
        assert ok is False
        assert result is None

    def test_validate_openclaw_rejected(self):
        ok, result = validate_provider_name("openclaw")
        assert ok is False
        assert result is None

    def test_validate_host_rejected(self):
        ok, result = validate_provider_name("host")
        assert ok is False
        assert result is None

    def test_validate_machine_operator_rejected(self):
        ok, result = validate_provider_name("machine_operator")
        assert ok is False
        assert result is None

    def test_validate_valid_name_anthropic(self):
        ok, result = validate_provider_name("anthropic")
        assert ok is True
        assert result == ModelProviderName.ANTHROPIC

    def test_validate_valid_name_case_insensitive(self):
        ok, result = validate_provider_name("LLAMA")
        assert ok is True
        assert result == ModelProviderName.LLAMA


# ---------------------------------------------------------------------------
# Test 3: Anthropic provider metadata (no secrets)
# ---------------------------------------------------------------------------


class TestAnthropicProviderMetadata:
    """Anthropic provider can be described without exposing API keys."""

    def test_anthropic_provider_dataclass_no_key(self):
        """Can describe Anthropic provider without touching the real API key."""
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="api_key_missing",
            local_or_remote="remote",
            supports_chat=True,
            supports_plan_only=True,
            safety_notes=("cognitive_only", "no_direct_execution"),
            config_source="env",
        )
        assert provider.provider_name == ModelProviderName.ANTHROPIC
        assert provider.availability == "api_key_missing"
        assert provider.is_available is False
        assert provider.local_or_remote == "remote"

    def test_anthropic_provider_available_state(self):
        """Anthropic provider with api_key_missing is not available."""
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-sonnet-4-6",
            availability="available",
            local_or_remote="remote",
        )
        assert provider.is_available is True

    def test_anthropic_to_dict_does_not_include_api_key(self):
        """to_dict() never includes the API key."""
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="available",
            local_or_remote="remote",
        )
        d = provider.to_dict()
        assert "api_key" not in d
        assert "ANTHROPIC_API_KEY" not in d
        assert d["provider_name"] == "anthropic"
        assert d["cognitive_only"] is True
        assert d["used_execution"] is False

    def test_anthropic_to_dict_safety_invariants(self):
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="available",
            local_or_remote="remote",
        )
        d = provider.to_dict()
        assert d["used_execution"] is False
        assert d["cognitive_only"] is True


# ---------------------------------------------------------------------------
# Test 4: Local Llama provider metadata
# ---------------------------------------------------------------------------


class TestLlamaProviderMetadata:
    """Local Llama provider described with local endpoint metadata."""

    def test_llama_provider_available(self):
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.LLAMA,
            model_name="mistral:7b",
            availability="available",
            local_or_remote="local",
            supports_chat=True,
            supports_plan_only=True,
            safety_notes=("cognitive_only", "local_endpoint"),
            config_source="env",
        )
        assert provider.is_available is True
        assert provider.local_or_remote == "local"

    def test_llama_provider_not_configured(self):
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.LLAMA,
            model_name="",
            availability="not_configured",
            local_or_remote="local",
        )
        assert provider.is_available is False
        assert provider.availability == "not_configured"

    def test_llama_provider_local_endpoint_missing(self):
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.LLAMA,
            model_name="mistral:7b",
            availability="local_endpoint_missing",
            local_or_remote="local",
        )
        assert provider.is_available is False

    def test_llama_no_network_call_needed_for_metadata(self):
        """Provider metadata can be described without making any network call."""
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.LLAMA,
            model_name="neural-chat:7b",
            availability="available",
            local_or_remote="local",
        )
        d = provider.to_dict()
        assert d["provider_name"] == "llama"
        assert d["local_or_remote"] == "local"
        assert d["is_available"] is True


# ---------------------------------------------------------------------------
# Test 5: OpenAI/GPT provider is not_implemented
# ---------------------------------------------------------------------------


class TestOpenAIProviderRepresentation:
    """OpenAI/GPT provider is represented honestly as not_implemented."""

    def test_openai_provider_not_implemented(self):
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.OPENAI,
            model_name="gpt-4o",
            availability="not_implemented",
            local_or_remote="remote",
            supports_chat=False,
            supports_plan_only=False,
        )
        assert provider.availability == "not_implemented"
        assert provider.is_available is False
        assert provider.supports_chat is False

    def test_openai_not_implemented_is_not_available(self):
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.OPENAI,
            model_name="gpt-4o",
            availability="not_implemented",
            local_or_remote="remote",
        )
        assert provider.is_available is False

    def test_openai_to_dict_honest_status(self):
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.OPENAI,
            model_name="gpt-4o",
            availability="not_implemented",
            local_or_remote="remote",
        )
        d = provider.to_dict()
        assert d["availability"] == "not_implemented"
        assert d["is_available"] is False


# ---------------------------------------------------------------------------
# Test 6: Gemma provider is not_implemented
# ---------------------------------------------------------------------------


class TestGemmaProviderRepresentation:
    """Gemma provider is represented honestly as not_implemented."""

    def test_gemma_provider_not_implemented(self):
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.GEMMA,
            model_name="gemma3:4b",
            availability="not_implemented",
            local_or_remote="local",
            supports_chat=False,
            supports_plan_only=False,
        )
        assert provider.availability == "not_implemented"
        assert provider.is_available is False

    def test_gemma_local_or_remote_is_local(self):
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.GEMMA,
            model_name="gemma3:4b",
            availability="not_implemented",
            local_or_remote="local",
        )
        assert provider.local_or_remote == "local"

    def test_gemma_to_dict_honest(self):
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.GEMMA,
            model_name="gemma3:4b",
            availability="not_implemented",
            local_or_remote="local",
        )
        d = provider.to_dict()
        assert d["provider_name"] == "gemma"
        assert d["availability"] == "not_implemented"
        assert d["is_available"] is False


# ---------------------------------------------------------------------------
# Test 7: Provider response is cognitive_only and non_executing
# ---------------------------------------------------------------------------


class TestProviderResponseInvariants:
    """Provider responses always carry cognitive_only=True, used_execution=False."""

    def test_cognitive_response_invariants(self):
        response = make_cognitive_response(
            text="Plan: step 1, step 2",
            provider_name="anthropic",
            model_name="claude-haiku-4-5-20251001",
        )
        assert response["used_execution"] is False
        assert response["cognitive_only"] is True
        assert response["status"] == "ok"

    def test_unavailable_response_invariants(self):
        response = make_unavailable_response(
            provider_name="openai",
            model_name="gpt-4o",
            reason="not_implemented",
        )
        assert response["used_execution"] is False
        assert response["cognitive_only"] is True
        assert response["status"] == "unavailable"

    def test_cognitive_response_metadata_enforces_invariants(self):
        """Even if caller passes bad metadata, invariants are enforced."""
        response = make_cognitive_response(
            text="Plan description",
            provider_name="llama",
            model_name="mistral:7b",
            metadata={"cognitive_only": False, "used_execution": True},
        )
        assert response["used_execution"] is False
        assert response["cognitive_only"] is True

    def test_response_text_returned(self):
        response = make_cognitive_response(
            text="This is the plan",
            provider_name="anthropic",
            model_name="claude-haiku-4-5-20251001",
        )
        assert response["text"] == "This is the plan"

    def test_unavailable_response_has_no_text(self):
        response = make_unavailable_response(
            provider_name="gemma",
            reason="not_implemented",
        )
        assert response["text"] == ""
        assert response["error"] is not None

    def test_response_has_non_executing_in_metadata(self):
        response = make_cognitive_response(
            text="x",
            provider_name="anthropic",
            model_name="claude-haiku-4-5-20251001",
        )
        assert response["metadata"].get("non_executing") is True


# ---------------------------------------------------------------------------
# Test 8: Provider cannot bypass Police/AuthorizedPlan
# ---------------------------------------------------------------------------


class TestProviderCannotBypassGates:
    """
    Provider responses cannot be used to bypass security gates.

    These tests verify the contract-level invariants, not the gate itself.
    Gate tests live in test_police_gate_behavior_xfail.py and test_police_token_bound_gate.py.
    """

    def test_provider_response_does_not_create_execution_result(self):
        """A plan-only provider response cannot be treated as an execution result."""
        response = make_cognitive_response(
            text="Plan: step 1, step 2",
            provider_name="anthropic",
            model_name="claude-haiku-4-5-20251001",
        )
        assert response["used_execution"] is False
        assert "execution_result" not in response
        assert "authorized_plan" not in response
        assert "capability_token" not in response

    def test_unavailable_response_does_not_grant_execution(self):
        response = make_unavailable_response(
            provider_name="none",
            reason="no provider seated",
        )
        assert response["used_execution"] is False
        assert response["status"] != "ok"

    def test_cognitive_only_flag_prevents_execution_semantics(self):
        response = make_cognitive_response(
            text="Do not execute this",
            provider_name="llama",
            model_name="mistral:7b",
        )
        assert response["cognitive_only"] is True
        assert response["used_execution"] is False

    def test_provider_metadata_frozen(self):
        """Provider metadata object is immutable (frozen dataclass)."""
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="available",
            local_or_remote="remote",
        )
        with pytest.raises(Exception):
            provider.availability = "available"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 9: Delegated MSO Seat can carry provider metadata
# ---------------------------------------------------------------------------


class TestSeatCarriesProviderMetadata:
    """DelegatedMSOSeat to_dict can be enriched with provider metadata."""

    def test_seat_dict_can_include_provider_context(self):
        """Provider metadata can be attached to a seat audit dict."""
        from datetime import datetime, timezone, timedelta
        from assistant_os.mso.delegated_seat import (
            DelegatedMSOSeat, MSOSeatType, MSOSeatScope, MSOSeatStatus,
        )

        now = datetime.now(timezone.utc)
        seat = DelegatedMSOSeat(
            seat_id="provider-test-seat",
            seat_type=MSOSeatType.CLAUDE_ANALYTICAL,
            holder="claude-haiku-4-5-20251001",
            issued_by="kernel",
            issued_at=now,
            expires_at=now + timedelta(hours=8),
            scope=(MSOSeatScope.PLAN, MSOSeatScope.RECOMMEND),
            forbidden_actions=("direct_execution",),
            status=MSOSeatStatus.ACTIVE,
            audit_ref="audit-provider-test",
        )

        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="available",
            local_or_remote="remote",
        )

        seat_dict = seat.to_dict()
        seat_dict["provider_context"] = provider.to_dict()

        assert seat_dict["provider_context"]["provider_name"] == "anthropic"
        assert seat_dict["provider_context"]["cognitive_only"] is True
        assert seat_dict["provider_context"]["used_execution"] is False

    def test_provider_metadata_is_traceable(self):
        """Provider metadata dict contains all fields needed for audit."""
        provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.LLAMA,
            model_name="mistral:7b",
            availability="available",
            local_or_remote="local",
            config_source="env",
        )
        d = provider.to_dict()
        required_fields = {
            "provider_name", "model_name", "availability",
            "local_or_remote", "is_available", "cognitive_only", "used_execution",
        }
        for field in required_fields:
            assert field in d, f"Missing field in provider dict: {field}"

    def test_provider_unavailable_does_not_grant_execution_to_seat(self):
        """A seat with an unavailable provider cannot perform execution."""
        from datetime import datetime, timezone, timedelta
        from assistant_os.mso.delegated_seat import (
            DelegatedMSOSeat, MSOSeatType, MSOSeatScope, MSOSeatStatus,
        )
        from assistant_os.mso.delegated_seat_registry import (
            MSOSeatRegistry, reset_mso_seat_registry,
        )

        reset_mso_seat_registry()
        registry = MSOSeatRegistry()
        now = datetime.now(timezone.utc)

        seat = DelegatedMSOSeat(
            seat_id="unavailable-provider-seat",
            seat_type=MSOSeatType.EXTERNAL_MODEL,
            holder="openai-gpt-4o",
            issued_by="kernel",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            scope=(MSOSeatScope.PLAN,),
            forbidden_actions=("direct_execution",),
            status=MSOSeatStatus.ACTIVE,
            audit_ref="audit-unavail-provider",
        )
        registry.register_seat(seat)

        unavailable_provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.OPENAI,
            model_name="gpt-4o",
            availability="not_implemented",
            local_or_remote="remote",
        )

        assert registry.can_request_action(seat.seat_id, "plan") is True
        assert registry.can_request_action(seat.seat_id, "direct_execution") is False
        assert unavailable_provider.is_available is False
