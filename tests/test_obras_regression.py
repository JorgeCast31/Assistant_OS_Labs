"""
Regression tests for UI chips and domain classification.

Covers:
1. "info sobre mis obras" → WORK query with eiProta domain filter
2. "estado de obras eiprota" → WORK query with eiProta project filter
3. "tareas status WAITING" → WORK query with status=WAITING

These tests ensure that:
- Classification routes to WORK query (is_work_query=True)
- Domain/project filters are correctly parsed
- UI chips are triggered when plan has tasks
"""
import unittest
from unittest.mock import patch, MagicMock

from assistant_os.classifier import classify_text, is_work_query, parse_work_query_filters
from assistant_os.contracts import ClassifyRequest
from assistant_os.taxonomy import parse_target_from_text


class TestObrasClassification(unittest.TestCase):
    """Test classification of 'obras' queries routes to EIPROTA/WORK."""
    
    def test_info_sobre_mis_obras_domain(self):
        """'info sobre mis obras' should classify as EIPROTA domain."""
        req = ClassifyRequest(text='info sobre mis obras')
        result = classify_text(req)
        
        self.assertEqual(result["domain"], "EIPROTA")
        self.assertGreater(result["confidence"], 0.7)
    
    def test_info_sobre_mis_obras_is_work_query(self):
        """'info sobre mis obras' should be recognized as work query."""
        text = 'info sobre mis obras'
        result = is_work_query(text, "EIPROTA")
        
        self.assertTrue(result, "'info sobre mis obras' should trigger work query")
    
    def test_info_sobre_mis_obras_filters(self):
        """'info sobre mis obras' should parse domain=eiProta filter."""
        filters = parse_work_query_filters('info sobre mis obras')
        
        self.assertEqual(filters.get("domain"), "eiProta")
        self.assertEqual(filters["_target_audit"]["target_type"], "domain")
    
    def test_estado_de_obras_eiprota_classification(self):
        """'estado de obras eiprota' should classify as EIPROTA domain."""
        req = ClassifyRequest(text='estado de obras eiprota')
        result = classify_text(req)
        
        self.assertEqual(result["domain"], "EIPROTA")
    
    def test_estado_de_obras_eiprota_is_work_query(self):
        """'estado de obras eiprota' should be recognized as work query."""
        text = 'estado de obras eiprota'
        result = is_work_query(text, "EIPROTA")
        
        self.assertTrue(result, "'estado de obras eiprota' should trigger work query")
    
    def test_estado_de_obras_eiprota_filters(self):
        """'estado de obras eiprota' should parse project_key=eiprota filter."""
        filters = parse_work_query_filters('estado de obras eiprota')
        
        # "eiprota" alias maps to key for ProjectKey filtering
        self.assertEqual(filters.get("project_key"), "eiprota")
        self.assertEqual(filters["_target_audit"]["target_type"], "key")


class TestStatusWaitingQuery(unittest.TestCase):
    """Test 'tareas status WAITING' query."""
    
    def test_status_waiting_is_work_query(self):
        """'tareas status WAITING' should be recognized as work query."""
        text = 'tareas status WAITING'
        result = is_work_query(text)
        
        self.assertTrue(result, "'tareas status WAITING' should trigger work query")
    
    def test_status_waiting_filters(self):
        """'tareas status WAITING' should parse status=['WAITING'] filter."""
        filters = parse_work_query_filters('tareas status WAITING')
        
        self.assertIn("status", filters)
        self.assertIn("WAITING", filters["status"])


