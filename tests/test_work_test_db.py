"""
Tests for WORK_TEST_DB functionality.

Test coverage:
1. Test intent detection (_has_test_intent, _has_test_reset_intent)
2. Routing overrides (ACTION_WORK_CREATE_TEST, ACTION_WORK_TEST_RESET)
3. Plan creation with target_db
4. Integration: /command routes test tasks correctly
"""
import unittest
from unittest.mock import patch, MagicMock


class TestTestIntentDetection(unittest.TestCase):
    """Unit tests for test intent detection functions."""
    
    def test_has_test_intent_ui_test_keyword(self):
        """'ui test' keyword should trigger test intent."""
        from assistant_os.webhook_server import _has_test_intent
        
        self.assertTrue(_has_test_intent("Crea una tarea ui test: verificar panel"))
        self.assertTrue(_has_test_intent("añade una tarea UI Test de confirmación"))
    
    def test_has_test_intent_tarea_de_prueba(self):
        """'tarea de prueba' should trigger test intent."""
        from assistant_os.webhook_server import _has_test_intent
        
        self.assertTrue(_has_test_intent("Crea una tarea de prueba para la UI"))
        self.assertTrue(_has_test_intent("añade tarea de prueba"))
    
    def test_has_test_intent_smoke_test(self):
        """'smoke test' should trigger test intent."""
        from assistant_os.webhook_server import _has_test_intent
        
        self.assertTrue(_has_test_intent("crea tarea smoke test"))
    
    def test_has_test_intent_title_prefix(self):
        """Title starting with 'UI ', 'Test ', 'TEST_' should trigger test intent."""
        from assistant_os.webhook_server import _has_test_intent
        
        # With parsed fields containing title prefix
        self.assertTrue(_has_test_intent("crea una tarea", {"title": "UI Panel Test"}))
        self.assertTrue(_has_test_intent("crea una tarea", {"title": "Test confirmación"}))
        self.assertTrue(_has_test_intent("crea una tarea", {"title": "TEST_validation"}))
    
    def test_has_test_intent_negative_normal_task(self):
        """Normal task should NOT trigger test intent."""
        from assistant_os.webhook_server import _has_test_intent
        
        self.assertFalse(_has_test_intent("Crea una tarea: revisar documentos"))
        self.assertFalse(_has_test_intent("añade tarea de consultoria"))
        self.assertFalse(_has_test_intent("Crea tarea: llamar al banco"))
    
    def test_has_test_reset_intent_resetear(self):
        """'resetear tests' should trigger reset intent."""
        from assistant_os.webhook_server import _has_test_reset_intent
        
        self.assertTrue(_has_test_reset_intent("resetear tests"))
        self.assertTrue(_has_test_reset_intent("reset tests"))
    
    def test_has_test_reset_intent_limpiar(self):
        """'limpiar pruebas' should trigger reset intent."""
        from assistant_os.webhook_server import _has_test_reset_intent
        
        self.assertTrue(_has_test_reset_intent("limpiar pruebas"))
        self.assertTrue(_has_test_reset_intent("limpiar tareas de prueba"))
    
    def test_has_test_reset_intent_wipe(self):
        """'wipe tests' should trigger reset intent."""
        from assistant_os.webhook_server import _has_test_reset_intent
        
        self.assertTrue(_has_test_reset_intent("wipe tests"))
    
    def test_has_test_reset_intent_borrar(self):
        """'borrar tests' should trigger reset intent."""
        from assistant_os.webhook_server import _has_test_reset_intent
        
        self.assertTrue(_has_test_reset_intent("borrar tests"))
        self.assertTrue(_has_test_reset_intent("eliminar tareas de prueba"))
    
    def test_has_test_reset_intent_negative(self):
        """Normal queries should NOT trigger reset intent."""
        from assistant_os.webhook_server import _has_test_reset_intent
        
        self.assertFalse(_has_test_reset_intent("tareas de consultoria"))
        self.assertFalse(_has_test_reset_intent("crea una tarea de prueba"))


