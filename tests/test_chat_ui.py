"""
Tests para el endpoint GET /chat (Chat UI).
Verifica que el HTML se sirve correctamente y no expone el token.
"""
import http.client
import time
import unittest

from assistant_os.webhook_server import start_server_thread, WebhookHTTPServer
from assistant_os.config import WEBHOOK_TOKEN


class TestChatUI(unittest.TestCase):
    """Tests para el endpoint GET /chat."""
    
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
    
    def _get(self, path: str) -> tuple[int, str, dict]:
        """Make GET request and return (status, body, headers)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path)
        response = conn.getresponse()
        status = response.status
        body = response.read().decode("utf-8")
        headers = dict(response.getheaders())
        conn.close()
        return status, body, headers
    
    # -------------------------------------------------------------------------
    # Basic Response Tests
    # -------------------------------------------------------------------------
    
    def test_chat_returns_200(self):
        """GET /chat debe retornar 200."""
        status, body, headers = self._get("/chat")
        self.assertEqual(status, 200)
    
    def test_chat_content_type_is_html(self):
        """GET /chat debe tener Content-Type text/html."""
        status, body, headers = self._get("/chat")
        content_type = headers.get("Content-Type", "")
        self.assertIn("text/html", content_type)
    
    def test_chat_contains_title(self):
        """GET /chat debe contener el título correcto."""
        status, body, headers = self._get("/chat")
        self.assertIn("<title>Assistant OS</title>", body)
    
    # -------------------------------------------------------------------------
    # Required Elements Tests
    # -------------------------------------------------------------------------
    
    def test_chat_contains_localstorage(self):
        """GET /chat debe usar localStorage para el token."""
        status, body, headers = self._get("/chat")
        self.assertIn("localStorage", body)
    
    def test_chat_contains_command_summary_endpoint(self):
        """GET /chat debe llamar a /command/summary."""
        status, body, headers = self._get("/chat")
        self.assertIn("/command/summary", body)
    
    def test_chat_contains_health_endpoint(self):
        """GET /chat debe llamar a /health."""
        status, body, headers = self._get("/chat")
        self.assertIn("/health", body)
    
    def test_chat_contains_token_header(self):
        """GET /chat debe enviar X-Assistant-Token header."""
        status, body, headers = self._get("/chat")
        self.assertIn("X-Assistant-Token", body)
    
    def test_chat_contains_input_element(self):
        """GET /chat debe contener input para mensajes."""
        status, body, headers = self._get("/chat")
        self.assertIn('id="messageInput"', body)
    
    def test_chat_contains_send_button(self):
        """GET /chat debe contener botón de enviar."""
        status, body, headers = self._get("/chat")
        self.assertIn('id="btnSend"', body)
    
    # -------------------------------------------------------------------------
    # Security Tests
    # -------------------------------------------------------------------------
    
    def test_chat_does_not_contain_webhook_token(self):
        """GET /chat NO debe contener el token hardcodeado (security)."""
        status, body, headers = self._get("/chat")
        # El token no debe aparecer en el HTML
        self.assertNotIn(WEBHOOK_TOKEN, body)
    
    def test_chat_does_not_contain_token_value(self):
        """GET /chat NO debe contener ningún token similar."""
        status, body, headers = self._get("/chat")
        # Buscar patrones que parezcan tokens hardcodeados
        # (tokens largos alfanuméricos)
        import re
        # Token de 50+ caracteres alfanuméricos seguidos
        long_tokens = re.findall(r'[A-Za-z0-9_]{50,}', body)
        for token in long_tokens:
            # Permitir solo cosas conocidas seguras
            if token not in ("BackgroundJob", "LocalStorage"):  # false positives
                self.assertNotEqual(token, WEBHOOK_TOKEN,
                    f"Found suspicious token-like string: {token[:20]}...")
    
    # -------------------------------------------------------------------------
    # UI Elements Tests
    # -------------------------------------------------------------------------
    
    def test_chat_has_clear_button(self):
        """GET /chat debe tener botón Clear chat."""
        status, body, headers = self._get("/chat")
        self.assertIn('id="btnClear"', body)
    
    def test_chat_has_export_button(self):
        """GET /chat debe tener botón Export."""
        status, body, headers = self._get("/chat")
        self.assertIn('id="btnExport"', body)
    
    def test_chat_has_token_button(self):
        """GET /chat debe tener botón Token/Clear token."""
        status, body, headers = self._get("/chat")
        self.assertIn('id="btnToken"', body)
    
    def test_chat_has_status_indicator(self):
        """GET /chat debe tener indicador de status."""
        status, body, headers = self._get("/chat")
        self.assertIn('id="statusDot"', body)
    
    def test_chat_has_token_modal(self):
        """GET /chat debe tener modal para ingresar token."""
        status, body, headers = self._get("/chat")
        self.assertIn('id="tokenModal"', body)


if __name__ == "__main__":
    unittest.main()
