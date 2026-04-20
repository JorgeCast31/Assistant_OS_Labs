"""
Tests para el webhook server.
Usa http.client (stdlib) para hacer requests.
"""
import http.client
import json
import time
import unittest
from unittest.mock import patch

from assistant_os.webhook_server import start_server_thread, WebhookHTTPServer
from assistant_os.config import WEBHOOK_TOKEN, WEBHOOK_MAX_BYTES
from typing import Any, Dict, Tuple


class TestWebhookServer(unittest.TestCase):
    """Tests para el servidor webhook HTTP."""
    
    server: WebhookHTTPServer
    port: int
    
    @classmethod
    def setUpClass(cls) -> None:
        """Start server in background thread."""
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        # Give server time to start
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
    
    def _post_command(
        self,
        text: str,
        token: str | None = WEBHOOK_TOKEN,
        content_type: str = "application/json",
    ) -> tuple[int, dict]:
        """Helper to POST /command with proper headers."""
        headers = {"Content-Type": content_type}
        if token is not None:
            headers["X-Assistant-Token"] = token
        
        body = json.dumps({"text": text}).encode("utf-8")
        return self._request("POST", "/command", body, headers)
    
    # -------------------------------------------------------------------------
    # Authentication Tests
    # -------------------------------------------------------------------------
    
    def test_401_missing_token(self):
        """POST /command sin token debe retornar 401."""
        headers = {"Content-Type": "application/json"}
        body = json.dumps({"text": "CODE: test"}).encode("utf-8")
        
        status, data = self._request("POST", "/command", body, headers)
        
        self.assertEqual(status, 401)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["error"]["type"], "Unauthorized")
        self.assertIn("Missing", data["error"]["message"])
    
    def test_401_invalid_token(self):
        """POST /command con token inválido debe retornar 401."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": "wrong-token",
        }
        body = json.dumps({"text": "CODE: test"}).encode("utf-8")
        
        status, data = self._request("POST", "/command", body, headers)
        
        self.assertEqual(status, 401)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["error"]["type"], "Unauthorized")
    
    # -------------------------------------------------------------------------
    # Success Tests
    # -------------------------------------------------------------------------
    
    def test_200_valid_request(self):
        """POST /command con token válido y body correcto debe retornar 200."""
        status, data = self._post_command("DOC: generate readme")
        
        self.assertEqual(status, 200)
        self.assertIn("status", data)
        self.assertIn(data["status"], ("ok", "pending"))
        # A1.5: All prefix text routes through the canonical orchestrator path
        # (handle_request → NL classifier). Legacy agent-specific values like
        # "doc" are no longer returned; verify structural response instead.
        self.assertIn("agent", data)
        self.assertIn("context_id", data)
    
    def test_response_structure(self):
        """Response debe tener la estructura completa del TypedDict."""
        status, data = self._post_command("JOBS: buscar Python")
        
        self.assertEqual(status, 200)
        # Verify all required fields
        self.assertIn("context_id", data)
        self.assertIn("agent", data)
        self.assertIn("status", data)
        self.assertIn("output", data)
        self.assertIn("ts", data)
        # error can be None or dict
        self.assertIn("error", data)
    
    # -------------------------------------------------------------------------
    # Bad Request Tests
    # -------------------------------------------------------------------------
    
    def test_400_invalid_json(self):
        """POST /command con JSON inválido debe retornar 400."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = b"not valid json{"
        
        status, data = self._request("POST", "/command", body, headers)
        
        self.assertEqual(status, 400)
        self.assertEqual(data["status"], "error")
        self.assertIn("JSON", data["error"]["message"])
    
    def test_400_missing_text_field(self):
        """POST /command sin campo 'text' debe retornar 400."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"command": "CODE: test"}).encode("utf-8")  # wrong field
        
        status, data = self._request("POST", "/command", body, headers)
        
        self.assertEqual(status, 400)
        self.assertEqual(data["status"], "error")
        self.assertIn("text", data["error"]["message"])
    
    def test_400_text_not_string(self):
        """POST /command con 'text' no string debe retornar 400."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"text": 12345}).encode("utf-8")
        
        status, data = self._request("POST", "/command", body, headers)
        
        self.assertEqual(status, 400)
        self.assertEqual(data["status"], "error")
        self.assertIn("string", data["error"]["message"])
    
    def test_400_wrong_content_type(self):
        """POST /command sin Content-Type JSON debe retornar 400."""
        headers = {
            "Content-Type": "text/plain",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = b'{"text": "CODE: test"}'
        
        status, data = self._request("POST", "/command", body, headers)
        
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["type"], "BadRequest")
    
    # -------------------------------------------------------------------------
    # Body Size Tests
    # -------------------------------------------------------------------------
    
    def test_413_body_too_large(self):
        """POST /command con body > 16KB debe retornar 413."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        # Create body larger than WEBHOOK_MAX_BYTES
        large_text = "x" * (WEBHOOK_MAX_BYTES + 100)
        body = json.dumps({"text": large_text}).encode("utf-8")
        
        status, data = self._request("POST", "/command", body, headers)
        
        self.assertEqual(status, 413)
        self.assertEqual(data["error"]["type"], "PayloadTooLarge")
    
    # -------------------------------------------------------------------------
    # Method Tests
    # -------------------------------------------------------------------------
    
    def test_405_get_on_command(self):
        """GET /command debe retornar 405."""
        headers = {"X-Assistant-Token": WEBHOOK_TOKEN}
        
        status, data = self._request("GET", "/command", headers=headers)
        
        self.assertEqual(status, 405)
        self.assertEqual(data["error"]["type"], "MethodNotAllowed")
    
    def test_health_endpoint(self):
        """GET /health debe retornar 200."""
        status, data = self._request("GET", "/health")
        
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertIn("service", data)
    
    # -------------------------------------------------------------------------
    # 404 Tests
    # -------------------------------------------------------------------------
    
    def test_404_unknown_path(self):
        """POST a path desconocido debe retornar 404."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        
        status, data = self._request("POST", "/unknown", b"{}", headers)
        
        self.assertEqual(status, 404)
        self.assertEqual(data["error"]["type"], "NotFound")

    # -------------------------------------------------------------------------
    # Chaperon Alias Tests
    # -------------------------------------------------------------------------
    
    def test_chaperon_alias_routes_to_fin_chaperon(self):
        """POST /chaperon should work as alias for /fin/chaperon."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"text": "test", "domain": "FIN"}).encode("utf-8")
        
        # Both endpoints should return same response shape (200 with ok field)
        status1, data1 = self._request("POST", "/chaperon", body, headers)
        status2, data2 = self._request("POST", "/fin/chaperon", body, headers)
        
        self.assertEqual(status1, status2, "Both endpoints should return same status")
        self.assertEqual(status1, 200)
        self.assertIn("ok", data1)
        self.assertIn("ok", data2)

    # -------------------------------------------------------------------------
    # Prefix-Free Routing Tests
    # -------------------------------------------------------------------------
    
    def test_command_summary_without_prefix_no_invalid_prefix(self):
        """POST /command/summary con texto sin prefijo NO debe retornar InvalidPrefix."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"text": "estado sobre tareas de consultoria"}).encode("utf-8")
        
        status, data = self._request("POST", "/command/summary", body, headers)
        
        # Should NOT be InvalidPrefix error
        if not data.get("ok", True):
            # If there's an error, it should NOT be InvalidPrefix
            error_type = data.get("details", {}).get("error_type", "")
            self.assertNotEqual(error_type, "InvalidPrefix", 
                              "Should not return InvalidPrefix for text without prefix")
        
        # Response should have summary structure
        self.assertIn("title", data)
        self.assertIn("summary", data)
    
    def test_command_without_prefix_routes_to_classifier(self):
        """POST /command con texto sin prefijo debe rutear vía classify."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"text": "tareas de consultoria"}).encode("utf-8")
        
        status, data = self._request("POST", "/command", body, headers)
        
        # Should NOT be InvalidPrefix error
        if data.get("status") == "error":
            error_type = data.get("error", {}).get("type", "")
            self.assertNotEqual(error_type, "InvalidPrefix",
                              "Should not return InvalidPrefix for text without prefix")
    
    def test_command_with_prefix_uses_canonical_routing(self):
        """POST /command con prefijo CODE: debe usar routing canónico (A1.5).

        A1.5 removed _gated_legacy_route. All prefix text now routes through
        _route_text_by_classification → handle_request (canonical path). The
        response will contain agent="classifier" rather than a legacy agent name.
        Verify a valid structured response is returned, not a legacy bypass.
        """
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"text": "CODE: crear modulo test"}).encode("utf-8")

        status, data = self._request("POST", "/command", body, headers)

        # Must return a structured response (not an unhandled error)
        self.assertIn(status, (200, 202), f"Expected 200/202, got {status}: {data}")
        self.assertIn("agent", data, "Response must include 'agent' field")
        # Must NOT return legacy agent values (prefix bypass was removed)
        legacy_agents = {"doc", "code", "jobs", "biz"}
        self.assertNotIn(
            data.get("agent"),
            legacy_agents,
            f"agent={data.get('agent')!r} indicates a legacy bypass is still active (A1.5)",
        )
    
    # -------------------------------------------------------------------------
    # GET /work/schema Robustness Tests
    # -------------------------------------------------------------------------
    
    def test_work_schema_get_returns_json_not_connection_close(self):
        """GET /work/schema debe retornar JSON (200 o 404), nunca cerrar conexión."""
        headers = {
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        
        # Should return JSON regardless of whether Notion is available
        # Must NOT close connection unexpectedly
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("GET", "/work/schema", headers=headers)
            response = conn.getresponse()
            status = response.status
            data = response.read().decode("utf-8")
            conn.close()
            
            # Status should be 200 or 404 or 500, but always with body
            self.assertIn(status, [200, 401, 404, 500], "Should return valid HTTP status")
            
            # Body should be JSON
            parsed = json.loads(data)
            self.assertIsInstance(parsed, dict, "Response should be JSON object")
            
        except (ConnectionResetError, BrokenPipeError) as e:
            self.fail(f"GET /work/schema closed connection unexpectedly: {e}")
    
    def test_work_schema_get_has_error_structure_on_failure(self):
        """GET /work/schema en caso de error debe retornar estructura de error."""
        headers = {
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        
        status, data = self._request("GET", "/work/schema", None, headers)
        
        # If not 200, should have error structure
        if status != 200:
            self.assertIn("error", data, "Error responses should have 'error' field")
            if isinstance(data.get("error"), dict):
                self.assertIn("type", data["error"], "Error should have 'type'")
                self.assertIn("message", data["error"], "Error should have 'message'")


class TestCommandSummaryNaturalLanguage(unittest.TestCase):
    """Tests for /command/summary with natural language (Plan-first)."""
    
    server: WebhookHTTPServer
    port: int
    
    @classmethod
    def setUpClass(cls) -> None:
        """Start server in background thread."""
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)
        # Isolate from real Notion: these tests validate routing, not Notion integration
        cls._qdb_patcher = patch(
            "assistant_os.webhook_server.query_work_db",
            return_value={"ok": True, "items": [], "total": 0},
        )
        cls._qdb_patcher.start()

    @classmethod
    def tearDownClass(cls) -> None:
        """Shutdown server."""
        cls._qdb_patcher.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def _post_summary(
        self,
        text: str,
        include_raw: bool = False,
    ) -> tuple[int, dict]:
        """Helper to POST /command/summary."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"text": text}).encode("utf-8")
        path = "/command/summary" + ("?raw=1" if include_raw else "")
        
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        status = response.status
        data = response.read().decode("utf-8")
        conn.close()
        
        return status, json.loads(data)
    
    def test_natural_language_consultoria_returns_ok(self):
        """
        POST /command/summary con lenguaje natural debe retornar ok.
        Input: "estado sobre tareas de consultoría"
        Asserts: ok=true, title contains "work" or action=WORK_QUERY
        """
        status, data = self._post_summary("estado sobre tareas de consultoría", include_raw=True)
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"), f"Expected ok=true, got: {data}")
        
        # Title should contain work or WORK_QUERY
        title = data.get("title", "").lower()
        self.assertTrue(
            "work" in title or "work_query" in title.lower(),
            f"Expected title to contain 'work', got: {title}"
        )
    
    def test_natural_language_consultoria_has_filters(self):
        """
        /command/summary con 'consultoría' debe incluir filtro project.
        """
        status, data = self._post_summary("tareas consultoría", include_raw=True)
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        
        # Check details.filters or raw.output.filters
        details = data.get("details", {})
        raw = data.get("raw", {})
        output = raw.get("output", {}) if raw else {}
        filters = output.get("filters", {})
        
        # Should have project filter with Consultoría
        has_consultoria = (
            "Consultoría" in str(details) or
            filters.get("project") == "Consultoría"
        )
        self.assertTrue(has_consultoria, f"Expected project=Consultoría, got details={details}, filters={filters}")
    
    def test_natural_language_tareas_routes_to_work_query(self):
        """
        'tareas' keyword should route to WORK_QUERY action.
        """
        status, data = self._post_summary("tareas pendientes", include_raw=True)
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        
        # Check that action is WORK_QUERY
        raw = data.get("raw", {})
        output = raw.get("output", {}) if raw else {}
        plan = output.get("plan", {})
        action = plan.get("action", "")
        
        self.assertEqual(action, "WORK_QUERY", f"Expected action=WORK_QUERY, got: {action}")
    
    def test_no_prefix_required(self):
        """
        /command/summary should NOT require CODE:/DOC:/JOBS:/BIZ: prefix.
        Natural language should work directly.
        """
        status, data = self._post_summary("qué hay pendiente hoy")
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"), f"Expected ok=true without prefix, got: {data}")
        
        # Should NOT be InvalidPrefix error
        self.assertNotIn("InvalidPrefix", str(data))


class TestWorkCreateRouting(unittest.TestCase):
    """
    Integration tests for WORK_CREATE routing via HTTP endpoints.
    
    These tests verify that both /command and /command/summary correctly:
    1. Detect creation intent (crea, añade, agrega + tarea)
    2. Route to WORK_CREATE action (NOT WORK_QUERY)
    3. Return requires_confirmation=True
    4. Parse task fields correctly
    """
    
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
    
    def _post_command(self, text: str, include_raw: bool = False) -> tuple[int, dict]:
        """Helper to POST /command."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"text": text}).encode("utf-8")
        
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/command", body=body, headers=headers)
        response = conn.getresponse()
        status = response.status
        data = response.read().decode("utf-8")
        conn.close()
        
        return status, json.loads(data)
    
    def _post_summary(self, text: str, include_raw: bool = False) -> tuple[int, dict]:
        """Helper to POST /command/summary."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"text": text}).encode("utf-8")
        path = "/command/summary" + ("?raw=1" if include_raw else "")
        
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        status = response.status
        data = response.read().decode("utf-8")
        conn.close()
        
        return status, json.loads(data)
    
    def test_command_create_task_routes_to_work_create(self):
        """
        POST /command with task creation text must route to WORK_CREATE.
        
        This is the regression test for the bug where /command was returning
        WORK_QUERY instead of WORK_CREATE for task creation text.
        """
        text = "Crea una tarea en WORK: Título: Test Final. Proyecto: X. Status: INBOX. Prioridad: P3. Carga cognitiva: Media. Due: null."
        
        status, data = self._post_command(text)
        
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "pending", 
                        f"Expected status=pending for confirmation, got: {data.get('status')}")
        self.assertEqual(data.get("agent"), "interpreter",
                        f"Expected agent=interpreter, got: {data.get('agent')}")
        
        # Check output type
        output = data.get("output", {})
        self.assertEqual(output.get("type"), "plan_confirmation_required",
                        f"Expected type=plan_confirmation_required, got: {output.get('type')}")
        
        # Check plan action
        plan = output.get("plan", {})
        self.assertEqual(plan.get("action"), "WORK_CREATE",
                        f"BUG: Expected action=WORK_CREATE, got: {plan.get('action')}")
        self.assertTrue(plan.get("requires_confirmation"),
                       f"Expected requires_confirmation=True")
        
        # Check filters
        filters = plan.get("filters", {})
        self.assertEqual(filters.get("title"), "Test Final")
        self.assertEqual(filters.get("project"), "X")
        self.assertEqual(filters.get("status"), "INBOX")
    
    def test_command_summary_create_task_routes_to_work_create(self):
        """
        POST /command/summary with task creation text must route to WORK_CREATE.
        """
        text = "Crea una tarea en WORK: Título: Test Summary. Proyecto: Y. Status: INBOX."
        
        status, data = self._post_summary(text, include_raw=True)
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        
        # Title should contain WORK_CREATE
        title = data.get("title", "")
        self.assertIn("WORK_CREATE", title,
                     f"Expected title to contain WORK_CREATE, got: {title}")
        
        # Summary should mention creating task
        summary = data.get("summary", "")
        self.assertIn("Crear tarea", summary,
                     f"Expected summary to contain 'Crear tarea', got: {summary}")
        
        # Check raw output if available
        raw = data.get("raw", {})
        if raw:
            output = raw.get("output", {})
            plan = output.get("plan", {})
            self.assertEqual(plan.get("action"), "WORK_CREATE")
    
    def test_anade_tarea_routes_to_work_create(self):
        """'Añade una tarea: ...' debe rutearse a WORK_CREATE."""
        text = "Añade una tarea: Revisar código del proyecto"
        
        status, data = self._post_command(text)
        
        self.assertEqual(status, 200)
        output = data.get("output", {})
        plan = output.get("plan", {})
        
        self.assertEqual(plan.get("action"), "WORK_CREATE",
                        f"Expected action=WORK_CREATE for 'Añade', got: {plan.get('action')}")
    
    def test_agrega_tarea_routes_to_work_create(self):
        """'Agrega tarea: ...' debe rutearse a WORK_CREATE."""
        text = "Agrega tarea: Llamar al cliente"
        
        status, data = self._post_command(text)
        
        self.assertEqual(status, 200)
        output = data.get("output", {})
        plan = output.get("plan", {})
        
        self.assertEqual(plan.get("action"), "WORK_CREATE",
                        f"Expected action=WORK_CREATE for 'Agrega', got: {plan.get('action')}")
    
    @patch("assistant_os.webhook_server.query_work_db",
           return_value={"ok": True, "items": [], "total": 0})
    def test_tareas_query_still_routes_to_work_query(self, _mock_qdb):
        """'tareas de consultoria' (without create verb) must route to WORK_QUERY."""
        text = "tareas de consultoria"
        
        status, data = self._post_command(text)
        
        self.assertEqual(status, 200)
        # For WORK_QUERY, status should be "ok" (not "pending")
        self.assertEqual(data.get("status"), "ok",
                        f"Expected status=ok for WORK_QUERY, got: {data.get('status')}")
        
        output = data.get("output", {})
        self.assertEqual(output.get("type"), "work_query",
                        f"Expected type=work_query, got: {output.get('type')}")


if __name__ == "__main__":
    unittest.main()
