"""
Unit tests for WORK_DELETE functionality.

Tests:
1. Delete intent detection priority over WORK_QUERY
2. Parsing keywords: "UI OR test", "UI, test", quotes
3. Empty keyword → validation_error
4. Routing overrides for delete intent
5. Plan creation for delete actions
"""
import unittest
from unittest.mock import patch, MagicMock


class TestWorkDeleteParser(unittest.TestCase):
    """Tests for work_delete_parser module."""
    
    def test_has_delete_intent_basic(self):
        """Basic delete intent detection."""
        from assistant_os.parsers.work_delete_parser import has_delete_intent
        
        # Should detect delete intent
        self.assertTrue(has_delete_intent("elimina tareas que contengan: UI"))
        self.assertTrue(has_delete_intent("borra las tareas de prueba"))
        self.assertTrue(has_delete_intent("borrar tareas UI"))
        self.assertTrue(has_delete_intent("eliminar tareas test"))
        self.assertTrue(has_delete_intent("limpia las tareas"))
        self.assertTrue(has_delete_intent("wipe tasks"))
        
        # Should NOT detect delete intent
        self.assertFalse(has_delete_intent("tareas de consultoria"))
        self.assertFalse(has_delete_intent("estado de tareas"))
        self.assertFalse(has_delete_intent("crea una tarea"))
        self.assertFalse(has_delete_intent("elimina la basura"))  # no "tarea"
    
    def test_parse_keywords_or(self):
        """Parse keywords with OR operator."""
        from assistant_os.parsers.work_delete_parser import parse_work_delete_intent
        
        result = parse_work_delete_intent("elimina tareas que contengan: UI OR test")
        self.assertTrue(result.get("is_delete"))
        query = result.get("query", {})
        self.assertIn("UI", query.get("keywords", []))
        self.assertIn("test", query.get("keywords", []))
        self.assertEqual(query.get("op"), "OR")
    
    def test_parse_keywords_comma(self):
        """Parse keywords separated by comma."""
        from assistant_os.parsers.work_delete_parser import parse_work_delete_intent
        
        result = parse_work_delete_intent("elimina tareas que contengan: UI, test, smoke")
        self.assertTrue(result.get("is_delete"))
        query = result.get("query", {})
        keywords = query.get("keywords", [])
        self.assertIn("UI", keywords)
        self.assertIn("test", keywords)
        self.assertIn("smoke", keywords)
    
    def test_parse_keywords_and(self):
        """Parse keywords with AND operator."""
        from assistant_os.parsers.work_delete_parser import parse_work_delete_intent
        
        result = parse_work_delete_intent("elimina tareas que contengan: UI AND test")
        self.assertTrue(result.get("is_delete"))
        query = result.get("query", {})
        self.assertEqual(query.get("op"), "AND")
    
    def test_empty_keywords_validation_error(self):
        """Empty keywords should produce validation error."""
        from assistant_os.parsers.work_delete_parser import parse_work_delete_intent
        
        result = parse_work_delete_intent("elimina tareas")
        self.assertTrue(result.get("is_delete"))
        self.assertIsNotNone(result.get("validation_error"))
    
    def test_delete_all_no_validation_error(self):
        """'todas las tareas' should NOT produce validation error."""
        from assistant_os.parsers.work_delete_parser import parse_work_delete_intent
        
        result = parse_work_delete_intent("elimina todas las tareas")
        self.assertTrue(result.get("is_delete"))
        query = result.get("query", {})
        self.assertTrue(query.get("delete_all"))
        self.assertIsNone(result.get("validation_error"))
    
    def test_target_db_test(self):
        """Test indicators should target work_test DB."""
        from assistant_os.parsers.work_delete_parser import parse_work_delete_intent
        
        result = parse_work_delete_intent("elimina tareas de prueba que contengan: smoke")
        self.assertTrue(result.get("is_delete"))
        query = result.get("query", {})
        self.assertEqual(query.get("target_db"), "work_test")
    
    def test_target_db_work(self):
        """Default should target work DB."""
        from assistant_os.parsers.work_delete_parser import parse_work_delete_intent
        
        result = parse_work_delete_intent("elimina tareas que contengan: UI")
        self.assertTrue(result.get("is_delete"))
        query = result.get("query", {})
        self.assertEqual(query.get("target_db"), "work")
    
    def test_include_next_flag(self):
        """'incluye NEXT' should set include_next flag."""
        from assistant_os.parsers.work_delete_parser import parse_work_delete_intent
        
        result = parse_work_delete_intent("elimina tareas que contengan: test incluye NEXT")
        self.assertTrue(result.get("is_delete"))
        query = result.get("query", {})
        self.assertTrue(query.get("include_next"))


