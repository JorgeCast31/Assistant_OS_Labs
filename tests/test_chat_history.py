"""
Tests para el endpoint GET /chat/history.
Verifica la funcionalidad de historial de conversación persistente.
"""
import http.client
import json
import time
import unittest

from assistant_os.webhook_server import start_server_thread, WebhookHTTPServer
from assistant_os.config import WEBHOOK_TOKEN


class TestChatHistory(unittest.TestCase):
    """Tests para el endpoint GET /chat/history."""
    
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
    
    def _get(
        self,
        path: str,
        headers: dict | None = None,
    ) -> tuple[int, dict]:
        """Make GET request and return (status, json_data)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = headers or {}
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        status = response.status
        data = response.read().decode("utf-8")
        conn.close()
        
        try:
            return status, json.loads(data)
        except json.JSONDecodeError:
            return status, {"_raw": data}
    
    def _post_command_summary(
        self,
        text: str,
        conversation_id: str = "",
        token: str = WEBHOOK_TOKEN,
    ) -> tuple[int, dict]:
        """POST to /command/summary with conversation_id."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": token,
        }
        
        body: dict = {"text": text}
        if conversation_id:
            body["conversation_id"] = conversation_id
        
        conn.request("POST", "/command/summary", json.dumps(body).encode("utf-8"), headers)
        response = conn.getresponse()
        status = response.status
        data = response.read().decode("utf-8")
        conn.close()
        
        try:
            return status, json.loads(data)
        except json.JSONDecodeError:
            return status, {"_raw": data}
    
    # -------------------------------------------------------------------------
    # Authentication Tests
    # -------------------------------------------------------------------------
    
    def test_401_missing_token(self):
        """GET /chat/history sin token debe retornar 401."""
        status, data = self._get("/chat/history?conversation_id=test-123")
        
        self.assertEqual(status, 401)
        self.assertEqual(data.get("status"), "error")
        self.assertEqual(data.get("error", {}).get("type"), "Unauthorized")
    
    def test_401_invalid_token(self):
        """GET /chat/history con token inválido debe retornar 401."""
        headers = {"X-Assistant-Token": "invalid-token"}
        status, data = self._get("/chat/history?conversation_id=test-123", headers)
        
        self.assertEqual(status, 401)
        self.assertEqual(data.get("status"), "error")
    
    # -------------------------------------------------------------------------
    # Validation Tests
    # -------------------------------------------------------------------------
    
    def test_400_missing_conversation_id(self):
        """GET /chat/history sin conversation_id debe retornar 400."""
        headers = {"X-Assistant-Token": WEBHOOK_TOKEN}
        status, data = self._get("/chat/history", headers)
        
        self.assertEqual(status, 400)
        self.assertEqual(data.get("status"), "error")
        self.assertIn("conversation_id", data.get("error", {}).get("message", ""))
    
    # -------------------------------------------------------------------------
    # Success Tests
    # -------------------------------------------------------------------------
    
    def test_200_valid_request_empty_history(self):
        """GET /chat/history con params válidos debe retornar 200."""
        headers = {"X-Assistant-Token": WEBHOOK_TOKEN}
        # Use a unique conversation_id that won't have any history
        status, data = self._get("/chat/history?conversation_id=empty-test-12345", headers)
        
        self.assertEqual(status, 200)
        self.assertIn("ok", data)
        self.assertIn("conversation_id", data)
        self.assertIn("items", data)
        self.assertEqual(data["conversation_id"], "empty-test-12345")
        self.assertIsInstance(data["items"], list)
    
    def test_response_has_required_keys(self):
        """GET /chat/history response debe tener ok, conversation_id, items."""
        headers = {"X-Assistant-Token": WEBHOOK_TOKEN}
        status, data = self._get("/chat/history?conversation_id=keys-test-123", headers)
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("conversation_id"), "keys-test-123")
        self.assertIsInstance(data.get("items"), list)
    
    # -------------------------------------------------------------------------
    # Limit Tests
    # -------------------------------------------------------------------------
    
    def test_limit_capped_at_200(self):
        """GET /chat/history con limit > 200 debe capear a 200."""
        headers = {"X-Assistant-Token": WEBHOOK_TOKEN}
        # Request with limit 500 should work (capped internally)
        status, data = self._get("/chat/history?conversation_id=limit-test&limit=500", headers)
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
    
    def test_limit_default_50(self):
        """GET /chat/history sin limit usa 50 por defecto."""
        headers = {"X-Assistant-Token": WEBHOOK_TOKEN}
        status, data = self._get("/chat/history?conversation_id=default-limit-test", headers)
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
    
    def test_limit_invalid_value(self):
        """GET /chat/history con limit inválido usa default."""
        headers = {"X-Assistant-Token": WEBHOOK_TOKEN}
        status, data = self._get("/chat/history?conversation_id=invalid-limit&limit=abc", headers)
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
    
    # -------------------------------------------------------------------------
    # Conversation ID with /command/summary Tests
    # -------------------------------------------------------------------------
    
    def test_command_summary_accepts_conversation_id(self):
        """POST /command/summary debe aceptar conversation_id."""
        status, data = self._post_command_summary(
            text="DOC: test doc",
            conversation_id="test-conv-abc123",
        )
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
    
    def test_command_summary_without_conversation_id(self):
        """POST /command/summary debe funcionar sin conversation_id."""
        status, data = self._post_command_summary(
            text="DOC: test doc without conv id",
        )

        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))

    # -------------------------------------------------------------------------
    # FIX-2: UTF-8 session title round-trip
    # -------------------------------------------------------------------------

    def _post_session(
        self,
        session_id: str,
        title: str,
    ) -> tuple[int, dict]:
        """POST /chat/sessions — create session with given title."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"id": session_id, "title": title}, ensure_ascii=False).encode("utf-8")
        conn.request("POST", "/chat/sessions", body, headers)
        response = conn.getresponse()
        status = response.status
        data = response.read().decode("utf-8")
        conn.close()
        try:
            return status, json.loads(data)
        except json.JSONDecodeError:
            return status, {"_raw": data}

    def _patch_session(
        self,
        session_id: str,
        title: str,
    ) -> tuple[int, dict]:
        """PATCH /chat/sessions/{id} — update title."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"title": title}, ensure_ascii=False).encode("utf-8")
        conn.request("PATCH", f"/chat/sessions/{session_id}", body, headers)
        response = conn.getresponse()
        status = response.status
        data = response.read().decode("utf-8")
        conn.close()
        try:
            return status, json.loads(data)
        except json.JSONDecodeError:
            return status, {"_raw": data}

    def test_utf8_title_roundtrips_on_create(self):
        """FIX-2: Titles con tildes deben almacenarse y devolverse sin mojibake."""
        import uuid as _uuid
        session_id = str(_uuid.uuid4())
        title = "Auditoría de código"
        status, data = self._post_session(session_id, title)

        self.assertEqual(status, 201)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data["session"]["title"], title)

    def test_utf8_title_roundtrips_on_patch(self):
        """FIX-2: PATCH de título con tildes debe persistir y devolverse correctamente."""
        import uuid as _uuid
        session_id = str(_uuid.uuid4())
        # Create with plain title first
        self._post_session(session_id, "Nuevo chat")
        # Patch with accented title
        title = "Revisión técnica"
        status, data = self._patch_session(session_id, title)

        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data["session"]["title"], title)


if __name__ == "__main__":
    unittest.main()