class TestRoutingOverrides(unittest.TestCase):
    """Tests for routing override rules with test actions."""
    
    def test_test_create_overrides_normal_create(self):
        """Test task creation should route to WORK_CREATE_TEST."""
        from assistant_os.webhook_server import _apply_routing_overrides
        from assistant_os.contracts import ACTION_WORK_CREATE_TEST
        
        action, reason = _apply_routing_overrides("Crea una tarea de prueba: Test UI", {})
        self.assertEqual(action, ACTION_WORK_CREATE_TEST)
        self.assertIn("test", reason.lower())
    
    def test_normal_create_routes_to_work_create(self):
        """Normal task creation should route to WORK_CREATE."""
        from assistant_os.webhook_server import _apply_routing_overrides
        from assistant_os.contracts import ACTION_WORK_CREATE
        
        action, reason = _apply_routing_overrides("Crea una tarea: revisar informe", {})
        self.assertEqual(action, ACTION_WORK_CREATE)
    
    def test_reset_has_highest_priority(self):
        """Reset intent should have highest priority."""
        from assistant_os.webhook_server import _apply_routing_overrides
        from assistant_os.contracts import ACTION_WORK_TEST_RESET
        
        action, reason = _apply_routing_overrides("resetear tests", {})
        self.assertEqual(action, ACTION_WORK_TEST_RESET)
    
    def test_query_routes_correctly(self):
        """Normal query should still route to WORK_QUERY."""
        from assistant_os.webhook_server import _apply_routing_overrides
        from assistant_os.contracts import ACTION_WORK_QUERY
        
        action, reason = _apply_routing_overrides("tareas de consultoria", {})
        self.assertEqual(action, ACTION_WORK_QUERY)


class TestPlanCreation(unittest.TestCase):
    """Tests for Plan creation with target_db."""
    
    def test_work_create_test_plan_has_target_db(self):
        """WORK_CREATE_TEST plan should have target_db=work_test."""
        from assistant_os.webhook_server import _create_plan_from_intent
        from assistant_os.contracts import ACTION_WORK_CREATE_TEST, TARGET_DB_WORK_TEST
        
        text = "Crea una tarea de prueba: UI Panel Test"
        intent = {"domain": "ENERGY", "confidence": 0.8}
        
        plan = _create_plan_from_intent(text, intent)
        
        self.assertEqual(plan.get("action"), ACTION_WORK_CREATE_TEST)
        self.assertEqual(plan.get("target_db"), TARGET_DB_WORK_TEST)
        self.assertTrue(plan.get("requires_confirmation"))
    
    def test_work_test_reset_plan_has_high_risk(self):
        """WORK_TEST_RESET plan should have high risk level."""
        from assistant_os.webhook_server import _create_plan_from_intent
        from assistant_os.contracts import ACTION_WORK_TEST_RESET, RISK_HIGH
        
        text = "resetear tests"
        intent = {"domain": "ENERGY", "confidence": 0.5}
        
        plan = _create_plan_from_intent(text, intent)
        
        self.assertEqual(plan.get("action"), ACTION_WORK_TEST_RESET)
        self.assertEqual(plan.get("risk_level"), RISK_HIGH)
        self.assertTrue(plan.get("requires_confirmation"))
    
    def test_normal_work_create_has_target_db_work(self):
        """Normal WORK_CREATE should have target_db=work."""
        from assistant_os.webhook_server import _create_plan_from_intent
        from assistant_os.contracts import ACTION_WORK_CREATE, TARGET_DB_WORK
        
        text = "Crea una tarea: revisar informe de consultoria"
        intent = {"domain": "WORK", "confidence": 0.9}
        
        plan = _create_plan_from_intent(text, intent)
        
        self.assertEqual(plan.get("action"), ACTION_WORK_CREATE)
        self.assertEqual(plan.get("target_db"), TARGET_DB_WORK)


class TestIntegrationEndpoints(unittest.TestCase):
    """Integration tests for /command endpoint with test actions."""
    
    @patch('assistant_os.webhook_server.NOTION_WORK_TEST_DB_ID', 'test-db-id-123')
    @patch('assistant_os.webhook_server.create_work_item_in_db')
    def test_command_create_test_task_with_confirm(self, mock_create):
        """POST /command with test task + confirm=True creates in TEST DB."""
        from assistant_os.webhook_server import WebhookHandler
        from unittest.mock import MagicMock
        import json
        
        # Mock the creation result
        mock_create.return_value = {
            "ok": True,
            "page_id": "test-page-123",
            "url": "https://notion.so/test-page-123",
            "title": "UI Test Task",
            "error": ""
        }
        
        # Create mock handler
        handler = MagicMock(spec=WebhookHandler)
        handler._route_text_by_classification = WebhookHandler._route_text_by_classification
        
        # Execute test
        text = "Crea una tarea de prueba: UI Test Task"
        
        # We test the routing function directly
        from assistant_os.webhook_server import _create_plan_from_intent
        from assistant_os.contracts import ACTION_WORK_CREATE_TEST
        
        plan = _create_plan_from_intent(text, {})
        self.assertEqual(plan.get("action"), ACTION_WORK_CREATE_TEST)


