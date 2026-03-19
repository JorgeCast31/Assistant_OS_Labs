"""
Tests for work_create_parser module.

Tests cover:
1. parse_work_create_fields - normal task parsing
2. parse_work_create_test_fields - test task parsing
3. validate_work_create_fields - validation logic
4. parse_and_validate_work_create - combined function
"""
import unittest


class TestParseWorkCreateFields(unittest.TestCase):
    """Tests for parse_work_create_fields function."""
    
    def test_simple_title_extraction(self):
        """Extract title from simple 'Crea una tarea: X' format."""
        from assistant_os.parsers import parse_work_create_fields
        
        fields = parse_work_create_fields("Crea una tarea: Revisar documentos")
        self.assertEqual(fields.get("title"), "Revisar documentos")
    
    def test_titulo_explicit_field(self):
        """Extract title from explicit 'Título: X' format."""
        from assistant_os.parsers import parse_work_create_fields
        
        fields = parse_work_create_fields("Título: Mi tarea importante. Proyecto: Test")
        self.assertEqual(fields.get("title"), "Mi tarea importante")
    
    def test_project_extraction(self):
        """Extract project from 'Proyecto: X' format."""
        from assistant_os.parsers import parse_work_create_fields
        
        text = "Crea una tarea: Test. Proyecto: Consultoría"
        fields = parse_work_create_fields(text)
        self.assertEqual(fields.get("project"), "Consultoría")
    
    def test_status_normalization(self):
        """Status values should be normalized to uppercase."""
        from assistant_os.parsers import parse_work_create_fields
        
        text = "Título: Test. Status: inbox"
        fields = parse_work_create_fields(text)
        self.assertEqual(fields.get("status"), "INBOX")
    
    def test_default_status_inbox(self):
        """Status should default to INBOX if not specified."""
        from assistant_os.parsers import parse_work_create_fields
        
        text = "Título: Sin status"
        fields = parse_work_create_fields(text)
        self.assertEqual(fields.get("status"), "INBOX")
    
    def test_priority_to_load_mapping(self):
        """Priority values (P1/P2/P3) should map to load."""
        from assistant_os.parsers import parse_work_create_fields
        
        text = "Título: Test. Prioridad: P1"
        fields = parse_work_create_fields(text)
        self.assertEqual(fields.get("load"), "Alta")
        
        text2 = "Título: Test2. Prioridad: P3"
        fields2 = parse_work_create_fields(text2)
        self.assertEqual(fields2.get("load"), "Baja")
    
    def test_null_values_handled(self):
        """Null-like values should be converted to None."""
        from assistant_os.parsers import parse_work_create_fields
        
        text = "Título: Test. Due: null"
        fields = parse_work_create_fields(text)
        self.assertIsNone(fields.get("due"))
    
    def test_all_fields_extraction(self):
        """All fields should be extracted from complete input."""
        from assistant_os.parsers import parse_work_create_fields
        
        text = "Título: Mi tarea. Proyecto: Test Project. Status: NEXT. Prioridad: P2. Carga cognitiva: Media. Due: 2024-01-15. Notas: Some notes here."
        fields = parse_work_create_fields(text)
        
        self.assertEqual(fields.get("title"), "Mi tarea")
        self.assertEqual(fields.get("project"), "Test Project")
        self.assertEqual(fields.get("status"), "NEXT")
        self.assertEqual(fields.get("load"), "Media")
        self.assertIn("2024-01-15", fields.get("due", ""))


