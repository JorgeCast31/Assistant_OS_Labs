"""
M30: llama.cpp Live Cognitive Path tests.

Coverage:
 1. llamacpp provider health — server responds 200 ok
 2. llamacpp provider health — server offline (connection error)
 3. llamacpp provider health — server loading (503)
 4. llamacpp completion — success, valid JSON returned
 5. llamacpp completion — server returns malformed JSON
 6. llamacpp completion — timeout fallback
 7. Classification schema validation — all valid paths
 8. Classification validation — missing required keys
 9. Classification validation — non-numeric confidence
10. classify_with_local_llm — success returns ClassificationResult
11. classify_with_local_llm — fallback when LLM fails
12. cognitive_trace.used = True when advisory succeeds (orchestrator path)
13. cognitive_trace.fallback_used = True when advisory fails
14. probe_local_llm llamacpp — reachable + model_available = True
15. probe_local_llm llamacpp — offline returns reachable = False
"""
import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1-3: llamacpp health probe
# ---------------------------------------------------------------------------

class TestLlamacppHealthProbe(unittest.TestCase):
    """Unit tests for _llamacpp_probe_health()."""

    def _load(self):
        import importlib
        import assistant_os.mso.local_llm_adapter as mod
        importlib.reload(mod)
        return mod

    def test_health_ok_200(self):
        """200 response → reachable=True, no error."""
        mod = self._load()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}

        with patch("requests.get", return_value=mock_resp):
            reachable, error, latency_ms = mod._llamacpp_probe_health()

        self.assertTrue(reachable)
        self.assertIsNone(error)
        self.assertGreaterEqual(latency_ms, 0)

    def test_health_offline_connection_error(self):
        """Connection refused → reachable=False."""
        import requests as req_lib
        mod = self._load()

        with patch("requests.get", side_effect=req_lib.ConnectionError("refused")):
            reachable, error, latency_ms = mod._llamacpp_probe_health()

        self.assertFalse(reachable)
        self.assertIsNotNone(error)
        self.assertIn("failed", error)

    def test_health_loading_503(self):
        """503 with 'loading model' body → reachable=True, error message set."""
        mod = self._load()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.json.return_value = {"status": "loading model"}

        with patch("requests.get", return_value=mock_resp):
            reachable, error, latency_ms = mod._llamacpp_probe_health()

        self.assertTrue(reachable)
        self.assertIsNotNone(error)
        self.assertIn("loading", error.lower())

    def test_health_timeout(self):
        """Timeout → reachable=False, error mentions timeout."""
        import requests as req_lib
        mod = self._load()

        with patch("requests.get", side_effect=req_lib.Timeout("timed out")):
            reachable, error, latency_ms = mod._llamacpp_probe_health()

        self.assertFalse(reachable)
        self.assertIn("timeout", error.lower())


# ---------------------------------------------------------------------------
# 4-6: llamacpp completion
# ---------------------------------------------------------------------------

