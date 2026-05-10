"""
Tests for MSO Seat Model Provider Registry / Selection.

Validates:
1. resolve_provider() returns correct metadata for all four names
2. Unknown provider names return None (fail-closed)
3. Anthropic availability reflects ANTHROPIC_API_KEY presence
4. Llama availability reflects MSO_ENABLED + LOCAL_LLM_* config
5. OpenAI is honestly not_implemented
6. Gemma is honestly not_implemented
7. get_seated_provider() returns None when MSO_SEAT_PROVIDER is unset
8. get_seated_provider() returns provider when MSO_SEAT_PROVIDER is set
9. list_all_providers() returns all four entries
10. describe_seated_provider() returns a non-empty string
11. make_plan_response() is always cognitive_only and non_executing

NO live API calls. Env vars are patched with monkeypatch.
"""

import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_config_cache(monkeypatch):
    """
    Patch config module to control env state per test.
    Most tests patch specific config attributes directly on the registry module
    via monkeypatch to avoid import ordering issues.
    """
    yield


# ---------------------------------------------------------------------------
# resolve_provider tests
# ---------------------------------------------------------------------------


class TestResolveProvider:
    """resolve_provider() returns correct metadata for each supported name."""

    def test_resolve_anthropic_returns_provider(self):
        from assistant_os.mso.seat_model_provider_registry import resolve_provider
        from assistant_os.mso.seat_model_provider import ModelProviderName

        result = resolve_provider("anthropic")
        assert result is not None
        assert result.provider_name == ModelProviderName.ANTHROPIC

    def test_resolve_openai_returns_provider(self):
        from assistant_os.mso.seat_model_provider_registry import resolve_provider
        from assistant_os.mso.seat_model_provider import ModelProviderName

        result = resolve_provider("openai")
        assert result is not None
        assert result.provider_name == ModelProviderName.OPENAI

    def test_resolve_llama_returns_provider(self):
        from assistant_os.mso.seat_model_provider_registry import resolve_provider
        from assistant_os.mso.seat_model_provider import ModelProviderName

        result = resolve_provider("llama")
        assert result is not None
        assert result.provider_name == ModelProviderName.LLAMA

    def test_resolve_gemma_returns_provider(self):
        from assistant_os.mso.seat_model_provider_registry import resolve_provider
        from assistant_os.mso.seat_model_provider import ModelProviderName

        result = resolve_provider("gemma")
        assert result is not None
        assert result.provider_name == ModelProviderName.GEMMA

    def test_resolve_unknown_returns_none(self):
        from assistant_os.mso.seat_model_provider_registry import resolve_provider

        assert resolve_provider("mistral") is None

    def test_resolve_empty_string_returns_none(self):
        from assistant_os.mso.seat_model_provider_registry import resolve_provider

        assert resolve_provider("") is None

    def test_resolve_openclaw_returns_none(self):
        from assistant_os.mso.seat_model_provider_registry import resolve_provider

        assert resolve_provider("openclaw") is None

    def test_resolve_host_returns_none(self):
        from assistant_os.mso.seat_model_provider_registry import resolve_provider

        assert resolve_provider("host") is None

    def test_resolve_is_case_insensitive(self):
        from assistant_os.mso.seat_model_provider_registry import resolve_provider
        from assistant_os.mso.seat_model_provider import ModelProviderName

        result = resolve_provider("ANTHROPIC")
        assert result is not None
        assert result.provider_name == ModelProviderName.ANTHROPIC


# ---------------------------------------------------------------------------
# Anthropic availability reflects API key
# ---------------------------------------------------------------------------