class TestParseWorkCreateTestFields(unittest.TestCase):
    """Tests for parse_work_create_test_fields function (TEST DB parsing)."""
    
    def test_tarea_de_prueba_format(self):
        """'tarea de prueba: <title>' should extract title."""
        from assistant_os.parsers import parse_work_create_test_fields
        
        text = "Crea una tarea de prueba: [TEST] PS Smoke 01. Proyecto: Test"
        fields = parse_work_create_test_fields(text)
        
        self.assertIn("PS Smoke 01", fields.get("title", ""))
        self.assertEqual(fields.get("project"), "Test")
    
    def test_ui_test_format(self):
        """'ui test: <title>' should extract title."""
        from assistant_os.parsers import parse_work_create_test_fields
        
        text = "ui test: Verificar panel de confirmación"
        fields = parse_work_create_test_fields(text)
        
        self.assertIn("Verificar panel", fields.get("title", ""))
    
    def test_smoke_test_format(self):
        """'smoke test: <title>' should extract title."""
        from assistant_os.parsers import parse_work_create_test_fields
        
        text = "smoke test: Flujo completo de gasto"
        fields = parse_work_create_test_fields(text)
        
        self.assertIn("Flujo completo", fields.get("title", ""))
    
    def test_exact_bug_reproduction(self):
        """Reproduce exact bug: 'tarea de prueba: [TEST] PS Smoke 01...'"""
        from assistant_os.parsers import parse_work_create_test_fields
        
        text = "Crea una tarea de prueba: [TEST] PS Smoke 01. Proyecto: Vínculos personales. Status: INBOX. Prioridad: P3. Carga cognitiva: Media. Due: null."
        fields = parse_work_create_test_fields(text)
        
        # Title MUST NOT be empty
        title = fields.get("title", "")
        self.assertTrue(title, "Title should not be empty")
        self.assertIn("PS Smoke 01", title)
        
        # Other fields should still be extracted
        self.assertEqual(fields.get("project"), "Vínculos personales")
        self.assertEqual(fields.get("status"), "INBOX")
        self.assertEqual(fields.get("priority"), "P3")
    
    def test_test_format_with_all_fields(self):
        """Test task with all fields should parse correctly."""
        from assistant_os.parsers import parse_work_create_test_fields
        
        text = "tarea de prueba: Smoke Test PS. Proyecto: Test Project. Status: NEXT. Prioridad: P2. Carga cognitiva: Alta."
        fields = parse_work_create_test_fields(text)
        
        self.assertIn("Smoke Test PS", fields.get("title", ""))
        self.assertEqual(fields.get("project"), "Test Project")
        self.assertEqual(fields.get("status"), "NEXT")
        self.assertEqual(fields.get("priority"), "P2")


class TestValidation(unittest.TestCase):
    """Tests for validate_work_create_fields function."""
    
    def test_valid_fields_pass(self):
        """Valid fields should return ok=True."""
        from assistant_os.parsers import validate_work_create_fields
        
        fields = {
            "title": "Valid Title",
            "project": "Test Project",
            "status": "INBOX",
        }
        result = validate_work_create_fields(fields)
        
        self.assertTrue(result.get("ok"))
        self.assertIsNone(result.get("error"))
    
    def test_empty_title_fails(self):
        """Empty title should return ok=False with error."""
        from assistant_os.parsers import validate_work_create_fields
        
        fields = {
            "title": "",
            "project": "Test Project",
            "status": "INBOX",
        }
        result = validate_work_create_fields(fields)
        
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error_type"), "validation_error")
        self.assertIn("title", result.get("error", "").lower())
    
    def test_none_title_fails(self):
        """None title should return ok=False with error."""
        from assistant_os.parsers import validate_work_create_fields
        
        fields = {
            "title": None,
            "project": "Test Project",
            "status": "INBOX",
        }
        result = validate_work_create_fields(fields)
        
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error_type"), "validation_error")
    
    def test_whitespace_only_title_fails(self):
        """Whitespace-only title should return ok=False with error."""
        from assistant_os.parsers import validate_work_create_fields
        
        fields = {
            "title": "   ",
            "project": None,
            "status": "INBOX",
        }
        result = validate_work_create_fields(fields)
        
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error_type"), "validation_error")


class TestParseAndValidate(unittest.TestCase):
    """Tests for parse_and_validate_work_create combined function."""
    
    def test_valid_input_returns_ok(self):
        """Valid input should parse and validate successfully."""
        from assistant_os.parsers.work_create_parser import parse_and_validate_work_create
        
        text = "Título: Valid Task Title"
        result = parse_and_validate_work_create(text, is_test=False)
        
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("fields", {}).get("title"), "Valid Task Title")
    
    def test_empty_title_input_fails(self):
        """Input that results in empty title should fail validation."""
        from assistant_os.parsers.work_create_parser import parse_and_validate_work_create
        
        # This input has no valid title extraction
        text = "tarea de prueba:"  # No title after colon
        result = parse_and_validate_work_create(text, is_test=True)
        
        self.assertFalse(result.get("ok"))
        self.assertIn("title", result.get("error", "").lower())
    
    def test_test_mode_uses_test_parser(self):
        """is_test=True should use test-specific parser."""
        from assistant_os.parsers.work_create_parser import parse_and_validate_work_create
        
        text = "tarea de prueba: [TEST] PS Smoke 01. Proyecto: Test"
        result = parse_and_validate_work_create(text, is_test=True)
        
        self.assertTrue(result.get("ok"))
        self.assertIn("PS Smoke 01", result.get("fields", {}).get("title", ""))