class TestLlamacppCompletion(unittest.TestCase):
    """Unit tests for _llamacpp_complete()."""

    def _load(self):
        import importlib
        import assistant_os.mso.local_llm_adapter as mod
        importlib.reload(mod)
        return mod

    def test_completion_success(self):
        """Valid JSON in content field → returns parsed dict."""
        mod = self._load()
        advisory_json = json.dumps({
            "reasoning_summary": "test reasoning",
            "routing_hint": "WORK",
            "suggested_domain": "WORK",
            "suggested_action": "WORK_QUERY",
            "execution_posture_hint": "auto",
            "confidence_note": "high",
            "code_task_summary": "",
            "repo_context": "",
            "constraints": [],
            "expected_artifact": "",
            "risk_notes": [],
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": advisory_json, "stop": True, "tokens_predicted": 80}

        with patch("requests.post", return_value=mock_resp):
            parsed, error, latency_ms = mod._llamacpp_complete("test prompt")

        self.assertIsNotNone(parsed)
        self.assertIsNone(error)
        self.assertEqual(parsed.get("reasoning_summary"), "test reasoning")

    def test_completion_malformed_json(self):
        """Non-JSON content → returns None with error."""
        mod = self._load()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": "this is not json at all"}

        with patch("requests.post", return_value=mock_resp):
            parsed, error, latency_ms = mod._llamacpp_complete("test prompt")

        self.assertIsNone(parsed)
        self.assertIsNotNone(error)
        self.assertIn("non-JSON", error)

    def test_completion_timeout(self):
        """Timeout → returns None with timeout error message."""
        import requests as req_lib
        mod = self._load()

        with patch("requests.post", side_effect=req_lib.Timeout("timed out")):
            parsed, error, latency_ms = mod._llamacpp_complete("test prompt")

        self.assertIsNone(parsed)
        self.assertIsNotNone(error)
        self.assertIn("timeout", error.lower())

    def test_completion_empty_content(self):
        """Empty content field → returns None with error."""
        mod = self._load()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": "", "stop": True}

        with patch("requests.post", return_value=mock_resp):
            parsed, error, latency_ms = mod._llamacpp_complete("test prompt")

        self.assertIsNone(parsed)
        self.assertIn("empty", error.lower())


# ---------------------------------------------------------------------------
# 7-9: Classification schema validation
# ---------------------------------------------------------------------------

class TestClassificationValidation(unittest.TestCase):
    """Unit tests for validate_classification_output()."""

    def setUp(self):
        from assistant_os.cognition.classifier import validate_classification_output
        self.validate = validate_classification_output

    def test_valid_full_schema(self):
        raw = {
            "classification": "WORK",
            "reasoning_summary": "looks like work",
            "risk_notes": "",
            "confidence": 0.82,
        }
        result, err = self.validate(raw)
        self.assertIsNotNone(result)
        self.assertEqual(err, "")
        self.assertEqual(result["classification"], "WORK")
        self.assertAlmostEqual(result["confidence"], 0.82)
        self.assertEqual(result["validation"], "passed")

    def test_confidence_clamped_above_1(self):
        raw = {"classification": "FIN", "reasoning_summary": "x", "risk_notes": "", "confidence": 1.5}
        result, err = self.validate(raw)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["confidence"], 1.0)

    def test_confidence_clamped_below_0(self):
        raw = {"classification": "CODE", "reasoning_summary": "x", "risk_notes": "", "confidence": -0.3}
        result, err = self.validate(raw)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["confidence"], 0.0)

    def test_missing_classification_key(self):
        raw = {"reasoning_summary": "x", "risk_notes": "", "confidence": 0.5}
        result, err = self.validate(raw)
        self.assertIsNone(result)
        self.assertIn("missing_keys", err)
        self.assertIn("classification", err)

    def test_missing_multiple_keys(self):
        raw = {"classification": "WORK"}
        result, err = self.validate(raw)
        self.assertIsNone(result)
        self.assertIn("missing_keys", err)

    def test_empty_classification_string(self):
        raw = {"classification": "   ", "reasoning_summary": "x", "risk_notes": "", "confidence": 0.5}
        result, err = self.validate(raw)
        self.assertIsNone(result)
        self.assertEqual(err, "classification_empty")

    def test_non_numeric_confidence(self):
        raw = {"classification": "FIN", "reasoning_summary": "x", "risk_notes": "", "confidence": "high"}
        result, err = self.validate(raw)
        self.assertIsNone(result)
        self.assertIn("confidence_not_numeric", err)

    def test_not_a_dict(self):
        result, err = self.validate(["WORK", 0.9])
        self.assertIsNone(result)
        self.assertEqual(err, "output_not_a_dict")

    def test_unknown_keys_stripped(self):
        """Extra keys in model output are ignored, result is still valid."""
        raw = {
            "classification": "WORK",
            "reasoning_summary": "x",
            "risk_notes": "",
            "confidence": 0.7,
            "extra_field": "ignored",
            "another": 123,
        }
        result, err = self.validate(raw)
        self.assertIsNotNone(result)
        self.assertNotIn("extra_field", result)


# ---------------------------------------------------------------------------
# 10-11: classify_with_local_llm — end-to-end
# ---------------------------------------------------------------------------

