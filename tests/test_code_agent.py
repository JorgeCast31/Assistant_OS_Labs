"""
Tests para CodeAgent real.
Verifica creación de módulos y ejecución de tests.
"""
import sys
import shutil
import unittest
from pathlib import Path

# Path setup
sys.path.insert(0, str(Path(__file__).parent.parent))

from assistant_os.agents.code_agent import (
    CodeAgent,
    slugify_module_name,
    ensure_unique_path,
    tail,
    extract_keywords,
    generate_module_code,
    generate_test_code,
)
from assistant_os.contracts import Request
from assistant_os.config import WORKSPACE_ROOT


class TestSlugifyModuleName(unittest.TestCase):
    """Tests para slugify_module_name."""
    
    def test_basic_text(self):
        """Texto simple se convierte a snake_case."""
        result = slugify_module_name("hello world")
        self.assertEqual(result, "hello_world")
    
    def test_accents_removed(self):
        """Acentos son removidos."""
        result = slugify_module_name("módulo básico")
        self.assertEqual(result, "modulo_basico")
    
    def test_special_chars_removed(self):
        """Caracteres especiales son removidos."""
        result = slugify_module_name("foo!@#$%bar")
        self.assertEqual(result, "foobar")
    
    def test_multiple_spaces(self):
        """Múltiples espacios se colapsan."""
        result = slugify_module_name("foo   bar   baz")
        self.assertEqual(result, "foo_bar_baz")
    
    def test_starts_with_number(self):
        """Si empieza con número, agrega prefijo."""
        result = slugify_module_name("123test")
        self.assertEqual(result, "module_123test")
    
    def test_empty_after_clean(self):
        """Si queda vacío, retorna module_."""
        result = slugify_module_name("!!!###")
        self.assertEqual(result, "module_")
    
    def test_max_length(self):
        """Limita a 40 caracteres."""
        long_text = "a" * 100
        result = slugify_module_name(long_text)
        self.assertEqual(len(result), 40)


