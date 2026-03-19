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


class TestChatUIConversationId(unittest.TestCase):
    """Tests para verificar que el chat UI incluye conversation_id."""
    
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
    
    def _get_chat_html(self) -> str:
        """Get the /chat HTML content."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/chat")
        response = conn.getresponse()
        html = response.read().decode("utf-8")
        conn.close()
        return html
    
    def test_chat_contains_conversation_id_key(self):
        """GET /chat debe contener referencia a conversation_id en localStorage."""
        html = self._get_chat_html()
        self.assertIn("assistant_os.conversation_id", html)
    
    def test_chat_contains_chat_history_endpoint(self):
        """GET /chat debe contener referencia a /chat/history."""
        html = self._get_chat_html()
        self.assertIn("/chat/history", html)
    
    def test_chat_contains_new_session_button(self):
        """GET /chat debe contener botón New session."""
        html = self._get_chat_html()
        self.assertIn("btnNewSession", html)
    
    def test_chat_contains_reload_button(self):
        """GET /chat debe contener botón Reload."""
        html = self._get_chat_html()
        self.assertIn("btnReload", html)
    
    def test_chat_contains_session_display(self):
        """GET /chat debe mostrar session ID."""
        html = self._get_chat_html()
        self.assertIn("sessionId", html)
        self.assertIn("Session:", html)
    
    def test_chat_contains_generate_uuid(self):
        """GET /chat debe contener función generateUUID."""
        html = self._get_chat_html()
        self.assertIn("generateUUID", html)
    
    def test_chat_sends_conversation_id_in_request(self):
        """GET /chat debe enviar conversation_id en el request body."""
        html = self._get_chat_html()
        # Check that the fetch body includes conversation_id
        self.assertIn("conversation_id: state.conversationId", html)
    
    def test_chat_contains_copy_session_button(self):
        """GET /chat debe contener botón Copy session."""
        html = self._get_chat_html()
        self.assertIn("btnCopySession", html)
        self.assertIn("Copy session ID", html)
    
    def test_chat_contains_join_session_button(self):
        """GET /chat debe contener botón Join session."""
        html = self._get_chat_html()
        self.assertIn("btnJoinSession", html)
        self.assertIn("Join session", html)
    
    def test_chat_contains_safe_area_inset(self):
        """GET /chat debe incluir safe-area-inset para iOS."""
        html = self._get_chat_html()
        self.assertIn("safe-area-inset-bottom", html)
    
    def test_chat_contains_setvh_script(self):
        """GET /chat debe incluir script setVH para iOS viewport fix."""
        html = self._get_chat_html()
        self.assertIn("setVH", html)
        self.assertIn("window.innerHeight", html)
    
    def test_chat_contains_dvh_support(self):
        """GET /chat debe incluir soporte para 100dvh."""
        html = self._get_chat_html()
        self.assertIn("100dvh", html)


if __name__ == "__main__":
    unittest.main()
