"""
M29: Cognition layer tests.

Covers:
- Provider health when feature is disabled
- Provider health when feature is enabled + probe succeeds
- Provider health when probe fails (offline)
- Provider health when model not available (degraded)
- Preference store: default, valid update, invalid update
- Webhook GET /cognition/providers (auth required)
- Webhook GET /cognition/providers/health (auth required)
- Webhook GET /cognition/preferences (auth required)
- Webhook POST /cognition/preferences (valid/invalid policy)
- cognitive_trace present in chat response when ASSISTANT_LOCAL_LLM_ENABLED
"""
import http.client
import os
import json
import time
import unittest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Provider health — feature disabled
# ---------------------------------------------------------------------------

class TestCognitionProvidersDisabled(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ASSISTANT_LOCAL_LLM_ENABLED", None)

    def test_disabled_returns_single_provider_with_disabled_status(self):
        # Reload config with feature off; patch dotenv so .env does not override env vars
        with patch.dict(os.environ, {
                "ASSISTANT_LOCAL_LLM_ENABLED": "false",
                "ASSISTANT_UI_SHOW_COGNITION": "false",
            }), \
             patch("dotenv.load_dotenv"):
            # Force reimport so new env is picked up
            import importlib
            import assistant_os.config as cfg
            importlib.reload(cfg)
            import assistant_os.cognition.providers as mod
            importlib.reload(mod)

            result = mod.get_providers()

        self.assertTrue(result["ok"])
        self.assertFalse(result["ui_cognition_enabled"])
        self.assertEqual(len(result["providers"]), 1)
        p = result["providers"][0]
        self.assertEqual(p["status"], "disabled")
        self.assertFalse(p["feature_enabled"])

    def tearDown(self):
        # Restore to clean state
        import importlib
        import assistant_os.config as cfg
        importlib.reload(cfg)
        import assistant_os.cognition.providers as mod
        importlib.reload(mod)


# ---------------------------------------------------------------------------
# Provider health — feature enabled, probe scenarios
# ---------------------------------------------------------------------------

class TestCognitionProvidersEnabled(unittest.TestCase):
    def _reload_with_env(self, extra_env):
        import importlib
        env = {
            "ASSISTANT_LOCAL_LLM_ENABLED": "true",
            "MSO_ENABLED": "true",
            "LOCAL_LLM_PROVIDER": "ollama",
            "LOCAL_LLM_BASE_URL": "http://localhost:11434",
            "LOCAL_LLM_MODEL": "mistral",
            **extra_env,
        }
        with patch.dict(os.environ, env, clear=False):
            import assistant_os.config as cfg
            importlib.reload(cfg)
            import assistant_os.cognition.providers as mod
            importlib.reload(mod)
            return mod

    def test_online_when_probe_succeeds(self):
        import importlib
        mod = self._reload_with_env({})

        fake_status = {
            "enabled": True,
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "mistral",
            "reachable": True,
            "model_available": True,
            "roundtrip_ok": False,
            "latency_ms": 42,
            "error": None,
        }
        with patch("assistant_os.mso.local_llm_adapter.probe_local_llm", return_value=fake_status), \
             patch("assistant_os.mso.local_llm_adapter.is_enabled", return_value=True):
            result = mod.get_providers()

        self.assertTrue(result["ok"])
        p = result["providers"][0]
        self.assertEqual(p["status"], "online")
        self.assertFalse(p["degraded"])
        self.assertEqual(p["latency_ms"], 42)
        self.assertGreater(len(p["available_tasks"]), 0)

    def test_offline_when_not_reachable(self):
        import importlib
        mod = self._reload_with_env({})

        fake_status = {
            "enabled": True,
            "reachable": False,
            "model_available": False,
            "latency_ms": 0,
            "error": "Connection refused",
        }
        with patch("assistant_os.mso.local_llm_adapter.probe_local_llm", return_value=fake_status), \
             patch("assistant_os.mso.local_llm_adapter.is_enabled", return_value=True):
            result = mod.get_providers()

        p = result["providers"][0]
        self.assertEqual(p["status"], "offline")
        self.assertFalse(p["degraded"])
        self.assertEqual(p["available_tasks"], [])

    def test_degraded_when_reachable_but_model_missing(self):
        import importlib
        mod = self._reload_with_env({})

        fake_status = {
            "enabled": True,
            "reachable": True,
            "model_available": False,
            "latency_ms": 10,
            "error": "model 'mistral' not found",
        }
        with patch("assistant_os.mso.local_llm_adapter.probe_local_llm", return_value=fake_status), \
             patch("assistant_os.mso.local_llm_adapter.is_enabled", return_value=True):
            result = mod.get_providers()

        p = result["providers"][0]
        self.assertEqual(p["status"], "degraded")
        self.assertTrue(p["degraded"])
        self.assertEqual(p["available_tasks"], [])

    def test_probe_exception_returns_offline(self):
        import importlib
        mod = self._reload_with_env({})

        with patch("assistant_os.mso.local_llm_adapter.probe_local_llm", side_effect=RuntimeError("network error")), \
             patch("assistant_os.mso.local_llm_adapter.is_enabled", return_value=True):
            result = mod.get_providers()

        p = result["providers"][0]
        self.assertEqual(p["status"], "offline")
        self.assertIn("network error", p["error"])

    def test_disabled_when_is_enabled_false(self):
        import importlib
        mod = self._reload_with_env({})

        with patch("assistant_os.mso.local_llm_adapter.is_enabled", return_value=False):
            result = mod.get_providers()

        p = result["providers"][0]
        self.assertEqual(p["status"], "disabled")

    def tearDown(self):
        import importlib
        import assistant_os.config as cfg
        importlib.reload(cfg)


# ---------------------------------------------------------------------------
# Preference store
# ---------------------------------------------------------------------------

class TestCognitionPreferences(unittest.TestCase):
    def setUp(self):
        # Reset preference store to default before each test
        import assistant_os.cognition.preferences as prefs
        import importlib
        importlib.reload(prefs)
        self._prefs = prefs

    def test_default_policy_is_auto(self):
        result = self._prefs.get_preferences()
        self.assertIn(result["policy"], ("auto", "prefer_local", "deterministic_only"))
        self.assertEqual(result["set_by"], "default")

    def test_valid_policy_update(self):
        for policy in ("auto", "prefer_local", "deterministic_only"):
            ok, err = self._prefs.set_preferences(policy)
            self.assertTrue(ok, f"Expected ok for policy={policy}, got err={err}")
            self.assertEqual(err, "")
            result = self._prefs.get_preferences()
            self.assertEqual(result["policy"], policy)
            self.assertEqual(result["set_by"], "user")

    def test_invalid_policy_rejected(self):
        ok, err = self._prefs.set_preferences("turbo_mode")
        self.assertFalse(ok)
        self.assertIn("turbo_mode", err)

    def test_empty_policy_rejected(self):
        ok, err = self._prefs.set_preferences("")
        self.assertFalse(ok)
        self.assertNotEqual(err, "")


# ---------------------------------------------------------------------------
# Webhook endpoint tests — real HTTP server (same pattern as test_codeops_endpoints.py)
# ---------------------------------------------------------------------------

class TestCognitionWebhookEndpoints(unittest.TestCase):
    """End-to-end tests using a real webhook server thread."""

    @classmethod
    def setUpClass(cls):
        from assistant_os.webhook_server import start_server_thread
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)
        from assistant_os.config import WEBHOOK_TOKEN
        cls.token = WEBHOOK_TOKEN

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _request(self, method, path, body=None, token=None):
        tok = token if token is not None else self.token
        headers = {"Content-Type": "application/json", "X-Assistant-Token": tok}
        body_bytes = json.dumps(body).encode() if body else None
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        raw = resp.read().decode()
        conn.close()
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, {"_raw": raw}

    def test_get_providers_requires_auth(self):
        status, _ = self._request("GET", "/cognition/providers", token="wrong")
        self.assertEqual(status, 401)

    def test_get_providers_returns_ok_with_auth(self):
        status, data = self._request("GET", "/cognition/providers")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("providers", data)
        self.assertIsInstance(data["providers"], list)
        self.assertGreater(len(data["providers"]), 0)

    def test_get_providers_health_returns_ok(self):
        status, data = self._request("GET", "/cognition/providers/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("providers", data)

    def test_get_preferences_returns_policy(self):
        status, data = self._request("GET", "/cognition/preferences")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn(data["policy"], ("auto", "prefer_local", "deterministic_only"))

    def test_post_preferences_valid_policy(self):
        status, data = self._request("POST", "/cognition/preferences", body={"policy": "deterministic_only"})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["policy"], "deterministic_only")
        self.assertEqual(data["set_by"], "user")

    def test_post_preferences_invalid_policy(self):
        status, data = self._request("POST", "/cognition/preferences", body={"policy": "superpowers"})
        self.assertEqual(status, 400)
        # Error responses use {"status": "error"} not {"ok": false}
        self.assertEqual(data.get("status"), "error")

    def test_post_preferences_missing_field(self):
        status, data = self._request("POST", "/cognition/preferences", body={})
        self.assertEqual(status, 400)
        self.assertEqual(data.get("status"), "error")

    def test_post_preferences_requires_auth(self):
        status, _ = self._request("POST", "/cognition/preferences", body={"policy": "auto"}, token="bad")
        self.assertEqual(status, 401)

    def test_roundtrip_policy_change(self):
        """Set policy to prefer_local, then verify GET reflects it."""
        self._request("POST", "/cognition/preferences", body={"policy": "prefer_local"})
        status, data = self._request("GET", "/cognition/preferences")
        self.assertEqual(status, 200)
        self.assertEqual(data["policy"], "prefer_local")