class TestStatusMapExpansion(unittest.TestCase):
    """
    Verify that the expanded _STATUS_MAP in work_create_parser normalizes all
    the same vocabulary already supported by STATUS_ALIASES in work_update_parser.
    Each test passes a status via an explicit 'Status: <value>' field.
    """

    def _parse_status(self, status_word: str) -> str:
        from assistant_os.parsers import parse_work_create_fields
        fields = parse_work_create_fields(f"Título: Test. Status: {status_word}")
        return fields.get("status", "")

    # INBOX aliases
    def test_nueva_maps_to_inbox(self):
        self.assertEqual(self._parse_status("nueva"), "INBOX")

    def test_entrada_maps_to_inbox(self):
        self.assertEqual(self._parse_status("entrada"), "INBOX")

    def test_bandeja_maps_to_inbox(self):
        self.assertEqual(self._parse_status("bandeja"), "INBOX")

    # NEXT aliases
    def test_ahora_maps_to_next(self):
        self.assertEqual(self._parse_status("ahora"), "NEXT")

    def test_urgente_maps_to_next(self):
        self.assertEqual(self._parse_status("urgente"), "NEXT")

    def test_prioritario_maps_to_next(self):
        self.assertEqual(self._parse_status("prioritario"), "NEXT")

    # SCHEDULED aliases
    def test_programado_maps_to_scheduled(self):
        self.assertEqual(self._parse_status("programado"), "SCHEDULED")

    def test_agendado_maps_to_scheduled(self):
        self.assertEqual(self._parse_status("agendado"), "SCHEDULED")

    def test_agendada_maps_to_scheduled(self):
        self.assertEqual(self._parse_status("agendada"), "SCHEDULED")

    def test_calendarizado_maps_to_scheduled(self):
        self.assertEqual(self._parse_status("calendarizado"), "SCHEDULED")

    # WAITING aliases
    def test_espera_maps_to_waiting(self):
        self.assertEqual(self._parse_status("espera"), "WAITING")

    def test_bloqueado_maps_to_waiting(self):
        self.assertEqual(self._parse_status("bloqueado"), "WAITING")

    def test_bloqueada_maps_to_waiting(self):
        self.assertEqual(self._parse_status("bloqueada"), "WAITING")

    # DONE aliases
    def test_hecho_maps_to_done(self):
        self.assertEqual(self._parse_status("hecho"), "DONE")

    def test_hecha_maps_to_done(self):
        self.assertEqual(self._parse_status("hecha"), "DONE")

    def test_terminado_maps_to_done(self):
        self.assertEqual(self._parse_status("terminado"), "DONE")

    def test_completado_maps_to_done(self):
        self.assertEqual(self._parse_status("completado"), "DONE")

    def test_finished_maps_to_done(self):
        self.assertEqual(self._parse_status("finished"), "DONE")

    def test_completed_maps_to_done(self):
        self.assertEqual(self._parse_status("completed"), "DONE")

    # Pre-existing entries must still work (regression guard)
    def test_inbox_still_maps(self):
        self.assertEqual(self._parse_status("inbox"), "INBOX")

    def test_pendiente_still_maps(self):
        self.assertEqual(self._parse_status("pendiente"), "INBOX")

    def test_terminada_still_maps(self):
        self.assertEqual(self._parse_status("terminada"), "DONE")


class TestValidationIntegration(unittest.TestCase):
    """Integration tests for validation in webhook server."""
    
    def test_plan_creation_with_validation_error(self):
        """Plan should contain validation_error for invalid input."""
        from assistant_os.webhook_server import _create_plan_from_intent
        from assistant_os.contracts import ACTION_WORK_CREATE_TEST
        
        # This input triggers CREATE_TEST but has no valid title (empty after colon)
        text = "Crea una tarea de prueba:"
        intent = {}  # Empty intent - override rules will determine action
        
        plan = _create_plan_from_intent(text, intent)
        
        # Action should be WORK_CREATE_TEST (due to "tarea de prueba")
        self.assertEqual(plan.get("action"), ACTION_WORK_CREATE_TEST)
        
        # Plan should have validation_error set (title is empty/invalid)
        self.assertIsNotNone(plan.get("validation_error"))
        self.assertIn("title", plan.get("validation_error", "").lower())
    
    def test_plan_creation_with_valid_input(self):
        """Plan should NOT have validation_error for valid input."""
        from assistant_os.webhook_server import _create_plan_from_intent
        
        text = "tarea de prueba: [TEST] Valid Title. Proyecto: Test"
        intent = {"domain": "WORK", "operation": "COMMAND"}
        
        plan = _create_plan_from_intent(text, intent)
        
        # Plan should NOT have validation_error
        self.assertIsNone(plan.get("validation_error"))


if __name__ == '__main__':
    unittest.main()
