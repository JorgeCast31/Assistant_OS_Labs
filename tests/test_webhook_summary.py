"""
Tests para el endpoint /command/summary del webhook server.
Valida resúmenes legibles para consumo móvil (iPhone Shortcuts).
"""
import http.client
import json
import time
import unittest
from typing import Any, Dict, Tuple

from assistant_os.webhook_server import start_server_thread, WebhookHTTPServer
from assistant_os.config import WEBHOOK_TOKEN, WEBHOOK_MAX_BYTES
from assistant_os.summary import summarize, SummaryResponse


class TestWebhookSummaryEndpoint(unittest.TestCase):
    """Tests para el endpoint POST /command/summary."""
    
    server: WebhookHTTPServer
    port: int
    
    @classmethod
    def setUpClass(cls) -> None:
        """Start server in background thread."""
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)
    
    @classmethod
    def tearDownClass(cls) -> None:
        """Shutdown server."""
        cls.server.shutdown()
        cls.server.server_close()
    
    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict | None = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """Make HTTP request and return (status_code, json_or_text)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = headers or {}
        
        if body is not None:
            conn.request(method, path, body=body, headers=headers)
        else:
            conn.request(method, path, headers=headers)
        
        response = conn.getresponse()
        status = response.status
        data = response.read().decode("utf-8")
        conn.close()
        
        try:
            return status, json.loads(data)
        except json.JSONDecodeError:
            return status, {"_raw": data}
    
    def _post_summary(
        self,
        text: str,
        token: str | None = WEBHOOK_TOKEN,
        raw: bool = False,
    ) -> Tuple[int, Dict[str, Any]]:
        """Helper to POST /command/summary with proper headers."""
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Assistant-Token"] = token
        
        body = json.dumps({"text": text}).encode("utf-8")
        path = "/command/summary"
        if raw:
            path += "?raw=1"
        
        return self._request("POST", path, body, headers)
    
    # -------------------------------------------------------------------------
    # Authentication Tests
    # -------------------------------------------------------------------------
    
    def test_401_missing_token(self):
        """POST /command/summary sin token debe retornar 401."""
        headers = {"Content-Type": "application/json"}
        body = json.dumps({"text": "CODE: test"}).encode("utf-8")
        
        status, data = self._request("POST", "/command/summary", body, headers)
        
        self.assertEqual(status, 401)
        # Error response should still have summary-like structure or error
        self.assertIn("error", data)
    
    # -------------------------------------------------------------------------
    # Success Tests - Structure Validation
    # -------------------------------------------------------------------------
    
    def test_200_valid_request_has_expected_keys(self):
        """POST /command/summary debe retornar ok, title, summary, details."""
        status, data = self._post_summary("DOC: generate readme")
        
        self.assertEqual(status, 200)
        self.assertIn("ok", data)
        self.assertIn("title", data)
        self.assertIn("summary", data)
        self.assertIn("details", data)
        
        self.assertIsInstance(data["ok"], bool)
        self.assertIsInstance(data["title"], str)
        self.assertIsInstance(data["summary"], str)
        self.assertIsInstance(data["details"], dict)
    
    def test_raw_param_includes_raw_response(self):
        """?raw=1 debe incluir la response original en 'raw'."""
        status, data = self._post_summary("DOC: generate readme", raw=True)
        
        self.assertEqual(status, 200)
        self.assertIn("raw", data)
        self.assertIsNotNone(data["raw"])
        # raw should be a full Response
        self.assertIn("context_id", data["raw"])
        self.assertIn("agent", data["raw"])
        self.assertIn("status", data["raw"])
    
    def test_no_raw_param_excludes_raw(self):
        """Sin ?raw=1, 'raw' debe ser null."""
        status, data = self._post_summary("DOC: generate readme", raw=False)
        
        self.assertEqual(status, 200)
        self.assertIn("raw", data)
        self.assertIsNone(data["raw"])
    
    # -------------------------------------------------------------------------
    # Body Size Tests
    # -------------------------------------------------------------------------
    
    def test_413_body_too_large(self):
        """POST /command/summary con body > 16KB debe retornar 413."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        large_text = "x" * (WEBHOOK_MAX_BYTES + 100)
        body = json.dumps({"text": large_text}).encode("utf-8")
        
        status, data = self._request("POST", "/command/summary", body, headers)
        
        self.assertEqual(status, 413)
    
    # -------------------------------------------------------------------------
    # Agent-Specific Summary Tests
    # -------------------------------------------------------------------------
    
    def test_code_agent_summary_uses_canonical_path(self):
        """A1.5: CODE: prefix routes through canonical orchestrator path.

        After A1.5, all prefix text goes through handle_request → NL classifier.
        The summary is produced by _summarize_classifier(), not _summarize_code().
        Verify the response structure is valid and agent is "classifier".
        """
        status, data = self._post_summary("CODE: crea modulo ejemplo simple")

        self.assertEqual(status, 200)
        self.assertIn("ok", data)
        self.assertIn("title", data)
        self.assertIn("summary", data)
        self.assertIn("details", data)
        # A1.5: canonical path uses classifier, not legacy "code" agent
        self.assertIn("classifier", data["title"].lower(), (
            f"A1.5: title must reflect canonical classifier path, got: {data['title']!r}"
        ))
        # Summary must have some content
        self.assertTrue(len(data["summary"]) > 0, "Summary must not be empty")
    
    def test_doc_agent_summary_uses_canonical_path(self):
        """A1.5: DOC: prefix routes through canonical orchestrator path.

        After A1.5, all prefix text goes through handle_request → NL classifier.
        Verify the response structure is valid and agent is "classifier".
        """
        status, data = self._post_summary("DOC: generate readme")

        self.assertEqual(status, 200)
        self.assertIn("ok", data)
        self.assertIn("title", data)
        self.assertIn("summary", data)
        self.assertIn("details", data)
        # A1.5: canonical path uses classifier, not legacy "doc" agent
        self.assertIn("classifier", data["title"].lower(), (
            f"A1.5: title must reflect canonical classifier path, got: {data['title']!r}"
        ))
        self.assertTrue(len(data["summary"]) > 0, "Summary must not be empty")
    
    def test_jobs_agent_summary_uses_canonical_path(self):
        """A1.5: JOBS: prefix routes through canonical orchestrator path.

        After A1.5, all prefix text goes through handle_request → NL classifier.
        Verify the response structure is valid and agent is "classifier".
        """
        status, data = self._post_summary("JOBS: buscar Python developer")

        self.assertEqual(status, 200)
        self.assertIn("ok", data)
        self.assertIn("title", data)
        self.assertIn("summary", data)
        self.assertIn("details", data)
        # A1.5: canonical path uses classifier, not legacy "jobs" agent
        self.assertIn("classifier", data["title"].lower(), (
            f"A1.5: title must reflect canonical classifier path, got: {data['title']!r}"
        ))
        self.assertTrue(len(data["summary"]) > 0, "Summary must not be empty")
    
    def test_biz_agent_summary_uses_canonical_path(self):
        """A1.5: BIZ: prefix routes through canonical orchestrator path.

        After A1.5, all prefix text goes through handle_request → NL classifier.
        Verify the response structure is valid and agent is "classifier".
        """
        status, data = self._post_summary("BIZ: analizar competencia AI")

        self.assertEqual(status, 200)
        self.assertIn("ok", data)
        self.assertIn("title", data)
        self.assertIn("summary", data)
        self.assertIn("details", data)
        # A1.5: canonical path uses classifier, not legacy "biz" agent
        self.assertIn("classifier", data["title"].lower(), (
            f"A1.5: title must reflect canonical classifier path, got: {data['title']!r}"
        ))
        self.assertTrue(len(data["summary"]) > 0, "Summary must not be empty")
    
    # -------------------------------------------------------------------------
    # Error Summary Tests
    # -------------------------------------------------------------------------
    
    def test_unknown_prefix_handled_by_canonical_path(self):
        """A1.5: Unknown prefixes are handled by the canonical orchestrator path.

        Before A1.5, unknown prefixes like "INVALID:" were rejected with 400.
        After A1.5, ALL text (including unknown prefixes) routes through
        handle_request → NL classifier, which processes any text. The response
        is a valid SummaryResponse, not a rejection.
        """
        status, data = self._post_summary("INVALID: this should fail")

        # A1.5: canonical path processes any text; no upfront prefix rejection
        self.assertEqual(status, 200)
        self.assertIn("ok", data)
        self.assertIn("title", data)
        self.assertIn("summary", data)
        self.assertTrue(len(data["summary"]) > 0, "Summary must not be empty")