# ---------------------------------------------------------------------------
# cognitive_trace in chat response — using real server
# ---------------------------------------------------------------------------

class TestCognitionTraceInChatResponse(unittest.TestCase):
    """cognitive_trace is present in chat response when ASSISTANT_LOCAL_LLM_ENABLED=true."""

    @classmethod
    def setUpClass(cls):
        from assistant_os.webhook_server import start_server_thread
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)
        from assistant_os.config import WEBHOOK_TOKEN
        cls.token = WEBHOOK_TOKEN

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _chat(self, text="hola"):
        headers = {
            "Content-Type":    "application/json",
            "X-Assistant-Token": self.token,
        }
        body = json.dumps({"text": text}).encode()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        conn.request("POST", "/chat/process", body=body, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        raw = resp.read().decode()
        conn.close()
        return status, json.loads(raw)

    def test_cognitive_trace_absent_by_default(self):
        """When ASSISTANT_LOCAL_LLM_ENABLED is not set, no cognitive_trace in response."""
        # patch dotenv so .env does not override env vars during config reload
        with patch.dict(os.environ, {
                "ASSISTANT_LOCAL_LLM_ENABLED": "false",
                "ASSISTANT_UI_SHOW_COGNITION": "false",
            }), \
             patch("dotenv.load_dotenv"):
            # Reimport config so the flag takes effect
            import importlib
            import assistant_os.config as cfg
            importlib.reload(cfg)
            status, data = self._chat()
        # Restore
        import importlib
        import assistant_os.config as cfg
        importlib.reload(cfg)

        self.assertEqual(status, 200)
        self.assertNotIn("cognitive_trace", data)

    def test_cognitive_trace_present_when_enabled(self):
        """When ASSISTANT_LOCAL_LLM_ENABLED=true, cognitive_trace.used=False on deterministic path."""
        with patch.dict(os.environ, {"ASSISTANT_LOCAL_LLM_ENABLED": "true"}):
            import importlib
            import assistant_os.config as cfg
            importlib.reload(cfg)
            status, data = self._chat()
        # Restore
        import importlib
        import assistant_os.config as cfg
        importlib.reload(cfg)

        self.assertEqual(status, 200)
        self.assertIn("cognitive_trace", data)
        ct = data["cognitive_trace"]
        self.assertFalse(ct["used"])
        self.assertEqual(ct["path"], "deterministic")


if __name__ == "__main__":
    unittest.main()