class TestEnsureUniquePath(unittest.TestCase):
    """Tests para ensure_unique_path."""
    
    def setUp(self):
        """Crear directorio temporal para tests."""
        self.test_dir = WORKSPACE_ROOT / "test_temp_unique"
        self.test_dir.mkdir(parents=True, exist_ok=True)
    
    def tearDown(self):
        """Limpiar directorio temporal."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def test_path_not_exists_unchanged(self):
        """Si no existe, retorna el mismo path."""
        path = self.test_dir / "new_file.py"
        result = ensure_unique_path(path)
        self.assertEqual(result, path)
    
    def test_path_exists_gets_v2(self):
        """Si existe, retorna con _v2."""
        path = self.test_dir / "existing.py"
        path.write_text("# existing", encoding="utf-8")
        
        result = ensure_unique_path(path)
        self.assertEqual(result.name, "existing_v2.py")
    
    def test_v2_exists_gets_v3(self):
        """Si _v2 existe, retorna _v3."""
        path = self.test_dir / "multi.py"
        path.write_text("# v1", encoding="utf-8")
        (self.test_dir / "multi_v2.py").write_text("# v2", encoding="utf-8")
        
        result = ensure_unique_path(path)
        self.assertEqual(result.name, "multi_v3.py")


class TestTail(unittest.TestCase):
    """Tests para tail."""
    
    def test_short_text_unchanged(self):
        """Texto corto no se modifica."""
        result = tail("hello", 100)
        self.assertEqual(result, "hello")
    
    def test_long_text_truncated(self):
        """Texto largo se trunca con ..."""
        text = "x" * 100
        result = tail(text, 50)
        self.assertTrue(result.startswith("..."))
        self.assertEqual(len(result), 53)  # ... + 50 chars


class TestExtractKeywords(unittest.TestCase):
    """Tests para extract_keywords."""
    
    def test_basic_extraction(self):
        """Extrae palabras clave relevantes."""
        result = extract_keywords("crear módulo tensor básico")
        self.assertIn("tensor", result)
    
    def test_stopwords_removed(self):
        """Palabras comunes son removidas."""
        result = extract_keywords("crea módulo para una cosa")
        self.assertNotIn("crea", result)
        self.assertNotIn("para", result)
    
    def test_max_five_keywords(self):
        """Máximo 5 keywords."""
        long_text = "word1 word2 word3 word4 word5 word6 word7"
        result = extract_keywords(long_text)
        self.assertLessEqual(len(result), 5)


class TestGenerateModuleCode(unittest.TestCase):
    """Tests para generate_module_code."""
    
    def test_generates_valid_python(self):
        """Genera código Python válido."""
        code = generate_module_code("test_module", ["data"])
        # Verificar que compila
        compile(code, "<test>", "exec")
    
    def test_contains_functions(self):
        """Contiene las funciones esperadas."""
        code = generate_module_code("test_module", ["data"])
        self.assertIn("def init_data", code)
        self.assertIn("def process_data", code)
        self.assertIn("def validate_data", code)
        self.assertIn("def export_data", code)
    
    def test_uses_topic(self):
        """Usa la keyword como topic."""
        code = generate_module_code("tensor_module", ["tensor"])
        self.assertIn("init_tensor", code)


class TestGenerateTestCode(unittest.TestCase):
    """Tests para generate_test_code."""
    
    def test_generates_valid_python(self):
        """Genera código Python válido."""
        code = generate_test_code("test_module", ["data"])
        compile(code, "<test>", "exec")
    
    def test_contains_unittest(self):
        """Contiene imports de unittest."""
        code = generate_test_code("test_module", ["data"])
        self.assertIn("import unittest", code)
        self.assertIn("class Test", code)


class TestCodeAgent(unittest.TestCase):
    """Tests para CodeAgent."""
    
    def setUp(self):
        """Configurar agente y limpiar directorios."""
        self.agent = CodeAgent()
        self.src_dir = WORKSPACE_ROOT / "src"
        self.tests_dir = WORKSPACE_ROOT / "tests_generated"
        self._created_files: list[Path] = []
    
    def tearDown(self):
        """Limpiar archivos generados por este test."""
        for f in self._created_files:
            if f.exists():
                f.unlink(missing_ok=True)
    
    def _unique_task(self, base: str) -> str:
        """Genera un task name único para evitar colisiones."""
        import uuid
        return f"{base} {uuid.uuid4().hex[:8]}"
    
    def _track_files(self, result: dict) -> None:
        """Trackea archivos creados para cleanup."""
        if "output" in result and "paths" in result["output"]:
            paths = result["output"]["paths"]
            if "module" in paths:
                self._created_files.append(WORKSPACE_ROOT / paths["module"])
            if "tests" in paths:
                self._created_files.append(WORKSPACE_ROOT / paths["tests"])
    
    def test_agent_creates_module_and_tests(self):
        """Agent crea archivos de módulo y tests."""
        req: Request = {
            "context_id": "test_ctx_001",
            "agent": "code",
            "payload": {"task": self._unique_task("crear modulo agentcreate")},
            "ts": "2025-01-01T00:00:00Z",
        }
        
        result = self.agent.run(req)
        self._track_files(result)
        
        # Si hubo error, mostrar mensaje
        if result["status"] != "ok":
            self.fail(f"Agent returned error: {result.get('error')}")
        
        # Verificar estructura de Response
        self.assertEqual(result["agent"], "code")
        self.assertIn("output", result)
        self.assertIn("files_created", result["output"])
        self.assertIn("module_name", result["output"])
        
        # Verificar que los archivos existen
        module_path = WORKSPACE_ROOT / result["output"]["paths"]["module"]
        test_path = WORKSPACE_ROOT / result["output"]["paths"]["tests"]
        
        self.assertTrue(module_path.exists(), f"Module not found: {module_path}")
        self.assertTrue(test_path.exists(), f"Tests not found: {test_path}")
    
    def test_agent_runs_tests(self):
        """Agent ejecuta tests y reporta resultado."""
        req: Request = {
            "context_id": "test_ctx_002",
            "agent": "code",
            "payload": {"task": self._unique_task("crear modulo validrun")},
            "ts": "2025-01-01T00:00:00Z",
        }
        
        result = self.agent.run(req)
        self._track_files(result)
        
        # Si hubo error, mostrar mensaje detallado
        if result["status"] != "ok":
            self.fail(f"Agent returned error: {result.get('error')}")
        
        # Verificar que se ejecutaron tests
        self.assertIn("tests", result["output"])
        self.assertIn("status", result["output"]["tests"])
        self.assertIn("iterations_used", result["output"])


if __name__ == "__main__":
    unittest.main()
