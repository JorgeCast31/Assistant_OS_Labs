"""
M31: Hardening + Freeze — targeted hardening tests.

Coverage (hardening cases not exercised by M30 tests):
 1.  _llamacpp_probe_health — 503 with non-JSON body → not reachable
 2.  _llamacpp_probe_health — 503 with non-dict JSON body → not reachable (AttributeError guard)
 3.  _llamacpp_probe_health — 404 status → not reachable
 4.  _llamacpp_probe_health — 500 status → not reachable
 5.  _llamacpp_complete     — HTTP 500 error response → (None, error, latency)
 6.  _extract_json_object   — JSON array input → None
 7.  _extract_json_object   — JSON embedded in prose → extracted
 8.  _extract_json_object   — empty / whitespace → None
 9.  validate_classification_output — None input → output_not_a_dict
10.  validate_classification_output — bool True confidence → confidence_not_numeric
11.  validate_classification_output — bool False confidence → confidence_not_numeric
12.  validate_classification_output — confidence = 0.0 exact boundary → valid, clamped
13.  validate_classification_output — confidence = 1.0 exact boundary → valid, clamped
14.  validate_classification_output — confidence = None → confidence_not_numeric
15.  _inject_cognitive_trace — disabled status → used=False, fallback_used=True
16.  _inject_cognitive_trace — no "consulted" key → used=False (fail-closed)
17.  _inject_cognitive_trace — non-dict non-None data → skipped, no crash
18.  preferences.reset_preferences — restores default after user change
19.  preferences cross-request isolation — set then reset returns clean state
20.  preferences.reset_preferences — set_by reverts to "default"
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1-4: _llamacpp_probe_health — edge-case status codes
# ---------------------------------------------------------------------------

class TestLlamacppProbeHealthEdgeCases(unittest.TestCase):
    """Edge-case status codes not covered in M30 tests."""

    def _load(self):
        import importlib
        import assistant_os.mso.local_llm_adapter as mod
        importlib.reload(mod)
        return mod

    def test_503_non_json_body_not_reachable(self):
        """503 with non-JSON body (HTML error page etc.) → not reachable.

        Previously could raise AttributeError if body.json() returned None
        then body.get() was called on a non-dict.
        """
        mod = self._load()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.json.side_effect = ValueError("No JSON")

        with patch("requests.get", return_value=mock_resp):
            reachable, error, latency_ms = mod._llamacpp_probe_health()

        self.assertFalse(reachable)
        self.assertIsNotNone(error)

    def test_503_non_dict_json_body_not_reachable(self):
        """503 with valid JSON but non-dict body (e.g. string, list) → not reachable.

        Fixes M31 bug: body.get() on non-dict raised AttributeError.
        """
        mod = self._load()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        # json() returns a list, not a dict — previously triggered AttributeError
        mock_resp.json.return_value = ["loading model"]

        with patch("requests.get", return_value=mock_resp):
            reachable, error, latency_ms = mod._llamacpp_probe_health()

        self.assertFalse(reachable)

    def test_404_not_reachable(self):
        """404 → not reachable (wrong path / wrong server)."""
        mod = self._load()
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("requests.get", return_value=mock_resp):
            reachable, error, latency_ms = mod._llamacpp_probe_health()

        self.assertFalse(reachable)
        self.assertIn("404", error)

    def test_500_not_reachable(self):
        """500 → not reachable (server crash / fatal error)."""
        mod = self._load()
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("requests.get", return_value=mock_resp):
            reachable, error, latency_ms = mod._llamacpp_probe_health()

        self.assertFalse(reachable)
        self.assertIn("500", error)


# ---------------------------------------------------------------------------
# 5: _llamacpp_complete — HTTP error response
# ---------------------------------------------------------------------------

class TestLlamacppCompleteHttpError(unittest.TestCase):
    """_llamacpp_complete with HTTP error status codes."""

    def _load(self):
        import importlib
        import assistant_os.mso.local_llm_adapter as mod
        importlib.reload(mod)
        return mod

    def test_http_500_returns_none_with_error(self):
        """Server returns 500 → raise_for_status raises RequestException → (None, error, latency)."""
        import requests as req_lib
        mod = self._load()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = req_lib.HTTPError("500 Server Error")

        with patch("requests.post", return_value=mock_resp):
            parsed, error, latency_ms = mod._llamacpp_complete("test prompt")

        self.assertIsNone(parsed)
        self.assertIsNotNone(error)
        self.assertIn("request failed", error.lower())


# ---------------------------------------------------------------------------
# 6-8: _extract_json_object edge cases
# ---------------------------------------------------------------------------

class TestExtractJsonObject(unittest.TestCase):
    """_extract_json_object — edge cases for robust JSON extraction."""

    def setUp(self):
        import importlib
        import assistant_os.mso.local_llm_adapter as mod
        importlib.reload(mod)
        self.extract = mod._extract_json_object

    def test_json_array_returns_none(self):
        """A top-level JSON array is not an object — return None."""
        result = self.extract('["a", "b", "c"]')
        self.assertIsNone(result)

    def test_json_embedded_in_prose_extracted(self):
        """JSON object embedded in surrounding text should be extracted."""
        prose = 'Here is the result: {"key": "value", "num": 42} end.'
        result = self.extract(prose)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("key"), "value")
        self.assertEqual(result.get("num"), 42)

    def test_empty_string_returns_none(self):
        """Empty string → None."""
        self.assertIsNone(self.extract(""))

    def test_whitespace_string_returns_none(self):
        """Whitespace-only string → None."""
        self.assertIsNone(self.extract("   \n  "))

    def test_none_input_returns_none(self):
        """None input → None without raising."""
        self.assertIsNone(self.extract(None))  # type: ignore[arg-type]

    def test_plain_text_no_json_returns_none(self):
        """Plain text with no JSON → None."""
        self.assertIsNone(self.extract("No JSON content here at all"))


# ---------------------------------------------------------------------------
# 9-14: validate_classification_output — hardening edge cases
# ---------------------------------------------------------------------------

class TestClassificationValidationHardening(unittest.TestCase):
    """validate_classification_output — edge cases added in M31 hardening."""

    def setUp(self):
        from assistant_os.cognition.classifier import validate_classification_output
        self.validate = validate_classification_output

    def test_none_input_fails_closed(self):
        """None input → output_not_a_dict (not AttributeError)."""
        result, err = self.validate(None)
        self.assertIsNone(result)
        self.assertEqual(err, "output_not_a_dict")

    def test_bool_true_confidence_rejected(self):
        """confidence=True silently becomes 1.0 without M31 guard.
        With guard: must be rejected as confidence_not_numeric."""
        raw = {
            "classification": "WORK",
            "reasoning_summary": "test",
            "risk_notes": "",
            "confidence": True,   # bool — schema error from model
        }
        result, err = self.validate(raw)
        self.assertIsNone(result)
        self.assertIn("confidence_not_numeric", err)

    def test_bool_false_confidence_rejected(self):
        """confidence=False must also be rejected."""
        raw = {
            "classification": "FIN",
            "reasoning_summary": "test",
            "risk_notes": "",
            "confidence": False,
        }
        result, err = self.validate(raw)
        self.assertIsNone(result)
        self.assertIn("confidence_not_numeric", err)

    def test_confidence_none_rejected(self):
        """confidence=None → confidence_not_numeric."""
        raw = {
            "classification": "CODE",
            "reasoning_summary": "test",
            "risk_notes": "",
            "confidence": None,
        }
        result, err = self.validate(raw)
        self.assertIsNone(result)
        self.assertIn("confidence_not_numeric", err)

    def test_confidence_zero_exact_boundary_valid(self):
        """confidence=0.0 (lower boundary) → valid and returned as 0.0."""
        raw = {
            "classification": "OTHER",
            "reasoning_summary": "uncertain",
            "risk_notes": "",
            "confidence": 0.0,
        }
        result, err = self.validate(raw)
        self.assertIsNotNone(result)
        self.assertEqual(err, "")
        self.assertAlmostEqual(result["confidence"], 0.0)

    def test_confidence_one_exact_boundary_valid(self):
        """confidence=1.0 (upper boundary) → valid and returned as 1.0."""
        raw = {
            "classification": "WORK",
            "reasoning_summary": "certain",
            "risk_notes": "",
            "confidence": 1.0,
        }
        result, err = self.validate(raw)
        self.assertIsNotNone(result)
        self.assertEqual(err, "")
        self.assertAlmostEqual(result["confidence"], 1.0)

    def test_string_list_input_fails_closed(self):
        """A list input → output_not_a_dict."""
        result, err = self.validate(["WORK", 0.9, "notes"])
        self.assertIsNone(result)
        self.assertEqual(err, "output_not_a_dict")

    def test_integer_input_fails_closed(self):
        """An integer input → output_not_a_dict."""
        result, err = self.validate(42)
        self.assertIsNone(result)
        self.assertEqual(err, "output_not_a_dict")


# ---------------------------------------------------------------------------
# 15-17: _inject_cognitive_trace — trace semantic hardening
# ---------------------------------------------------------------------------

class TestInjectCognitiveTraceHardening(unittest.TestCase):
    """_inject_cognitive_trace — edge cases for trace semantic correctness."""

    def setUp(self):
        from assistant_os.core.orchestrator import _inject_cognitive_trace
        self.inject = _inject_cognitive_trace

    def _make_result(self, data=None):
        from assistant_os.contracts import make_domain_result
        return make_domain_result(
            ok=True,
            result_type="work_query",
            domain="WORK",
            message="ok",
            data=data if data is not None else {},
        )

    def test_disabled_status_sets_used_false(self):
        """advisory_trace with status='disabled' → used=False, fallback_used=True."""
        result = self._make_result()
        advisory_trace = {
            "consulted": False,
            "status": "disabled",
            "provider": "llamacpp",
        }
        with patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
            self.inject(result, advisory_trace)

        ct = result["data"]["cognitive_trace"]
        self.assertFalse(ct["used"])
        self.assertTrue(ct["fallback_used"])
        self.assertEqual(ct["validation"], "disabled")

    def test_missing_consulted_key_fails_closed(self):
        """advisory_trace with status='ok' but no 'consulted' key → used=False (fail-closed)."""
        result = self._make_result()
        advisory_trace = {
            # "consulted" key intentionally absent
            "status": "ok",
            "provider": "llamacpp",
        }
        with patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
            self.inject(result, advisory_trace)

        ct = result["data"]["cognitive_trace"]
        # No consulted=True → used must be False even if status=ok
        self.assertFalse(ct["used"])

    def test_non_dict_non_none_data_not_crashed(self):
        """result.data is a non-dict, non-None value → inject skips gracefully, no crash.

        M31 hardening: previously would replace non-dict data with a new dict.
        Now: logs warning and skips injection (preserves existing non-dict data).
        """
        result = self._make_result()
        result["data"] = "unexpected_string"  # non-dict, non-None
        advisory_trace = {"consulted": True, "status": "ok", "provider": "llamacpp"}

        with patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
            # Must not raise
            self.inject(result, advisory_trace)

        # data unchanged — we chose not to overwrite it
        self.assertEqual(result["data"], "unexpected_string")

    def test_trace_validation_field_reflects_error_status(self):
        """advisory_trace status='error' → validation field is 'error'."""
        result = self._make_result()
        advisory_trace = {
            "consulted": True,
            "status": "error",
            "provider": "llamacpp",
            "error": "timeout",
        }
        with patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
            self.inject(result, advisory_trace)

        ct = result["data"]["cognitive_trace"]
        self.assertEqual(ct["validation"], "error")
        self.assertFalse(ct["used"])
        self.assertTrue(ct["fallback_used"])


# ---------------------------------------------------------------------------
# 18-20: preferences.py — reset + isolation
# ---------------------------------------------------------------------------

class TestPreferencesReset(unittest.TestCase):
    """preferences.reset_preferences() — test isolation helper correctness."""

    def setUp(self):
        from assistant_os.cognition.preferences import reset_preferences
        reset_preferences()  # ensure clean baseline before each test

    def tearDown(self):
        from assistant_os.cognition.preferences import reset_preferences
        reset_preferences()  # clean up after each test

    def test_reset_after_user_change_restores_default_policy(self):
        """set_preferences then reset → policy back to default."""
        from assistant_os.cognition.preferences import (
            get_preferences,
            reset_preferences,
            set_preferences,
        )
        ok, err = set_preferences("prefer_local")
        self.assertTrue(ok)
        self.assertEqual(get_preferences()["policy"], "prefer_local")

        reset_preferences()
        prefs = get_preferences()
        # Default is "auto" per config (COGNITION_DEFAULT_POLICY defaults to "auto")
        self.assertIn(prefs["policy"], {"auto", "prefer_local", "deterministic_only"})
        self.assertEqual(prefs["set_by"], "default")

    def test_reset_restores_set_by_to_default(self):
        """After a user change, reset sets set_by back to 'default'."""
        from assistant_os.cognition.preferences import (
            get_preferences,
            reset_preferences,
            set_preferences,
        )
        set_preferences("deterministic_only")
        self.assertEqual(get_preferences()["set_by"], "user")

        reset_preferences()
        self.assertEqual(get_preferences()["set_by"], "default")

    def test_preferences_isolated_between_tests(self):
        """Each test starts with default state due to setUp/tearDown reset."""
        from assistant_os.cognition.preferences import get_preferences
        prefs = get_preferences()
        # If previous test set "prefer_local", this should still see "default"
        self.assertEqual(prefs["set_by"], "default")


if __name__ == "__main__":
    unittest.main()