class TestWorkQueryRendersChips(unittest.TestCase):
    """Test that WORK query response activates renderPlanControls."""
    
    @patch('assistant_os.integrations.notion.query_work_db')
    @patch('assistant_os.integrations.notion.check_notion_available')
    def test_work_query_with_tasks_returns_plan(self, mock_check, mock_query):
        """WORK query with tasks should return plan items for chip rendering."""
        from assistant_os.chat_core import process_chat_input
        from assistant_os.contracts import ChatSession
        
        # Mock Notion returning tasks
        mock_check.return_value = True
        mock_query.return_value = {
            "ok": True,
            "items": [
                {"title": "Tarea 1", "status": "WAITING"},
                {"title": "Tarea 2", "status": "WAITING"},
            ],
            "elapsed_ms": 100,
            "status_filter_applied": True,
            "domain_filter_applied": False,
            "project_filter_applied": False,
            "filters_summary": {"status": "WAITING"},
            "notion_filter_json": '{}',
        }
        
        session = ChatSession(context_id="test-123")
        response = process_chat_input("tareas status WAITING", session)
        
        # Response should have domain=WORK and plan with items
        self.assertEqual(response["domain"], "WORK")
        self.assertEqual(response["intent"], "query")
        self.assertGreater(len(response.get("plan", [])), 0)
        
        # UI should render chips when plan.length > 0 and intent != query_error
        # (This verifies the backend returns correct data for chip rendering)
        self.assertNotEqual(response["intent"], "query_error")


class TestTaxonomyObrasAlias(unittest.TestCase):
    """Test 'obras' alias resolution in taxonomy."""
    
    def test_obras_resolves_to_eiprota(self):
        """'obras' should resolve to eiProta domain."""
        target = parse_target_from_text("info sobre mis obras")
        
        self.assertEqual(target["target_type"], "domain")
        self.assertEqual(target["value"], "eiProta")
    
    def test_eiprota_explicit_resolves_to_key(self):
        """'eiprota' explicit should resolve to key for ProjectKey filtering."""
        target = parse_target_from_text("estado de obras eiprota")
        
        # "eiprota" alias maps to key slug for ProjectKey filtering
        self.assertEqual(target["target_type"], "key")
        self.assertEqual(target["value"], "eiprota")


class TestProjectKeySlugNormalization(unittest.TestCase):
    """Test ProjectKey slug normalization for various input formats."""
    
    def test_edapt3_normalizes_to_eda_pt3(self):
        """'edapt3' should normalize to key 'eda_pt3'."""
        target = parse_target_from_text("tareas edapt3")
        
        self.assertEqual(target["target_type"], "key")
        self.assertEqual(target["value"], "eda_pt3")
    
    def test_eda_pt3_with_underscore(self):
        """'eda_pt3' exact slug should match."""
        target = parse_target_from_text("tareas eda_pt3")
        
        self.assertEqual(target["target_type"], "key")
        self.assertEqual(target["value"], "eda_pt3")
    
    def test_eda_space_pt3(self):
        """'eda pt3' with space should match."""
        target = parse_target_from_text("tareas eda pt3")
        
        self.assertEqual(target["target_type"], "key")
        self.assertEqual(target["value"], "eda_pt3")
    
    def test_evangelio_normalizes_to_key(self):
        """'evangelio' should map to key 'evangelio_iii'."""
        target = parse_target_from_text("tareas evangelio")
        
        self.assertEqual(target["target_type"], "key")
        self.assertEqual(target["value"], "evangelio_iii")
    
    def test_tti_normalizes_to_key(self):
        """'tti' should map to key 'tti_eco'."""
        target = parse_target_from_text("tareas tti")
        
        self.assertEqual(target["target_type"], "key")
        self.assertEqual(target["value"], "tti_eco")
    
    def test_thcye_direct_key_match(self):
        """'thcye' should map directly to key."""
        target = parse_target_from_text("tareas thcye")
        
        self.assertEqual(target["target_type"], "key")
        self.assertEqual(target["value"], "thcye")
    
    def test_project_key_in_filters(self):
        """Key slug should produce project_key filter."""
        filters = parse_work_query_filters("tareas thcye")
        
        self.assertIn("project_key", filters)
        self.assertEqual(filters["project_key"], "thcye")
        self.assertNotIn("project", filters)  # Should NOT have project


if __name__ == '__main__':
    unittest.main()
