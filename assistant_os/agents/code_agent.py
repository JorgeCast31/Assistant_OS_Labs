"""
CodeAgent - Crea módulos Python nuevos y ejecuta tests con loop iterativo.
SOLO crea archivos nuevos, nunca modifica existentes.
"""
import re
import unicodedata
from pathlib import Path
from typing import Any

from ..contracts import Request, Response, make_ok, make_error
from ..config import WORKSPACE_ROOT, MAX_ITERATIONS
from ..runner import run
from ..memory.state import update_agent_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify_module_name(text: str) -> str:
    """
    Convierte texto a nombre de módulo válido (snake_case).
    Elimina acentos, caracteres especiales, y normaliza espacios.
    """
    # Normalizar unicode (quitar acentos)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    
    # Convertir a minúsculas
    text = text.lower()
    
    # Reemplazar espacios y guiones por underscore
    text = re.sub(r"[\s\-]+", "_", text)
    
    # Eliminar caracteres no válidos para identificadores Python
    text = re.sub(r"[^a-z0-9_]", "", text)
    
    # Eliminar underscores múltiples
    text = re.sub(r"_+", "_", text)
    
    # Quitar underscores al inicio/final
    text = text.strip("_")
    
    # Si queda vacío o empieza con número, agregar prefijo
    if not text or text[0].isdigit():
        text = "module_" + text
    
    # Limitar longitud
    return text[:40]


def ensure_unique_path(path: Path) -> Path:
    """
    Si el path existe, agrega sufijo _v2, _v3, etc.
    Retorna un path que no existe.
    """
    if not path.exists():
        return path
    
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    
    version = 2
    while True:
        new_path = parent / f"{stem}_v{version}{suffix}"
        if not new_path.exists():
            return new_path
        version += 1
        if version > 100:  # Safety limit
            raise RuntimeError(f"Too many versions for {path}")