class TestClassifyWithLocalLlm(unittest.TestCase):
    """Tests for the public classify_with_local_llm() entry point."""

    def _env(self, provider="llamacpp"):
        return {
            "MSO_ENABLED": "true",
            "LOCAL_LLM_PROVIDER": provider,
            "LOCAL_LLM_BASE_URL": "http://localhost:8081",
            "LOCAL_LLM_MODEL": "mistral",
            "ASSISTANT_LOCAL_LLM_ENABLED": "true",
        }

    def test_success_returns_classification_result(self):
        """When llamacpp returns valid JSON, classify_with_local_llm returns result."""
        valid_output = {
            "classification": "WORK",
            "reasoning_summary": "looks like a work task",
            "risk_notes": "",
            "confidence": 0.85,
        }

        with patch.dict(os.environ, self._env()):
            import importlib
            import assistant_os.config as cfg
            importlib.reload(cfg)
            import assistant_os.mso.local_llm_adapter as ada
            importlib.reload(ada)
            import assistant_os.cognition.classifier as cls_mod
            importlib.reload(cls_mod)

            with patch.object(cls_mod, "_llamacpp_complete" if False else "__name__"):
                pass

            # Patch the _llamacpp_complete directly in the classifier module's imports
            with patch("assistant_os.mso.local_llm_adapter._llamacpp_complete",
                       return_value=(valid_output, None, 55)), \
                 patch("assistant_os.mso.local_llm_adapter.is_enabled", return_value=True), \
                 patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
                result = cls_mod.classify_with_local_llm("agenda esta reunión de trabajo")

        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], "WORK")
        self.assertAlmostEqual(result["confidence"], 0.85)
        self.assertEqual(result["backend"], "llamacpp")
        self.assertEqual(result["provider"], "local_llm")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["validation"], "passed")

    def test_fallback_when_llm_fails(self):
        """When _llamacpp_complete returns error, classify_with_local_llm returns None."""
        with patch.dict(os.environ, self._env()):
            import importlib
            import assistant_os.mso.local_llm_adapter as ada
            importlib.reload(ada)
            import assistant_os.cognition.classifier as cls_mod
            importlib.reload(cls_mod)

            with patch("assistant_os.mso.local_llm_adapter._llamacpp_complete",
                       return_value=(None, "connection refused", 0)), \
                 patch("assistant_os.mso.local_llm_adapter.is_enabled", return_value=True), \
                 patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
                result = cls_mod.classify_with_local_llm("some text")

        self.assertIsNone(result)

    def test_fallback_when_disabled(self):
        """When MSO is disabled, classify_with_local_llm returns None immediately."""
        with patch.dict(os.environ, {"MSO_ENABLED": "false", "LOCAL_LLM_PROVIDER": "llamacpp"}):
            import importlib
            import assistant_os.mso.local_llm_adapter as ada
            importlib.reload(ada)
            import assistant_os.cognition.classifier as cls_mod
            importlib.reload(cls_mod)

            with patch("assistant_os.mso.local_llm_adapter.is_enabled", return_value=False):
                result = cls_mod.classify_with_local_llm("some text")

        self.assertIsNone(result)

    def test_fallback_on_validation_failure(self):
        """When LLM returns invalid schema, classify_with_local_llm returns None."""
        bad_output = {"random_key": "value"}  # missing required keys

        with patch.dict(os.environ, self._env()):
            import importlib
            import assistant_os.mso.local_llm_adapter as ada
            importlib.reload(ada)
            import assistant_os.cognition.classifier as cls_mod
            importlib.reload(cls_mod)

            with patch("assistant_os.mso.local_llm_adapter._llamacpp_complete",
                       return_value=(bad_output, None, 40)), \
                 patch("assistant_os.mso.local_llm_adapter.is_enabled", return_value=True), \
                 patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
                result = cls_mod.classify_with_local_llm("some text")

        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 12-13: cognitive_trace threading through orchestrator
# ---------------------------------------------------------------------------