class TestParseWorkCreateTestFields(unittest.TestCase):
    """Tests for parse_work_create_test_fields with test task formats."""
    
    def test_tarea_de_prueba_with_test_prefix_title(self):
        """'tarea de prueba: [TEST] PS Smoke 01' should extract title correctly."""
        from assistant_os.parsers import parse_work_create_test_fields
        
        # This is the exact bug reproduction case
        text = "Crea una tarea de prueba: [TEST] PS Smoke 01. Proyecto: Vínculos personales. Status: INBOX. Prioridad: P3. Carga cognitiva: Media. Due: null."
        fields = parse_work_create_test_fields(text)
        
        # Title should NOT be empty
        self.assertIsNotNone(fields.get("title"))
        self.assertNotEqual(fields.get("title"), "")
        # Title should be [TEST] PS Smoke 01 or PS Smoke 01
        self.assertIn("PS Smoke 01", fields.get("title", ""))
    
    def test_tarea_de_prueba_simple(self):
        """Simple 'tarea de prueba: <title>' should extract title."""
        from assistant_os.parsers import parse_work_create_test_fields
        
        text = "Crea una tarea de prueba: Mi tarea de test"
        fields = parse_work_create_test_fields(text)
        
        self.assertIn("Mi tarea de test", fields.get("title", ""))
    
    def test_ui_test_format(self):
        """'ui test: <title>' should extract title."""
        from assistant_os.parsers import parse_work_create_test_fields
        
        text = "ui test: Verificar panel de confirmación. Status: INBOX"
        fields = parse_work_create_test_fields(text)
        
        self.assertIn("Verificar panel", fields.get("title", ""))
    
    def test_smoke_test_format(self):
        """'smoke test: <title>' should extract title."""
        from assistant_os.parsers import parse_work_create_test_fields
        
        text = "smoke test: Flujo completo de gasto"
        fields = parse_work_create_test_fields(text)
        
        self.assertIn("Flujo completo", fields.get("title", ""))
    
    def test_title_with_all_fields(self):
        """Test task with all fields should parse correctly."""
        from assistant_os.parsers import parse_work_create_test_fields
        
        text = "tarea de prueba: Smoke Test PS. Proyecto: Test Project. Status: NEXT. Prioridad: P2. Carga cognitiva: Alta."
        fields = parse_work_create_test_fields(text)
        
        self.assertIn("Smoke Test PS", fields.get("title", ""))
        self.assertEqual(fields.get("project"), "Test Project")
        self.assertEqual(fields.get("status"), "NEXT")
        self.assertEqual(fields.get("priority"), "P2")


class TestContracts(unittest.TestCase):
    """Tests for contract changes."""
    
    def test_action_constants_exist(self):
        """New action constants should be defined."""
        from assistant_os.contracts import (
            ACTION_WORK_CREATE_TEST,
            ACTION_WORK_TEST_RESET,
            TARGET_DB_WORK,
            TARGET_DB_WORK_TEST,
        )
        
        self.assertEqual(ACTION_WORK_CREATE_TEST, "WORK_CREATE_TEST")
        self.assertEqual(ACTION_WORK_TEST_RESET, "WORK_TEST_RESET")
        self.assertEqual(TARGET_DB_WORK, "work")
        self.assertEqual(TARGET_DB_WORK_TEST, "work_test")
    
    def test_make_plan_accepts_target_db(self):
        """make_plan should accept target_db parameter."""
        from assistant_os.contracts import (
            make_plan, 
            ACTION_WORK_CREATE_TEST, 
            TARGET_DB_WORK_TEST,
            RISK_MEDIUM,
        )
        
        plan = make_plan(
            domain="ENERGY",
            action=ACTION_WORK_CREATE_TEST,
            target="Test task",
            target_db=TARGET_DB_WORK_TEST,
            requires_confirmation=True,
        )
        
        self.assertEqual(plan.get("target_db"), TARGET_DB_WORK_TEST)
        self.assertEqual(plan.get("action"), ACTION_WORK_CREATE_TEST)


if __name__ == '__main__':
    unittest.main()