class TestAnthropicAvailability:
    """Anthropic availability is derived from ANTHROPIC_API_KEY env var."""

    def test_anthropic_available_when_key_set(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-test-key-not-real")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import _resolve_anthropic
        provider = _resolve_anthropic()
        assert provider.availability == "available"
        assert provider.is_available is True

    def test_anthropic_api_key_missing_when_key_absent(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", None)
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import _resolve_anthropic
        provider = _resolve_anthropic()
        assert provider.availability == "api_key_missing"
        assert provider.is_available is False

    def test_anthropic_api_key_empty_string_is_missing(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import _resolve_anthropic
        provider = _resolve_anthropic()
        assert provider.availability == "api_key_missing"

    def test_anthropic_model_defaults_from_config(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")
        monkeypatch.setattr(cfg, "CODE_REVIEW_MODEL", "claude-haiku-4-5-20251001")

        from assistant_os.mso.seat_model_provider_registry import _resolve_anthropic
        provider = _resolve_anthropic()
        assert provider.model_name != ""

    def test_anthropic_model_overridden_by_seat_model(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "claude-sonnet-4-6")

        from assistant_os.mso.seat_model_provider_registry import _resolve_anthropic
        provider = _resolve_anthropic()
        assert provider.model_name == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Llama availability reflects local config
# ---------------------------------------------------------------------------


class TestLlamaAvailability:
    """Llama availability derived from MSO_ENABLED + LOCAL_LLM_* config."""

    def test_llama_available_when_fully_configured(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_ENABLED", True)
        monkeypatch.setattr(cfg, "LOCAL_LLM_PROVIDER", "ollama")
        monkeypatch.setattr(cfg, "LOCAL_LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setattr(cfg, "LOCAL_LLM_MODEL", "mistral:7b")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import _resolve_llama
        provider = _resolve_llama()
        assert provider.availability == "available"
        assert provider.is_available is True
        assert provider.local_or_remote == "local"

    def test_llama_not_configured_when_mso_disabled(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_ENABLED", False)
        monkeypatch.setattr(cfg, "LOCAL_LLM_PROVIDER", "ollama")
        monkeypatch.setattr(cfg, "LOCAL_LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import _resolve_llama
        provider = _resolve_llama()
        assert provider.availability == "not_configured"
        assert provider.is_available is False

    def test_llama_local_endpoint_missing_when_no_url(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_ENABLED", True)
        monkeypatch.setattr(cfg, "LOCAL_LLM_PROVIDER", "ollama")
        monkeypatch.setattr(cfg, "LOCAL_LLM_BASE_URL", "")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import _resolve_llama
        provider = _resolve_llama()
        assert provider.availability == "local_endpoint_missing"
        assert provider.is_available is False

    def test_llama_local_endpoint_missing_when_no_provider(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_ENABLED", True)
        monkeypatch.setattr(cfg, "LOCAL_LLM_PROVIDER", "")
        monkeypatch.setattr(cfg, "LOCAL_LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import _resolve_llama
        provider = _resolve_llama()
        assert provider.availability == "local_endpoint_missing"

    def test_llama_model_from_local_llm_model(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_ENABLED", True)
        monkeypatch.setattr(cfg, "LOCAL_LLM_PROVIDER", "llamacpp")
        monkeypatch.setattr(cfg, "LOCAL_LLM_BASE_URL", "http://localhost:8080")
        monkeypatch.setattr(cfg, "LOCAL_LLM_MODEL", "neural-chat:7b")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import _resolve_llama
        provider = _resolve_llama()
        assert provider.model_name == "neural-chat:7b"

    def test_llama_does_not_make_network_calls(self, monkeypatch):
        """_resolve_llama uses config only, no network probes."""
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_ENABLED", True)
        monkeypatch.setattr(cfg, "LOCAL_LLM_PROVIDER", "ollama")
        monkeypatch.setattr(cfg, "LOCAL_LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setattr(cfg, "LOCAL_LLM_MODEL", "mistral:7b")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        with patch("assistant_os.mso.local_llm_adapter.probe_local_llm") as mock_probe:
            from assistant_os.mso.seat_model_provider_registry import _resolve_llama
            _resolve_llama()
            mock_probe.assert_not_called()


# ---------------------------------------------------------------------------
# OpenAI and Gemma are honestly not_implemented
# ---------------------------------------------------------------------------


class TestOpenAIGemmaHonestStatus:
    """OpenAI and Gemma are not_implemented — no adapter exists."""

    def test_openai_is_not_implemented(self):
        from assistant_os.mso.seat_model_provider_registry import _resolve_openai
        provider = _resolve_openai()
        assert provider.availability == "not_implemented"
        assert provider.is_available is False
        assert provider.supports_chat is False
        assert provider.supports_plan_only is False

    def test_gemma_is_not_implemented(self):
        from assistant_os.mso.seat_model_provider_registry import _resolve_gemma
        provider = _resolve_gemma()
        assert provider.availability == "not_implemented"
        assert provider.is_available is False
        assert provider.supports_chat is False
        assert provider.supports_plan_only is False

    def test_openai_config_source_is_none(self):
        from assistant_os.mso.seat_model_provider_registry import _resolve_openai
        provider = _resolve_openai()
        assert provider.config_source == "none"

    def test_gemma_config_source_is_none(self):
        from assistant_os.mso.seat_model_provider_registry import _resolve_gemma
        provider = _resolve_gemma()
        assert provider.config_source == "none"


# ---------------------------------------------------------------------------
# get_seated_provider
# ---------------------------------------------------------------------------


class TestGetSeatedProvider:
    """get_seated_provider() reads MSO_SEAT_PROVIDER from config."""

    def test_no_provider_when_env_unset(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "")

        from assistant_os.mso.seat_model_provider_registry import get_seated_provider
        result = get_seated_provider()
        assert result is None

    def test_anthropic_seated_when_env_set(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "anthropic")
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import get_seated_provider
        from assistant_os.mso.seat_model_provider import ModelProviderName
        result = get_seated_provider()
        assert result is not None
        assert result.provider_name == ModelProviderName.ANTHROPIC

    def test_llama_seated_when_env_set(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "llama")
        monkeypatch.setattr(cfg, "MSO_ENABLED", True)
        monkeypatch.setattr(cfg, "LOCAL_LLM_PROVIDER", "ollama")
        monkeypatch.setattr(cfg, "LOCAL_LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setattr(cfg, "LOCAL_LLM_MODEL", "mistral:7b")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import get_seated_provider
        from assistant_os.mso.seat_model_provider import ModelProviderName
        result = get_seated_provider()
        assert result is not None
        assert result.provider_name == ModelProviderName.LLAMA

    def test_invalid_provider_seated_returns_none(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "openclaw")

        from assistant_os.mso.seat_model_provider_registry import get_seated_provider
        result = get_seated_provider()
        assert result is None


# ---------------------------------------------------------------------------
# list_all_providers
# ---------------------------------------------------------------------------


class TestListAllProviders:
    """list_all_providers() returns all four provider entries."""

    def test_list_returns_four_providers(self):
        from assistant_os.mso.seat_model_provider_registry import list_all_providers
        providers = list_all_providers()
        assert len(providers) == 4

    def test_list_contains_all_names(self):
        from assistant_os.mso.seat_model_provider_registry import list_all_providers
        from assistant_os.mso.seat_model_provider import ModelProviderName

        providers = list_all_providers()
        names = {p.provider_name for p in providers}
        assert ModelProviderName.ANTHROPIC in names
        assert ModelProviderName.OPENAI in names
        assert ModelProviderName.LLAMA in names
        assert ModelProviderName.GEMMA in names

    def test_list_all_have_to_dict(self):
        from assistant_os.mso.seat_model_provider_registry import list_all_providers
        providers = list_all_providers()
        for p in providers:
            d = p.to_dict()
            assert "provider_name" in d
            assert "availability" in d
            assert d["cognitive_only"] is True
            assert d["used_execution"] is False


# ---------------------------------------------------------------------------
# describe_seated_provider
# ---------------------------------------------------------------------------


class TestDescribeSeatedProvider:
    """describe_seated_provider() returns a non-empty descriptive string."""

    def test_describe_no_provider_returns_safe_string(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "")

        from assistant_os.mso.seat_model_provider_registry import describe_seated_provider
        desc = describe_seated_provider()
        assert desc
        assert "No cognitive provider" in desc

    def test_describe_available_provider_includes_name(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "anthropic")
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "claude-haiku-4-5-20251001")

        from assistant_os.mso.seat_model_provider_registry import describe_seated_provider
        desc = describe_seated_provider()
        assert "anthropic" in desc
        assert "available" in desc

    def test_describe_unavailable_provider_includes_status(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "anthropic")
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", None)
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import describe_seated_provider
        desc = describe_seated_provider()
        assert "api_key_missing" in desc


# ---------------------------------------------------------------------------
# make_plan_response (cognitive_only invariant)
# ---------------------------------------------------------------------------


class TestMakePlanResponse:
    """make_plan_response() is always cognitive_only and non_executing."""

    def test_no_provider_returns_unavailable_response(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "")

        from assistant_os.mso.seat_model_provider_registry import make_plan_response
        resp = make_plan_response()
        assert resp["status"] == "unavailable"
        assert resp["used_execution"] is False
        assert resp["cognitive_only"] is True

    def test_unavailable_provider_returns_unavailable_response(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "anthropic")
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", None)
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import make_plan_response
        resp = make_plan_response()
        assert resp["status"] == "unavailable"
        assert resp["used_execution"] is False
        assert resp["cognitive_only"] is True

    def test_available_provider_returns_ok_response(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "anthropic")
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "claude-haiku-4-5-20251001")

        from assistant_os.mso.seat_model_provider_registry import make_plan_response
        resp = make_plan_response()
        assert resp["status"] == "ok"
        assert resp["used_execution"] is False
        assert resp["cognitive_only"] is True

    def test_plan_response_with_seat_ref(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "anthropic")
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "claude-haiku-4-5-20251001")

        from assistant_os.mso.seat_model_provider_registry import make_plan_response
        resp = make_plan_response(delegated_seat_ref="seat-test-001")
        assert resp["used_execution"] is False
        assert resp["cognitive_only"] is True
        assert resp["metadata"].get("delegated_seat_ref") == "seat-test-001"

    def test_not_implemented_provider_returns_unavailable(self, monkeypatch):
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "MSO_SEAT_PROVIDER", "openai")
        monkeypatch.setattr(cfg, "MSO_SEAT_MODEL", "")

        from assistant_os.mso.seat_model_provider_registry import make_plan_response
        resp = make_plan_response()
        assert resp["status"] == "unavailable"
        assert resp["used_execution"] is False
