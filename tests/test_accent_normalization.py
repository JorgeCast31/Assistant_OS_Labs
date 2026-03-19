"""
Tests for accent-insensitive taxonomy parsing.

Regression tests for bug: "tareas consultoría" vs "tareas consultoria"
should resolve to the same Domain target.
"""
import unittest
from assistant_os.taxonomy import parse_target_from_text, normalize_key


class TestNormalizeKey(unittest.TestCase):
    """Test normalize_key helper function."""
    
    def test_removes_accent_i(self):
        """Accent í should be normalized to i."""
        self.assertEqual(normalize_key("consultoría"), "consultoria")
    
    def test_removes_accent_e(self):
        """Accent é should be normalized to e."""
        self.assertEqual(normalize_key("búsqueda"), "busqueda")
    
    def test_lowercase(self):
        """Should lowercase."""
        self.assertEqual(normalize_key("CONSULTORIA"), "consultoria")
    
    def test_collapse_whitespace(self):
        """Should collapse multiple spaces."""
        self.assertEqual(normalize_key("estado  del   arte"), "estado del arte")
    
    def test_strip(self):
        """Should strip leading/trailing whitespace."""
        self.assertEqual(normalize_key("  consultoria  "), "consultoria")


class TestAccentInsensitiveParsing(unittest.TestCase):
    """Test that accented and non-accented inputs resolve the same."""
    
    def test_tareas_consultoria_with_accent(self):
        """'tareas consultoría' should resolve to proyecto.
        
        UPDATED: Now maps to Proyecto "Consultoría" not Domain "Consultoria"
        because Proyecto has actual tasks, Domain has none.
        """
        result = parse_target_from_text("tareas consultoría")
        self.assertNotEqual(result["target_type"], "none")
        self.assertEqual(result["target_type"], "project")
        self.assertEqual(result["value"], "Consultoría")
    
    def test_tareas_consultoria_without_accent(self):
        """'tareas consultoria' should resolve to same proyecto."""
        result = parse_target_from_text("tareas consultoria")
        self.assertEqual(result["target_type"], "project")
        self.assertEqual(result["value"], "Consultoría")
    
    def test_estado_sobre_tareas_de_consultoria(self):
        """Full phrase with accent should resolve."""
        result = parse_target_from_text("Estado sobre tareas de consultoría")
        self.assertEqual(result["target_type"], "project")
        self.assertEqual(result["value"], "Consultoría")
    
    def test_busqueda_laboral_with_accent(self):
        """'búsqueda laboral' with accent should match."""
        result = parse_target_from_text("tareas búsqueda laboral")
        # Should match alias "busqueda laboral" or "busqueda de trabajo"
        self.assertNotEqual(result["target_type"], "none")
    
    def test_tesis_with_accent_insensitive(self):
        """'tesis' (no accent) should work for domain Tesis."""
        result = parse_target_from_text("tareas tesis")
        self.assertEqual(result["target_type"], "domain")
        self.assertEqual(result["value"], "Tesis")


class TestPrepositionNotConsumed(unittest.TestCase):
    """Regression: 'con' should NOT be consumed from 'consultoria'."""
    
    def test_tareas_consultoria_not_sultoria(self):
        """'tareas consultoria' should NOT become 'sultoria'.
        
        UPDATED: Now maps to project, not domain.
        """
        result = parse_target_from_text("tareas consultoria")
        # If bug exists, result would be 'none' because 'sultoria' doesn't match
        self.assertEqual(result["target_type"], "project")
    
    def test_tareas_con_something(self):
        """'tareas con algo' should still work if 'con' is legit preposition."""
        # This is edge case - 'con' as actual preposition
        # For now, we just verify it doesn't break
        result = parse_target_from_text("tareas con thcye")
        # Should resolve thcye
        self.assertEqual(result["target_type"], "key")


if __name__ == "__main__":
    unittest.main()
