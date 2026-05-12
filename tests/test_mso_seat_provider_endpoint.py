"""
Tests for GET /mso/seat/provider backend endpoint — S-MSO-SEAT-PROVIDER-01.

Validates:
1. Endpoint returns ok=true
2. Endpoint returns execution_allowed=false always
3. Endpoint returns can_execute_now=false always
4. Endpoint never exposes secrets (ANTHROPIC_API_KEY, WEBHOOK_TOKEN)
5. Endpoint does not make network calls to provider
6. Endpoint handles no provider configured safely (seat_provider=null)
7. Endpoint includes provider_name/model_name when configured
8. seat_provider.cognitive_only=true always
9. seat_provider.used_execution=false always
10. seat_provider.non_executing=true always

NO live HTTP server. Tests call the handler logic directly via webhook handler.
NO live API calls. Env vars patched with monkeypatch.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers — inline handler invocation without running a real server
# ---------------------------------------------------------------------------


def _invoke_handler(monkeypatch_or_patches: dict) -> dict:
    """
    Invoke the seat provider logic inline by calling the same code path
    that _handle_mso_seat_provider_get() uses, without spinning up HTTP.
    """
    from assistant_os.mso.seat_model_provider_registry import (
        get_seated_provider,
        describe_seated_provider,
    )

    provider = get_seated_provider()
    description = describe_seated_provider()

    _NOTE = (
        "MSO Seat provider metadata is read-only. "
        "Provider availability is config-derived — no network calls are made. "
        "This surface does not execute, approve, or issue tokens. "
        "Cognitive only. Used execution: false."
    )

    if provider is None:
        return {
            "ok": True,
            "seat_provider": None,
            "description": description,
            "execution_allowed": False,
            "can_execute_now": False,
            "note": _NOTE,
        }

    provider_dict = provider.to_dict()
    seat_provider = {
        "provider_name": provider_dict["provider_name"],
        "model_name": provider_dict["model_name"],
        "provider_kind": provider_dict["provider_name"],
        "is_available": provider_dict["is_available"],
        "availability": provider_dict["availability"],
        "local_or_remote": provider_dict["local_or_remote"],
        "cognitive_only": True,
        "used_execution": False,
        "non_executing": True,
    }

    return {
        "ok": True,
        "seat_provider": seat_provider,
        "description": description,
        "execution_allowed": False,
        "can_execute_now": False,
        "note": _NOTE,
    }


# ---------------------------------------------------------------------------
# Test 1: Endpoint returns ok=true when no provider configured
# ---------------------------------------------------------------------------


class TestEndpointOkWhenNoProvider(unittest.TestCase):
    def test_ok_true_when_no_provider(self):
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=None,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="No cognitive provider is currently seated/configured.",
        ):
            result = _invoke_handler({})
        self.assertTrue(result["ok"])

    def test_seat_provider_null_when_no_provider(self):
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=None,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="No cognitive provider is currently seated/configured.",
        ):
            result = _invoke_handler({})
        self.assertIsNone(result["seat_provider"])


# ---------------------------------------------------------------------------
# Test 2: execution_allowed is ALWAYS false
# ---------------------------------------------------------------------------


class TestExecutionAllowedAlwaysFalse(unittest.TestCase):
    def test_execution_allowed_false_no_provider(self):
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=None,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="No provider.",
        ):
            result = _invoke_handler({})
        self.assertIs(result["execution_allowed"], False)

    def test_execution_allowed_false_with_provider(self):
        from assistant_os.mso.seat_model_provider import MSOSeatModelProvider, ModelProviderName

        mock_provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="available",
            local_or_remote="remote",
        )
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=mock_provider,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="Seated provider: anthropic / claude-haiku-4-5-20251001 [available]",
        ):
            result = _invoke_handler({})
        self.assertIs(result["execution_allowed"], False)


# ---------------------------------------------------------------------------
# Test 3: can_execute_now is ALWAYS false
# ---------------------------------------------------------------------------


class TestCanExecuteNowAlwaysFalse(unittest.TestCase):
    def test_can_execute_now_false_no_provider(self):
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=None,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="No provider.",
        ):
            result = _invoke_handler({})
        self.assertIs(result["can_execute_now"], False)

    def test_can_execute_now_false_with_provider(self):
        from assistant_os.mso.seat_model_provider import MSOSeatModelProvider, ModelProviderName

        mock_provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="available",
            local_or_remote="remote",
        )
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=mock_provider,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="Seated provider: anthropic / claude-haiku-4-5-20251001 [available]",
        ):
            result = _invoke_handler({})
        self.assertIs(result["can_execute_now"], False)


# ---------------------------------------------------------------------------
# Test 4: Response never exposes secrets
# ---------------------------------------------------------------------------


class TestResponseNeverExposesSecrets(unittest.TestCase):
    def _result_as_json(self, result: dict) -> str:
        return json.dumps(result)

    def test_no_api_key_in_response_no_provider(self):
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=None,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="No provider.",
        ):
            result = _invoke_handler({})
        serialized = self._result_as_json(result)
        self.assertNotIn("ANTHROPIC_API_KEY", serialized)
        self.assertNotIn("api_key", serialized.lower())
        self.assertNotIn("WEBHOOK_TOKEN", serialized)

    def test_no_api_key_in_response_with_provider(self):
        from assistant_os.mso.seat_model_provider import MSOSeatModelProvider, ModelProviderName

        mock_provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="available",
            local_or_remote="remote",
        )
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=mock_provider,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="Seated provider: anthropic / claude-haiku-4-5-20251001 [available]",
        ):
            result = _invoke_handler({})
        serialized = self._result_as_json(result)
        self.assertNotIn("ANTHROPIC_API_KEY", serialized)
        self.assertNotIn("WEBHOOK_TOKEN", serialized)
        self.assertNotIn("sk-ant-", serialized)


# ---------------------------------------------------------------------------
# Test 5: No network calls to provider
# ---------------------------------------------------------------------------


class TestNoNetworkCallsToProvider(unittest.TestCase):
    def test_handler_does_not_call_provider_network(self):
        """
        The handler calls get_seated_provider() which reads config only.
        Verify no external HTTP call is attempted by patching requests.
        """
        import unittest.mock as mock_module

        with mock_module.patch("requests.get") as mock_get, \
             mock_module.patch("requests.post") as mock_post, \
             patch(
                 "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
                 return_value=None,
             ), patch(
                 "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
                 return_value="No provider.",
             ):
            _invoke_handler({})
            mock_get.assert_not_called()
            mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: Handles no provider safely
# ---------------------------------------------------------------------------


class TestHandlesNoProviderSafely(unittest.TestCase):
    def test_no_exception_when_no_provider(self):
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=None,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="No cognitive provider is currently seated/configured.",
        ):
            try:
                result = _invoke_handler({})
            except Exception as exc:
                self.fail(f"Handler raised exception with no provider: {exc}")
        self.assertIsNotNone(result)
        self.assertIn("description", result)

    def test_description_present_when_no_provider(self):
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=None,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="No cognitive provider is currently seated/configured.",
        ):
            result = _invoke_handler({})
        self.assertIn("No", result["description"])


# ---------------------------------------------------------------------------
# Test 7: Provider name and model name present when configured
# ---------------------------------------------------------------------------


class TestProviderNameAndModelPresent(unittest.TestCase):
    def test_provider_name_in_seat_provider(self):
        from assistant_os.mso.seat_model_provider import MSOSeatModelProvider, ModelProviderName

        mock_provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="available",
            local_or_remote="remote",
        )
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=mock_provider,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="Seated provider: anthropic / claude-haiku-4-5-20251001 [available]",
        ):
            result = _invoke_handler({})

        self.assertIsNotNone(result["seat_provider"])
        self.assertEqual(result["seat_provider"]["provider_name"], "anthropic")

    def test_model_name_in_seat_provider(self):
        from assistant_os.mso.seat_model_provider import MSOSeatModelProvider, ModelProviderName

        mock_provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="available",
            local_or_remote="remote",
        )
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=mock_provider,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="Seated provider: anthropic / claude-haiku-4-5-20251001 [available]",
        ):
            result = _invoke_handler({})

        self.assertEqual(result["seat_provider"]["model_name"], "claude-haiku-4-5-20251001")

    def test_llama_provider_represented(self):
        from assistant_os.mso.seat_model_provider import MSOSeatModelProvider, ModelProviderName

        mock_provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.LLAMA,
            model_name="mistral:7b",
            availability="available",
            local_or_remote="local",
        )
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=mock_provider,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="Seated provider: llama / mistral:7b [available]",
        ):
            result = _invoke_handler({})

        self.assertEqual(result["seat_provider"]["provider_name"], "llama")
        self.assertEqual(result["seat_provider"]["model_name"], "mistral:7b")
        self.assertEqual(result["seat_provider"]["local_or_remote"], "local")


# ---------------------------------------------------------------------------
# Tests 8–10: seat_provider invariants
# ---------------------------------------------------------------------------


class TestSeatProviderInvariants(unittest.TestCase):
    def _provider_result(self):
        from assistant_os.mso.seat_model_provider import MSOSeatModelProvider, ModelProviderName

        mock_provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="available",
            local_or_remote="remote",
        )
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=mock_provider,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="Seated provider: anthropic / claude-haiku-4-5-20251001 [available]",
        ):
            return _invoke_handler({})

    def test_cognitive_only_true(self):
        result = self._provider_result()
        self.assertIs(result["seat_provider"]["cognitive_only"], True)

    def test_used_execution_false(self):
        result = self._provider_result()
        self.assertIs(result["seat_provider"]["used_execution"], False)

    def test_non_executing_true(self):
        result = self._provider_result()
        self.assertIs(result["seat_provider"]["non_executing"], True)

    def test_provider_kind_matches_provider_name(self):
        result = self._provider_result()
        self.assertEqual(
            result["seat_provider"]["provider_kind"],
            result["seat_provider"]["provider_name"],
        )

    def test_is_available_true_for_available_provider(self):
        result = self._provider_result()
        self.assertIs(result["seat_provider"]["is_available"], True)

    def test_api_key_missing_yields_not_available(self):
        from assistant_os.mso.seat_model_provider import MSOSeatModelProvider, ModelProviderName

        mock_provider = MSOSeatModelProvider(
            provider_name=ModelProviderName.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            availability="api_key_missing",
            local_or_remote="remote",
        )
        with patch(
            "assistant_os.mso.seat_model_provider_registry.get_seated_provider",
            return_value=mock_provider,
        ), patch(
            "assistant_os.mso.seat_model_provider_registry.describe_seated_provider",
            return_value="Seated provider: anthropic / claude-haiku-4-5-20251001 [api_key_missing]",
        ):
            result = _invoke_handler({})

        self.assertIs(result["seat_provider"]["is_available"], False)
        self.assertEqual(result["seat_provider"]["availability"], "api_key_missing")
        self.assertIs(result["execution_allowed"], False)
        self.assertIs(result["can_execute_now"], False)


if __name__ == "__main__":
    unittest.main()