class TestSummarizeFunction(unittest.TestCase):
    """Tests para la función summarize() directamente."""
    
    def test_summarize_ok_response(self):
        """summarize debe manejar response OK."""
        response = {
            "context_id": "test-123",
            "agent": "doc",
            "status": "ok",
            "output": {
                "document": {
                    "id": "DOC-001",
                    "title": "Test Doc",
                    "local_path": "docs/test.md",
                    "status": "draft",
                }
            },
            "error": None,
            "ts": "2026-02-24T00:00:00Z",
        }
        
        result = summarize(response, include_raw=False)
        
        self.assertTrue(result["ok"])
        self.assertIn("doc", result["title"].lower())
        self.assertIsNone(result["raw"])
    
    def test_summarize_error_response(self):
        """summarize debe manejar response de error."""
        response = {
            "context_id": "test-456",
            "agent": "webhook",
            "status": "error",
            "output": {},
            "error": {"type": "BadRequest", "message": "Invalid input"},
            "ts": "2026-02-24T00:00:00Z",
        }
        
        result = summarize(response, include_raw=False)
        
        self.assertFalse(result["ok"])
        self.assertIn("ERROR", result["title"])
        self.assertIn("BadRequest", result["summary"])
    
    def test_summarize_include_raw(self):
        """summarize con include_raw=True debe incluir response original."""
        response = {
            "context_id": "test-789",
            "agent": "code",
            "status": "ok",
            "output": {"module_name": "test"},
            "error": None,
            "ts": "2026-02-24T00:00:00Z",
        }
        
        result = summarize(response, include_raw=True)
        
        self.assertIsNotNone(result["raw"])
        self.assertEqual(result["raw"]["context_id"], "test-789")
    
    def test_summarize_code_agent_details(self):
        """summarize de CodeAgent debe extraer detalles relevantes."""
        response = {
            "context_id": "code-001",
            "agent": "code",
            "status": "ok",
            "output": {
                "module_name": "my_module",
                "paths": {"module": "src/my_module.py", "tests": "tests/test_my_module.py"},
                "iterations_used": 2,
                "tests": {"status": "passed", "summary": "Ran 5 tests in 0.1s"},
                "files_created": ["src/my_module.py", "tests/test_my_module.py"],
            },
            "error": None,
            "ts": "2026-02-24T00:00:00Z",
        }
        
        result = summarize(response, include_raw=False)
        
        self.assertTrue(result["ok"])
        self.assertEqual(result["details"]["module_name"], "my_module")
        self.assertEqual(result["details"]["iterations"], 2)
        self.assertEqual(result["details"]["tests_status"], "passed")


if __name__ == "__main__":
    unittest.main()