class TestWorkDeleteRouting(unittest.TestCase):
    """Tests for routing overrides for delete intent."""
    
    def test_delete_override_priority_over_query(self):
        """Delete intent should override WORK_QUERY routing."""
        from assistant_os.webhook_server import _apply_routing_overrides
        from assistant_os.contracts import ACTION_WORK_DELETE
        
        # "elimina tareas" should route to DELETE, not QUERY
        action, reason = _apply_routing_overrides("elimina tareas que contengan: UI", {})
        self.assertEqual(action, ACTION_WORK_DELETE)
        self.assertIn("delete", reason.lower())
    
    def test_delete_test_routing(self):
        """Test delete should route to WORK_DELETE_TEST."""
        from assistant_os.webhook_server import _apply_routing_overrides
        from assistant_os.contracts import ACTION_WORK_DELETE_TEST
        
        action, reason = _apply_routing_overrides("elimina tareas de prueba: smoke", {})
        self.assertEqual(action, ACTION_WORK_DELETE_TEST)
    
    def test_query_routing_unchanged(self):
        """Regular queries should still route to WORK_QUERY."""
        from assistant_os.webhook_server import _apply_routing_overrides
        from assistant_os.contracts import ACTION_WORK_QUERY
        
        action, reason = _apply_routing_overrides("tareas de consultoria", {})
        self.assertEqual(action, ACTION_WORK_QUERY)
    
    def test_create_routing_unchanged(self):
        """Create intents should still route to WORK_CREATE."""
        from assistant_os.webhook_server import _apply_routing_overrides
        from assistant_os.contracts import ACTION_WORK_CREATE
        
        action, reason = _apply_routing_overrides("crea una tarea: revisar informe", {})
        self.assertEqual(action, ACTION_WORK_CREATE)


class TestWorkDeletePreview(unittest.TestCase):
    """Tests for delete preview generation."""
    
    def test_preview_with_keywords(self):
        """Preview should include keywords."""
        from assistant_os.parsers.work_delete_parser import generate_delete_preview, DeleteQuery
        
        query = DeleteQuery(
            keywords=["UI", "test"],
            op="OR",
            delete_all=False,
            target_db="work",
            include_next=False
        )
        
        preview = generate_delete_preview(query)
        self.assertIn("UI", preview)
        self.assertIn("test", preview)
        self.assertIn("OR", preview)
    
    def test_preview_delete_all(self):
        """Preview should warn about delete all."""
        from assistant_os.parsers.work_delete_parser import generate_delete_preview, DeleteQuery
        
        query = DeleteQuery(
            keywords=[],
            op="OR",
            delete_all=True,
            target_db="work",
            include_next=False
        )
        
        preview = generate_delete_preview(query)
        self.assertIn("TODAS", preview)
    
    def test_preview_test_db(self):
        """Preview should mention TEST DB when targeting it."""
        from assistant_os.parsers.work_delete_parser import generate_delete_preview, DeleteQuery
        
        query = DeleteQuery(
            keywords=["smoke"],
            op="OR",
            delete_all=False,
            target_db="work_test",
            include_next=False
        )
        
        preview = generate_delete_preview(query)
        self.assertIn("TEST", preview)


class TestWorkDeleteContracts(unittest.TestCase):
    """Tests for delete-related contracts."""
    
    def test_action_constants_exist(self):
        """WORK_DELETE action constants should exist."""
        from assistant_os.contracts import (
            ACTION_WORK_DELETE,
            ACTION_WORK_DELETE_TEST,
            DELETE_MODE_TRASH,
            DELETE_MODE_ARCHIVE,
            TARGET_DB_WORK_TRASH,
        )
        
        self.assertEqual(ACTION_WORK_DELETE, "WORK_DELETE")
        self.assertEqual(ACTION_WORK_DELETE_TEST, "WORK_DELETE_TEST")
        self.assertEqual(DELETE_MODE_TRASH, "trash")
        self.assertEqual(DELETE_MODE_ARCHIVE, "archive")
        self.assertEqual(TARGET_DB_WORK_TRASH, "work_trash")


if __name__ == "__main__":
    unittest.main()