class TestCognitiveTraceOrchestrator(unittest.TestCase):
    """Tests for cognitive_trace injection via _inject_cognitive_trace."""

    def setUp(self):
        from assistant_os.core.orchestrator import _inject_cognitive_trace
        self.inject = _inject_cognitive_trace

    def _make_domain_result(self, data=None):
        from assistant_os.contracts import make_domain_result
        return make_domain_result(
            ok=True,
            result_type="work_query",
            domain="WORK",
            message="ok",
            data=data or {},
        )

    def test_cognitive_trace_used_true_when_advisory_ok(self):
        """advisory_trace with status=ok → cognitive_trace.used=True."""
        result = self._make_domain_result()
        advisory_trace = {
            "consulted": True,
            "status": "ok",
            "provider": "llamacpp",
            "model": "mistral",
            "latency_ms": 120,
        }
        with patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
            self.inject(result, advisory_trace)

        ct = result.get("data", {}).get("cognitive_trace")
        self.assertIsNotNone(ct)
        self.assertTrue(ct["used"])
        self.assertEqual(ct["backend"], "llamacpp")
        self.assertEqual(ct["task_type"], "orchestrator_advisory")
        self.assertFalse(ct["fallback_used"])
        self.assertEqual(ct["validation"], "passed")

    def test_cognitive_trace_fallback_when_advisory_error(self):
        """advisory_trace with status=error → cognitive_trace.used=False, fallback_used=True."""
        result = self._make_domain_result()
        advisory_trace = {
            "consulted": True,
            "status": "error",
            "provider": "llamacpp",
            "error": "timeout",
            "latency_ms": 4000,
        }
        with patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
            self.inject(result, advisory_trace)

        ct = result.get("data", {}).get("cognitive_trace")
        self.assertIsNotNone(ct)
        self.assertFalse(ct["used"])
        self.assertTrue(ct["fallback_used"])
        self.assertEqual(ct["validation"], "error")

    def test_cognitive_trace_not_overwritten_if_already_set(self):
        """If domain pipeline already set cognitive_trace, don't overwrite."""
        existing_ct = {"used": True, "task_type": "pipeline_custom"}
        result = self._make_domain_result(data={"cognitive_trace": existing_ct})
        advisory_trace = {"consulted": True, "status": "ok", "provider": "llamacpp"}
        with patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
            self.inject(result, advisory_trace)

        ct = result.get("data", {}).get("cognitive_trace")
        self.assertEqual(ct["task_type"], "pipeline_custom")  # unchanged

    def test_inject_safe_with_none_data(self):
        """_inject_cognitive_trace handles result.data = None without crashing."""
        result = self._make_domain_result()
        result["data"] = None  # force None
        advisory_trace = {"consulted": True, "status": "ok", "provider": "llamacpp"}
        with patch("assistant_os.mso.local_llm_adapter._normalized_provider", return_value="llamacpp"):
            self.inject(result, advisory_trace)
        # Should not raise; cognitive_trace should be set in new dict
        ct = (result.get("data") or {}).get("cognitive_trace")
        self.assertIsNotNone(ct)


# ---------------------------------------------------------------------------
# 14-15: probe_local_llm with llamacpp provider
# ---------------------------------------------------------------------------

class TestProbeLlamacpp(unittest.TestCase):
    """Tests for probe_local_llm() with LOCAL_LLM_PROVIDER=llamacpp."""

    def _env(self):
        return {
            "MSO_ENABLED": "true",
            "LOCAL_LLM_PROVIDER": "llamacpp",
            "LOCAL_LLM_BASE_URL": "http://localhost:8081",
            "LOCAL_LLM_MODEL": "mistral",
        }

    def test_probe_llamacpp_online(self):
        """probe_local_llm returns reachable=True and model_available=True when healthy."""
        with patch.dict(os.environ, self._env()):
            import importlib
            import assistant_os.config as cfg
            importlib.reload(cfg)
            import assistant_os.mso.local_llm_adapter as mod
            importlib.reload(mod)

            with patch.object(mod, "_llamacpp_probe_health", return_value=(True, None, 25)):
                status = mod.probe_local_llm(roundtrip=False)

        self.assertTrue(status["reachable"])
        self.assertTrue(status["model_available"])
        self.assertIsNone(status.get("error"))
        self.assertEqual(status["provider"], "llamacpp")

    def test_probe_llamacpp_offline(self):
        """probe_local_llm returns reachable=False when connection fails."""
        with patch.dict(os.environ, self._env()):
            import importlib
            import assistant_os.config as cfg
            importlib.reload(cfg)
            import assistant_os.mso.local_llm_adapter as mod
            importlib.reload(mod)

            with patch.object(mod, "_llamacpp_probe_health",
                               return_value=(False, "connection refused", 0)):
                status = mod.probe_local_llm(roundtrip=False)

        self.assertFalse(status["reachable"])
        self.assertFalse(status["model_available"])
        self.assertIsNotNone(status["error"])

    def tearDown(self):
        import importlib
        import assistant_os.config as cfg
        importlib.reload(cfg)
        import assistant_os.mso.local_llm_adapter as mod
        importlib.reload(mod)


if __name__ == "__main__":
    unittest.main()
