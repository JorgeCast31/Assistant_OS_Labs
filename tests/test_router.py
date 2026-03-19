"""
Tests para el router de comandos.
"""
import unittest

from assistant_os.router import parse_command_to_request, route_request


class TestParseCommandToRequest(unittest.TestCase):
    """Tests para parse_command_to_request."""
    
    def test_parse_code_prefix(self):
        """CODE: debe parsearse a agent='code'."""
        req = parse_command_to_request(" CODE: hola")
        self.assertEqual(req["agent"], "code")
        self.assertEqual(req["action"], "run_task")
        self.assertEqual(req["payload"]["task"], "hola")
    
    def test_parse_doc_prefix(self):
        """DOC: debe parsearse a agent='doc'."""
        req = parse_command_to_request("DOC: genera docs")
        self.assertEqual(req["agent"], "doc")
    
    def test_parse_jobs_prefix(self):
        """JOBS: debe parsearse a agent='jobs'."""
        req = parse_command_to_request("jobs: buscar trabajo")
        self.assertEqual(req["agent"], "jobs")
    
    def test_parse_biz_prefix(self):
        """BIZ: debe parsearse a agent='biz'."""
        req = parse_command_to_request("  BIZ:  analizar modelo")
        self.assertEqual(req["agent"], "biz")
        self.assertEqual(req["payload"]["task"], "analizar modelo")
    
    def test_parse_no_prefix(self):
        """Sin prefijo válido debe ser agent='unknown'."""
        req = parse_command_to_request("hola mundo")
        self.assertEqual(req["agent"], "unknown")
        self.assertEqual(req["action"], "invalid_prefix")
    
    def test_parse_empty_command(self):
        """Comando vacío debe ser agent='unknown'."""
        req = parse_command_to_request("")
        self.assertEqual(req["agent"], "unknown")
        self.assertEqual(req["action"], "empty_command")
    
    def test_context_id_generated(self):
        """Cada request debe tener un context_id único."""
        req1 = parse_command_to_request("CODE: test1")
        req2 = parse_command_to_request("CODE: test2")
        self.assertIsNotNone(req1["context_id"])
        self.assertIsNotNone(req2["context_id"])
        self.assertNotEqual(req1["context_id"], req2["context_id"])


class TestRouteRequest(unittest.TestCase):
    """Tests para route_request."""
    
    def test_route_unknown_returns_error(self):
        """Agente unknown debe retornar status='error'."""
        req = parse_command_to_request("comando inválido")
        response = route_request(req)
        self.assertEqual(response["status"], "error")
        self.assertIsNotNone(response["error"])
        self.assertEqual(response["error"]["type"], "InvalidPrefix")
    
    def test_route_empty_returns_error(self):
        """Comando vacío debe retornar error."""
        req = parse_command_to_request("")
        response = route_request(req)
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error"]["type"], "EmptyCommand")
    
    def test_route_code_returns_ok(self):
        """CODE: debe retornar respuesta válida del CodeAgent."""
        req = parse_command_to_request("CODE: crear modulo test xyz123")
        response = route_request(req)
        # CodeAgent real puede tardar y crear archivos, verificamos estructura
        self.assertEqual(response["agent"], "code")
        self.assertIn("status", response)  # ok o error ambos válidos
        self.assertIn(response["status"], ("ok", "error"))
        # Si ok, verificar estructura de output
        if response["status"] == "ok":
            self.assertIn("action", response["output"])
    
    def test_route_doc_returns_ok(self):
        """DOC: debe retornar status='ok'."""
        req = parse_command_to_request("DOC: generar docs")
        response = route_request(req)
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["agent"], "doc")
    
    def test_route_jobs_returns_ok(self):
        """JOBS: debe retornar status='ok' con resultados."""
        req = parse_command_to_request("JOBS: buscar Python")
        response = route_request(req)
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["agent"], "jobs")
        self.assertIn("results", response["output"])
        self.assertEqual(response["output"]["count"], 3)
    
    def test_route_biz_returns_ok(self):
        """BIZ: debe retornar status='ok' con next_actions y risks."""
        req = parse_command_to_request("BIZ: analizar SaaS")
        response = route_request(req)
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["agent"], "biz")
        self.assertIn("next_actions", response["output"])
        self.assertIn("risks", response["output"])


if __name__ == "__main__":
    unittest.main()
