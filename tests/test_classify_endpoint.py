"""
Tests para el endpoint POST /classify.
"""
import http.client
import json
import time
import unittest

from assistant_os.webhook_server import start_server_thread, WebhookHTTPServer
from assistant_os.config import WEBHOOK_TOKEN


class TestClassifyEndpoint(unittest.TestCase):
    """Tests para el endpoint POST /classify."""
    
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
    ) -> tuple[int, dict]:
        """Make HTTP request and return (status_code, json_response)."""
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
    
    def _post_classify(
        self,
        body: dict | str | bytes,
        token: str | None = WEBHOOK_TOKEN,
        content_type: str = "application/json",
    ) -> tuple[int, dict]:
        """Helper to POST /classify."""
        headers = {"Content-Type": content_type}
        if token is not None:
            headers["X-Assistant-Token"] = token
        
        if isinstance(body, dict):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        
        return self._request("POST", "/classify", body, headers)
    
    # -------------------------------------------------------------------------
    # Authentication Tests
    # -------------------------------------------------------------------------
    
    def test_401_missing_token(self):
        """POST /classify sin token debe retornar 401."""
        status, data = self._post_classify({"text": "test"}, token=None)
        
        self.assertEqual(status, 401)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["error"]["type"], "Unauthorized")
        self.assertIn("Missing", data["error"]["message"])
    
    def test_401_invalid_token(self):
        """POST /classify con token inválido debe retornar 401."""
        status, data = self._post_classify({"text": "test"}, token="wrong-token")
        
        self.assertEqual(status, 401)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["error"]["type"], "Unauthorized")
    
    # -------------------------------------------------------------------------
    # Input Validation Tests
    # -------------------------------------------------------------------------
    
    def test_400_invalid_json(self):
        """POST /classify con JSON inválido debe retornar 400."""
        status, data = self._post_classify(b"not valid json")
        
        self.assertEqual(status, 400)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["error"]["type"], "BadRequest")
        self.assertIn("Invalid JSON", data["error"]["message"])
    
    def test_400_missing_text_field(self):
        """POST /classify sin campo text debe retornar 400."""
        status, data = self._post_classify({"mode": "auto"})
        
        self.assertEqual(status, 400)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["error"]["type"], "BadRequest")
        self.assertIn("text", data["error"]["message"])
    
    def test_400_text_not_string(self):
        """POST /classify con text no string debe retornar 400."""
        status, data = self._post_classify({"text": 123})
        
        self.assertEqual(status, 400)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["error"]["type"], "BadRequest")
        self.assertIn("string", data["error"]["message"])
    
    def test_400_body_not_object(self):
        """POST /classify con body que no es objeto debe retornar 400."""
        status, data = self._post_classify(b'"just a string"')
        
        self.assertEqual(status, 400)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["error"]["type"], "BadRequest")
    
    def test_400_wrong_content_type(self):
        """POST /classify con Content-Type incorrecto debe retornar 400."""
        headers = {
            "Content-Type": "text/plain",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"text": "test"}).encode("utf-8")
        status, data = self._request("POST", "/classify", body, headers)
        
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["type"], "BadRequest")
    
    # -------------------------------------------------------------------------
    # Success Tests
    # -------------------------------------------------------------------------
    
    def test_200_valid_request_minimal(self):
        """POST /classify con request válido mínimo debe retornar 200."""
        status, data = self._post_classify({"text": "Gasté $25 en comida"})
        
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("intent", data)
    
    def test_200_valid_request_full(self):
        """POST /classify con request completo debe retornar 200."""
        status, data = self._post_classify({
            "text": "Gasté $25 en comida",
            "mode": "auto",
            "conversation_id": "test-123",
            "context": {"source": "test"},
        })
        
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
    
    def test_response_structure(self):
        """Response debe tener estructura correcta."""
        status, data = self._post_classify({"text": "Test message"})
        
        self.assertEqual(status, 200)
        
        # Top level
        self.assertIn("ok", data)
        self.assertIn("intent", data)
        
        # Intent structure
        intent = data["intent"]
        self.assertIn("domain", intent)
        self.assertIn("type", intent)
        self.assertIn("cognitive_load", intent)
        self.assertIn("impact", intent)
        self.assertIn("next_action", intent)
        self.assertIn("confidence", intent)
        self.assertIn("alternatives", intent)
        self.assertIn("needs_confirmation", intent)
        self.assertIn("reason", intent)
    
    def test_domain_values_valid(self):
        """domain debe ser uno de los valores válidos."""
        valid_domains = {"WORK", "PRO_DIAG", "FIN", "REL", "HEALTH", "EIPROTA", "ENERGY"}
        
        status, data = self._post_classify({"text": "Test"})
        
        self.assertEqual(status, 200)
        self.assertIn(data["intent"]["domain"], valid_domains)
    
    def test_type_values_valid(self):
        """type debe ser uno de los valores válidos."""
        valid_types = {"Idea", "Tarea", "Reflexión", "Proyecto", "Ajuste"}
        
        status, data = self._post_classify({"text": "Test"})
        
        self.assertEqual(status, 200)
        self.assertIn(data["intent"]["type"], valid_types)
    
    def test_cognitive_load_values_valid(self):
        """cognitive_load debe ser uno de los valores válidos."""
        valid_loads = {"Alta", "Media", "Baja"}
        
        status, data = self._post_classify({"text": "Test"})
        
        self.assertEqual(status, 200)
        self.assertIn(data["intent"]["cognitive_load"], valid_loads)
    
    def test_impact_values_valid(self):
        """impact debe ser uno de los valores válidos."""
        valid_impacts = {"Estructural", "Económico", "Emocional", "Intelectual", "Operativo"}
        
        status, data = self._post_classify({"text": "Test"})
        
        self.assertEqual(status, 200)
        self.assertIn(data["intent"]["impact"], valid_impacts)
    
    def test_confidence_range(self):
        """confidence debe estar entre 0 y 1."""
        status, data = self._post_classify({"text": "Test"})
        
        self.assertEqual(status, 200)
        confidence = data["intent"]["confidence"]
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)
    
    def test_alternatives_structure(self):
        """alternatives debe ser una lista con estructura correcta."""
        status, data = self._post_classify({"text": "Test"})
        
        self.assertEqual(status, 200)
        alternatives = data["intent"]["alternatives"]
        self.assertIsInstance(alternatives, list)
        
        for alt in alternatives:
            self.assertIn("domain", alt)
            self.assertIn("confidence", alt)
    
    def test_needs_confirmation_boolean(self):
        """needs_confirmation debe ser boolean."""
        status, data = self._post_classify({"text": "Test"})
        
        self.assertEqual(status, 200)
        self.assertIsInstance(data["intent"]["needs_confirmation"], bool)
    
    # -------------------------------------------------------------------------
    # Classification Accuracy Tests
    # -------------------------------------------------------------------------
    
    def test_classify_fin(self):
        """Texto financiero debe clasificar como FIN."""
        status, data = self._post_classify({"text": "Gasté $25 en comida"})
        
        self.assertEqual(status, 200)
        self.assertEqual(data["intent"]["domain"], "FIN")
    
    def test_classify_energy(self):
        """Texto sobre saturación debe clasificar como ENERGY."""
        status, data = self._post_classify({"text": "Estoy saturado, demasiados frentes abiertos"})
        
        self.assertEqual(status, 200)
        self.assertEqual(data["intent"]["domain"], "ENERGY")
    
    def test_classify_eiprota(self):
        """Texto sobre TTI debe clasificar como EIPROTA."""
        status, data = self._post_classify({"text": "Necesito avanzar módulo de tensores TTI"})
        
        self.assertEqual(status, 200)
        self.assertEqual(data["intent"]["domain"], "EIPROTA")
    
    def test_classify_work(self):
        """Texto sobre POE debe clasificar como WORK."""
        status, data = self._post_classify({"text": "Actualizar POE incubadoras"})
        
        self.assertEqual(status, 200)
        self.assertEqual(data["intent"]["domain"], "WORK")
    
    def test_classify_prodiag(self):
        """Texto sobre SaaS/diagnóstico debe clasificar como PRO_DIAG."""
        status, data = self._post_classify({"text": "Propuesta SaaS diagnóstico empresarial pricing"})
        
        self.assertEqual(status, 200)
        self.assertEqual(data["intent"]["domain"], "PRO_DIAG")
    
    def test_classify_rel(self):
        """Texto sobre relaciones debe clasificar como REL."""
        status, data = self._post_classify({"text": "Hablar con Ana sobre la cena"})
        
        self.assertEqual(status, 200)
        self.assertEqual(data["intent"]["domain"], "REL")
    
    def test_classify_health(self):
        """Texto sobre salud debe clasificar como HEALTH."""
        status, data = self._post_classify({"text": "Dormí mal, ansiedad"})
        
        self.assertEqual(status, 200)
        self.assertEqual(data["intent"]["domain"], "HEALTH")


if __name__ == "__main__":
    unittest.main()
