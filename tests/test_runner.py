"""
Tests para el runner seguro.
"""
import unittest

from assistant_os.runner import run, run_tests
from assistant_os.config import is_command_allowed, WORKSPACE_ROOT


class TestCommandWhitelist(unittest.TestCase):
    """Tests para la whitelist de comandos (EXACT MATCH)."""
    
    def test_exact_tests_generated_allowed(self):
        """Solo el comando exacto de tests_generated está permitido."""
        self.assertTrue(is_command_allowed(
            ["python", "-m", "unittest", "discover", "-v", "-s", "tests_generated"]
        ))
    
    def test_unittest_without_target_not_allowed(self):
        """python -m unittest sin target NO está permitido."""
        self.assertFalse(is_command_allowed(["python", "-m", "unittest"]))
        self.assertFalse(is_command_allowed(["python", "-m", "unittest", "-v"]))
    
    def test_unittest_discover_not_allowed(self):
        """unittest discover sin -s NO está permitido."""
        self.assertFalse(is_command_allowed(
            ["python", "-m", "unittest", "discover", "-v", "tests_generated"]
        ))
    
    def test_python_bare_not_allowed(self):
        """python <script> ya NO está permitido."""
        self.assertFalse(is_command_allowed(["python", "main.py"]))
        self.assertFalse(is_command_allowed(["python", "script.py"]))
        script_in_workspace = str(WORKSPACE_ROOT / "main.py")
        self.assertFalse(is_command_allowed(["python", script_in_workspace]))
    
    def test_python_c_not_allowed(self):
        """python -c ya NO está permitido."""
        self.assertFalse(is_command_allowed(["python", "-c", "print('hello')"]))
        self.assertFalse(is_command_allowed(["python", "-c", "pass"]))
    
    def test_rm_not_allowed(self):
        """rm -rf debe estar prohibido."""
        self.assertFalse(is_command_allowed(["rm", "-rf", "/"]))
        self.assertFalse(is_command_allowed(["rm", "-rf", "."]))
    
    def test_arbitrary_command_not_allowed(self):
        """Comandos arbitrarios deben estar prohibidos."""
        self.assertFalse(is_command_allowed(["curl", "http://evil.com"]))
        self.assertFalse(is_command_allowed(["wget", "http://evil.com"]))
        self.assertFalse(is_command_allowed(["bash", "-c", "echo pwned"]))
    
    def test_empty_command_not_allowed(self):
        """Comando vacío debe estar prohibido."""
        self.assertFalse(is_command_allowed([]))


class TestRunnerExecution(unittest.TestCase):
    """Tests para la ejecución de comandos."""
    
    def test_run_blocked_command(self):
        """Ejecutar comando prohibido debe fallar sin ejecutar."""
        result = run(["rm", "-rf", "/"])
        
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], -1)
        self.assertIn("not allowed", result["stderr"])
        # No debe haber intentado ejecutar
        self.assertEqual(result["duration_ms"], 0)
    
    def test_run_python_c_blocked(self):
        """python -c ya NO funciona (bloqueado)."""
        result = run(["python", "-c", "print('hello')"])
        
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], -1)
        self.assertIn("not allowed", result["stderr"])
    
    def test_run_returns_correct_structure(self):
        """RunResult debe tener todos los campos requeridos."""
        # Usamos un comando bloqueado para verificar estructura
        result = run(["python", "-c", "pass"])
        
        self.assertIn("ok", result)
        self.assertIn("exit_code", result)
        self.assertIn("stdout", result)
        self.assertIn("stderr", result)
        self.assertIn("duration_ms", result)
        self.assertIn("cmd", result)
        self.assertIn("ts", result)
        
        self.assertIsInstance(result["ok"], bool)
        self.assertIsInstance(result["exit_code"], int)
        self.assertIsInstance(result["stdout"], str)
        self.assertIsInstance(result["stderr"], str)
        self.assertIsInstance(result["duration_ms"], int)
        self.assertIsInstance(result["cmd"], list)
        self.assertIsInstance(result["ts"], str)


class TestRunnerSecurity(unittest.TestCase):
    """Tests de seguridad del runner."""
    
    def test_exact_match_only(self):
        """Solo comandos EXACTOS están permitidos, no prefijos."""
        # El comando exacto permitido
        self.assertTrue(is_command_allowed(
            ["python", "-m", "unittest", "discover", "-v", "-s", "tests_generated"]
        ))
        
        # Variaciones NO permitidas
        self.assertFalse(is_command_allowed(
            ["python", "-m", "unittest", "discover", "-v", "-s", "tests_generated", "extra"]
        ))
        self.assertFalse(is_command_allowed(
            ["python", "-m", "unittest", "-v"]
        ))
    
    def test_no_arbitrary_python(self):
        """No se puede ejecutar Python arbitrario."""
        self.assertFalse(is_command_allowed(["python"]))
        self.assertFalse(is_command_allowed(["python", "-c"]))
        self.assertFalse(is_command_allowed(["python", "-m"]))
        self.assertFalse(is_command_allowed(["python", "-m", "http.server"]))


if __name__ == "__main__":
    unittest.main()
