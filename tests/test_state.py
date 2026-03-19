"""
Tests para el manejo de estado (memory/state.py).
"""
import json
import tempfile
import unittest
from pathlib import Path

# Importamos y parcheamos STATE_FILE antes de importar state
from assistant_os import config
original_state_file = config.STATE_FILE

from assistant_os.memory import state


class TestStateManagement(unittest.TestCase):
    """Tests para load_state, save_state, update_agent_state."""
    
    def setUp(self):
        """Crear archivo temporal para tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_state_file = Path(self.temp_dir) / "state.json"
        # Parchear STATE_FILE
        state.STATE_FILE = self.temp_state_file
        config.STATE_FILE = self.temp_state_file
    
    def tearDown(self):
        """Limpiar archivos temporales."""
        if self.temp_state_file.exists():
            self.temp_state_file.unlink()
        # Restaurar
        state.STATE_FILE = original_state_file
        config.STATE_FILE = original_state_file
    
    def test_load_state_creates_default_if_missing(self):
        """load_state debe crear estado por defecto si no existe archivo."""
        # Asegurar que no existe
        if self.temp_state_file.exists():
            self.temp_state_file.unlink()
        
        loaded = state.load_state()
        
        self.assertIn("session", loaded)
        self.assertIn("agents", loaded)
        self.assertIn("code", loaded["agents"])
        self.assertIn("doc", loaded["agents"])
        self.assertIn("jobs", loaded["agents"])
        self.assertIn("biz", loaded["agents"])
    
    def test_load_state_creates_default_if_corrupted(self):
        """load_state debe crear default si JSON está corrupto."""
        self.temp_state_file.parent.mkdir(parents=True, exist_ok=True)
        self.temp_state_file.write_text("{ invalid json }", encoding="utf-8")
        
        loaded = state.load_state()
        
        self.assertIn("session", loaded)
        self.assertIn("agents", loaded)
    
    def test_save_state_writes_valid_json(self):
        """save_state debe escribir JSON válido."""
        test_state = {
            "session": {"id": "test-123", "started_at": "2024-01-01", "last_active": "2024-01-01"},
            "agents": {
                "code": {"last_task": "test", "status": "ok", "iterations": 1},
                "doc": {"last_task": None, "status": "idle"},
                "jobs": {"last_task": None, "status": "idle", "results_count": 0},
                "biz": {"last_task": None, "status": "idle"},
            },
        }
        
        state.save_state(test_state)
        
        self.assertTrue(self.temp_state_file.exists())
        loaded_raw = self.temp_state_file.read_text(encoding="utf-8")
        loaded = json.loads(loaded_raw)
        self.assertEqual(loaded["session"]["id"], "test-123")
    
    def test_update_agent_state_only_affects_its_namespace(self):
        """update_agent_state solo debe modificar el namespace del agente."""
        # Crear estado inicial
        initial = state.load_state()
        
        # Actualizar solo 'code'
        state.update_agent_state("code", {"last_task": "nueva tarea", "status": "running"})
        
        # Verificar que 'code' cambió
        updated = state.load_state()
        self.assertEqual(updated["agents"]["code"]["last_task"], "nueva tarea")
        self.assertEqual(updated["agents"]["code"]["status"], "running")
        
        # Verificar que otros agentes NO cambiaron
        self.assertEqual(updated["agents"]["doc"]["status"], "idle")
        self.assertEqual(updated["agents"]["jobs"]["status"], "idle")
        self.assertEqual(updated["agents"]["biz"]["status"], "idle")
    
    def test_update_agent_state_updates_last_active(self):
        """update_agent_state debe actualizar session.last_active."""
        initial = state.load_state()
        initial_last_active = initial["session"]["last_active"]
        
        # Esperar un momento y actualizar
        import time
        time.sleep(0.01)
        
        state.update_agent_state("doc", {"last_task": "docs"})
        
        updated = state.load_state()
        # last_active debe ser diferente (más reciente)
        self.assertNotEqual(updated["session"]["last_active"], initial_last_active)


if __name__ == "__main__":
    unittest.main()
