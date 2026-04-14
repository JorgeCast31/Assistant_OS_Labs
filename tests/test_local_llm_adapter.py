import unittest
from unittest.mock import Mock, patch


class TestLocalLlmAdapterDisabled(unittest.TestCase):
    def test_disabled_returns_disabled_status(self):
        from assistant_os.mso import local_llm_adapter as adapter

        with patch.object(adapter, "MSO_ENABLED", False):
            result = adapter.consult_advisory({"text": "hola"})

        self.assertEqual(result["status"], "disabled")
        self.assertIn("disabled", (result.get("error") or "").lower())


class TestLocalLlmAdapterOllamaSuccess(unittest.TestCase):
    @patch("assistant_os.mso.local_llm_adapter.requests.post")
    def test_ollama_success_returns_advisory(self, mock_post):
        from assistant_os.mso import local_llm_adapter as adapter

        mock_response = Mock()
        mock_response.json.return_value = {
            "response": (
                '{"reasoning_summary":"resumen",'
                '"routing_hint":"WORK_QUERY",'
                '"confidence_note":"alta"}'
            )
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with (
            patch.object(adapter, "MSO_ENABLED", True),
            patch.object(adapter, "LOCAL_LLM_PROVIDER", "ollama"),
            patch.object(adapter, "LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434"),
            patch.object(adapter, "LOCAL_LLM_MODEL", "llama3.2:3b-instruct"),
            patch.object(adapter, "LOCAL_LLM_TIMEOUT_SECONDS", 1.5),
        ):
            result = adapter.consult_advisory({"text": "listar tareas"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["advisory"]["routing_hint"], "WORK_QUERY")
        self.assertEqual(result["model"], "llama3.2:3b-instruct")


class TestLocalLlmAdapterTimeout(unittest.TestCase):
    @patch("assistant_os.mso.local_llm_adapter.requests.post")
    def test_timeout_returns_error_status(self, mock_post):
        import requests
        from assistant_os.mso import local_llm_adapter as adapter

        mock_post.side_effect = requests.Timeout("boom")

        with (
            patch.object(adapter, "MSO_ENABLED", True),
            patch.object(adapter, "LOCAL_LLM_PROVIDER", "ollama"),
            patch.object(adapter, "LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434"),
            patch.object(adapter, "LOCAL_LLM_MODEL", "llama3.2:3b-instruct"),
            patch.object(adapter, "LOCAL_LLM_TIMEOUT_SECONDS", 0.5),
        ):
            result = adapter.consult_advisory({"text": "listar tareas"})

        self.assertEqual(result["status"], "error")
        self.assertIn("timeout", (result.get("error") or "").lower())


class TestLocalLlmProbe(unittest.TestCase):
    @patch("assistant_os.mso.local_llm_adapter.requests.post")
    @patch("assistant_os.mso.local_llm_adapter.requests.get")
    def test_probe_reports_reachability_and_roundtrip(self, mock_get, mock_post):
        from assistant_os.mso import local_llm_adapter as adapter

        mock_get_response = Mock()
        mock_get_response.raise_for_status.return_value = None
        mock_get_response.json.return_value = {
            "models": [{"name": "llama3.2:3b-instruct"}]
        }
        mock_get.return_value = mock_get_response

        mock_post_response = Mock()
        mock_post_response.raise_for_status.return_value = None
        mock_post_response.json.return_value = {
            "response": (
                '{"reasoning_summary":"ok",'
                '"routing_hint":"NONE",'
                '"confidence_note":"ok"}'
            )
        }
        mock_post.return_value = mock_post_response

        with (
            patch.object(adapter, "MSO_ENABLED", True),
            patch.object(adapter, "LOCAL_LLM_PROVIDER", "ollama"),
            patch.object(adapter, "LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434"),
            patch.object(adapter, "LOCAL_LLM_MODEL", "llama3.2:3b-instruct"),
            patch.object(adapter, "LOCAL_LLM_TIMEOUT_SECONDS", 1.0),
        ):
            result = adapter.probe_local_llm(roundtrip=True)

        self.assertTrue(result["enabled"])
        self.assertTrue(result["reachable"])
        self.assertTrue(result["model_available"])
        self.assertTrue(result["roundtrip_ok"])