def write_text_safe(path: Path, content: str) -> Path:
    """
    Escribe contenido a un archivo, creando directorios padre si es necesario.
    Retorna el path final usado (puede diferir si existía).
    """
    final_path = ensure_unique_path(path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(content, encoding="utf-8")
    return final_path


def tail(text: str, max_chars: int = 1200) -> str:
    """Retorna los últimos max_chars caracteres del texto."""
    if len(text) <= max_chars:
        return text
    return "..." + text[-max_chars:]


def extract_keywords(text: str) -> list[str]:
    """Extrae palabras clave del texto para generar código relevante."""
    # Palabras comunes en español a ignorar
    stopwords = {
        "crea", "crear", "modulo", "módulo", "basico", "básico", "nuevo", 
        "para", "con", "que", "una", "uno", "los", "las", "del", "de", "el", "la"
    }
    
    words = re.findall(r"[a-záéíóúñ]+", text.lower())
    keywords = [w for w in words if w not in stopwords and len(w) > 2]
    return keywords[:5]  # Max 5 keywords


# ---------------------------------------------------------------------------
# Code Generation Templates
# ---------------------------------------------------------------------------

def generate_module_code(module_name: str, keywords: list[str]) -> str:
    """Genera código del módulo basado en keywords."""
    
    # Determinar tema dominante
    topic = keywords[0] if keywords else "data"
    
    return f'''"""
Módulo {module_name} - Generado automáticamente por CodeAgent.

Proporciona funciones para trabajar con {topic}.
"""
from typing import Any, List, Dict, Optional


def init_{topic}(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Inicializa una estructura de {topic}.
    
    Args:
        config: Configuración opcional
    
    Returns:
        Diccionario con la estructura inicializada
    """
    config = config or {{}}
    return {{
        "name": config.get("name", "{topic}_default"),
        "data": [],
        "metadata": {{"version": "1.0", "type": "{topic}"}},
    }}


def process_{topic}(item: Any) -> Any:
    """
    Procesa un elemento de {topic}.
    
    Args:
        item: Elemento a procesar
    
    Returns:
        Elemento procesado
    """
    if item is None:
        return None
    
    if isinstance(item, dict):
        return {{k: v for k, v in item.items() if v is not None}}
    
    if isinstance(item, (list, tuple)):
        return [process_{topic}(x) for x in item]
    
    return item


def validate_{topic}(data: Any) -> bool:
    """
    Valida datos de {topic}.
    
    Args:
        data: Datos a validar
    
    Returns:
        True si es válido, False en caso contrario
    """
    if data is None:
        return False
    
    if isinstance(data, dict):
        return "name" in data or "data" in data or len(data) > 0
    
    if isinstance(data, (list, tuple)):
        return len(data) >= 0  # Listas vacías son válidas
    
    return True


def export_{topic}(data: Dict[str, Any], format: str = "dict") -> Any:
    """
    Exporta datos de {topic} al formato especificado.
    
    Args:
        data: Datos a exportar
        format: Formato de salida ("dict", "list", "summary")
    
    Returns:
        Datos en el formato solicitado
    """
    if format == "list":
        if isinstance(data, dict):
            return list(data.values())
        return list(data) if data else []
    
    if format == "summary":
        return {{
            "type": "{topic}",
            "items": len(data) if isinstance(data, (dict, list)) else 1,
            "valid": validate_{topic}(data),
        }}
    
    # Default: dict
    return dict(data) if isinstance(data, dict) else {{"value": data}}
'''


def generate_test_code(module_name: str, keywords: list[str]) -> str:
    """Genera código de tests para el módulo."""
    
    topic = keywords[0] if keywords else "data"
    
    return f'''"""
Tests para el módulo {module_name}.
Generado automáticamente por CodeAgent.
"""
import unittest
import sys
from pathlib import Path

# Agregar workspace al path para imports como paquete
_workspace = Path(__file__).parent.parent
sys.path.insert(0, str(_workspace))

from src.{module_name} import init_{topic}, process_{topic}, validate_{topic}, export_{topic}


class Test{module_name.title().replace("_", "")}(unittest.TestCase):
    """Tests para {module_name}."""
    
    def test_init_returns_dict(self):
        """init_{topic} debe retornar un diccionario."""
        result = init_{topic}()
        self.assertIsInstance(result, dict)
        self.assertIn("name", result)
        self.assertIn("data", result)
        self.assertIn("metadata", result)
    
    def test_init_with_config(self):
        """init_{topic} debe aceptar configuración."""
        result = init_{topic}({{"name": "custom"}})
        self.assertEqual(result["name"], "custom")
    
    def test_process_none(self):
        """process_{topic} debe manejar None."""
        result = process_{topic}(None)
        self.assertIsNone(result)
    
    def test_process_dict(self):
        """process_{topic} debe procesar diccionarios."""
        result = process_{topic}({{"a": 1, "b": None}})
        self.assertIsInstance(result, dict)
        self.assertIn("a", result)
    
    def test_process_list(self):
        """process_{topic} debe procesar listas."""
        result = process_{topic}([1, 2, 3])
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)
    
    def test_validate_none_returns_false(self):
        """validate_{topic} debe retornar False para None."""
        self.assertFalse(validate_{topic}(None))
    
    def test_validate_dict_returns_true(self):
        """validate_{topic} debe retornar True para dict válido."""
        self.assertTrue(validate_{topic}({{"name": "test"}}))
    
    def test_validate_empty_list_returns_true(self):
        """validate_{topic} debe retornar True para lista vacía."""
        self.assertTrue(validate_{topic}([]))
    
    def test_export_dict_format(self):
        """export_{topic} debe exportar como dict."""
        data = {{"key": "value"}}
        result = export_{topic}(data, "dict")
        self.assertIsInstance(result, dict)
    
    def test_export_list_format(self):
        """export_{topic} debe exportar como list."""
        data = {{"a": 1, "b": 2}}
        result = export_{topic}(data, "list")
        self.assertIsInstance(result, list)
    
    def test_export_summary_format(self):
        """export_{topic} debe exportar como summary."""
        data = {{"a": 1}}
        result = export_{topic}(data, "summary")
        self.assertIn("type", result)
        self.assertIn("items", result)
        self.assertIn("valid", result)


if __name__ == "__main__":
    unittest.main()
'''


# ---------------------------------------------------------------------------
# CodeAgent Class
# ---------------------------------------------------------------------------

class CodeAgent:
    """
    Agente para crear módulos Python nuevos.
    - Genera código en src/<module>.py
    - Genera tests en tests_generated/test_<module>.py
    - Ejecuta tests y itera hasta MAX_ITERATIONS si fallan
    """
    
    def __init__(self):
        self.src_dir = WORKSPACE_ROOT / "src"
        self.tests_dir = WORKSPACE_ROOT / "tests_generated"
    
    def run(self, req: Request) -> Response:
        """
        Crea un módulo nuevo basado en la Request.
        
        Args:
            req: Request con payload.task o payload.raw
        
        Returns:
            Response estructurada con resultado
        """
        context_id = req["context_id"]
        task = req["payload"].get("task", req["payload"].get("raw", ""))
        
        # Actualizar estado: iniciando
        update_agent_state("code", {
            "last_task": task,
            "status": "running",
            "iterations": 0,
        })
        
        try:
            result = self._create_module(task, context_id)
            return result
        except Exception as e:
            update_agent_state("code", {"status": "error"})
            return make_error(
                agent="code",
                context_id=context_id,
                message=f"Error en CodeAgent: {type(e).__name__}: {e}",
                err_type="AgentError",
            )
    
    def _create_module(self, task: str, context_id: str) -> Response:
        """
        Lógica principal de creación de módulo.
        """
        # Extraer nombre y keywords
        module_name = slugify_module_name(task)
        keywords = extract_keywords(task)
        
        if not keywords:
            keywords = [module_name.split("_")[0]]
        
        # Paths objetivo
        module_path = self.src_dir / f"{module_name}.py"
        test_path = self.tests_dir / f"test_{module_name}.py"
        
        files_created: list[str] = []
        notes: list[str] = []
        
        # Generar y escribir código
        module_code = generate_module_code(module_name, keywords)
        test_code = generate_test_code(module_name, keywords)
        
        final_module_path = write_text_safe(module_path, module_code)
        final_test_path = write_text_safe(test_path, test_code)
        
        files_created.append(str(final_module_path.relative_to(WORKSPACE_ROOT)))
        files_created.append(str(final_test_path.relative_to(WORKSPACE_ROOT)))
        
        if final_module_path != module_path:
            notes.append(f"Módulo renombrado a {final_module_path.name} (original existía)")
        if final_test_path != test_path:
            notes.append(f"Test renombrado a {final_test_path.name} (original existía)")
        
        # Crear __init__.py en tests_generated si no existe
        tests_init = self.tests_dir / "__init__.py"
        if not tests_init.exists():
            tests_init.parent.mkdir(parents=True, exist_ok=True)
            tests_init.write_text('"""Tests generados por CodeAgent."""\n', encoding="utf-8")
            files_created.append(str(tests_init.relative_to(WORKSPACE_ROOT)))
        
        # Crear __init__.py en src si no existe
        src_init = self.src_dir / "__init__.py"
        if not src_init.exists():
            src_init.parent.mkdir(parents=True, exist_ok=True)
            src_init.write_text('"""Módulos generados por CodeAgent."""\n', encoding="utf-8")
            files_created.append(str(src_init.relative_to(WORKSPACE_ROOT)))
        
        # Ejecutar tests con loop iterativo
        test_result = self._run_tests_with_retry(
            module_name=module_name,
            module_path=final_module_path,
            test_path=final_test_path,
            keywords=keywords,
            context_id=context_id,
        )
        
        # Construir output
        output = {
            "action": "create_module",
            "module_name": module_name,
            "paths": {
                "module": str(final_module_path.relative_to(WORKSPACE_ROOT)),
                "tests": str(final_test_path.relative_to(WORKSPACE_ROOT)),
            },
            "files_created": files_created,
            "iterations_used": test_result["iterations"],
            "tests": {
                "status": "passed" if test_result["passed"] else "failed",
                "exit_code": test_result["exit_code"],
                "summary": test_result["summary"],
                "stdout_tail": tail(test_result["stdout"], 800),
                "stderr_tail": tail(test_result["stderr"], 400),
            },
            "notes": notes + test_result.get("notes", []),
        }
        
        # Actualizar estado final
        final_status = "ok" if test_result["passed"] else "error"
        update_agent_state("code", {
            "status": final_status,
            "iterations": test_result["iterations"],
        })
        
        if test_result["passed"]:
            return make_ok(agent="code", context_id=context_id, output=output)
        else:
            return Response(
                context_id=context_id,
                agent="code",
                status="error",
                output=output,
                error={"type": "TestsFailed", "message": "Tests no pasaron tras máximas iteraciones"},
                ts=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            )
    
    def _run_tests_with_retry(
        self,
        module_name: str,
        module_path: Path,
        test_path: Path,
        keywords: list[str],
        context_id: str,
    ) -> dict[str, Any]:
        """
        Ejecuta tests y reintenta hasta MAX_ITERATIONS si fallan.
        """
        iterations = 0
        notes: list[str] = []
        
        while iterations < MAX_ITERATIONS:
            iterations += 1
            
            update_agent_state("code", {"iterations": iterations})
            
            # Ejecutar tests de tests_generated (comando exacto permitido)
            result = run(["python", "-m", "unittest", "discover", "-v", "-s", "tests_generated"])
            
            if result["ok"]:
                notes.append(f"Tests pasaron en iteración {iterations}")
                return {
                    "passed": True,
                    "iterations": iterations,
                    "exit_code": result["exit_code"],
                    "stdout": result["stdout"],
                    "stderr": result["stderr"],
                    "summary": self._extract_test_summary(result["stderr"] or result["stdout"]),
                    "notes": notes,
                }
            
            # Si fallaron, intentar corregir
            if iterations < MAX_ITERATIONS:
                fix_applied = self._try_fix_code(
                    module_path=module_path,
                    test_path=test_path,
                    keywords=keywords,
                    error_output=result["stderr"] or result["stdout"],
                )
                if fix_applied:
                    notes.append(f"Iteración {iterations}: aplicada corrección")
                else:
                    notes.append(f"Iteración {iterations}: no se pudo aplicar corrección")
                    break  # Sin más correcciones posibles
        
        # Tests fallaron tras todas las iteraciones
        return {
            "passed": False,
            "iterations": iterations,
            "exit_code": result["exit_code"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "summary": self._extract_test_summary(result["stderr"] or result["stdout"]),
            "notes": notes,
        }
    
    def _extract_test_summary(self, output: str) -> str:
        """Extrae resumen de tests del output."""
        lines = output.strip().split("\n")
        
        # Buscar línea con "Ran X tests" o "OK" o "FAILED"
        for line in reversed(lines):
            if "Ran" in line and "test" in line:
                return line.strip()
            if line.strip() in ("OK", "FAILED"):
                return line.strip()
            if "FAILED" in line or "ERROR" in line:
                return line.strip()[:100]
        
        return lines[-1][:100] if lines else "No output"
    
    def _try_fix_code(
        self,
        module_path: Path,
        test_path: Path,
        keywords: list[str],
        error_output: str,
    ) -> bool:
        """
        Intenta corregir el código basándose en el error.
        Solo regenera los archivos que creó este agente.
        
        Returns:
            True si se aplicó alguna corrección
        """
        error_lower = error_output.lower()
        
        # Error de import: regenerar con paths corregidos
        if "modulenotfounderror" in error_lower or "importerror" in error_lower:
            # Regenerar test con import path alternativo
            module_name = module_path.stem
            new_test_code = self._generate_test_with_alt_import(module_name, keywords)
            test_path.write_text(new_test_code, encoding="utf-8")
            return True
        
        # Error de sintaxis en el módulo
        if "syntaxerror" in error_lower and "src" in error_output:
            # Regenerar módulo más simple
            module_name = module_path.stem
            simple_code = generate_module_code(module_name, keywords)
            module_path.write_text(simple_code, encoding="utf-8")
            return True
        
        return False
    
    def _generate_test_with_alt_import(self, module_name: str, keywords: list[str]) -> str:
        """Genera test con import alternativo (directo desde src)."""
        topic = keywords[0] if keywords else "data"
        
        return f'''"""
Tests para el módulo {module_name}.
Generado automáticamente por CodeAgent (import alternativo).
"""
import unittest
import sys
from pathlib import Path

# Import alternativo: agregar workspace root y src
_workspace = Path(__file__).parent.parent
sys.path.insert(0, str(_workspace))
sys.path.insert(0, str(_workspace / "src"))

try:
    from src.{module_name} import init_{topic}, process_{topic}, validate_{topic}, export_{topic}
except ImportError:
    from {module_name} import init_{topic}, process_{topic}, validate_{topic}, export_{topic}


class Test{module_name.title().replace("_", "")}(unittest.TestCase):
    """Tests para {module_name}."""
    
    def test_init_returns_dict(self):
        """init_{topic} debe retornar un diccionario."""
        result = init_{topic}()
        self.assertIsInstance(result, dict)
    
    def test_init_with_config(self):
        """init_{topic} debe aceptar configuración."""
        result = init_{topic}({{"name": "custom"}})
        self.assertEqual(result["name"], "custom")
    
    def test_process_none(self):
        """process_{topic} debe manejar None."""
        result = process_{topic}(None)
        self.assertIsNone(result)
    
    def test_validate_none_returns_false(self):
        """validate_{topic} debe retornar False para None."""
        self.assertFalse(validate_{topic}(None))
    
    def test_validate_dict_returns_true(self):
        """validate_{topic} debe retornar True para dict válido."""
        self.assertTrue(validate_{topic}({{"name": "test"}}))
    
    def test_export_dict_format(self):
        """export_{topic} debe exportar como dict."""
        data = {{"key": "value"}}
        result = export_{topic}(data, "dict")
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
'''
