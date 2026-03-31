"""
Integration tests for WORK_DELETE functionality.

Tests:
1. /command/summary returns plan_confirmation_required for delete
2. Notion helper functions (query, archive, move)
3. Canonical delete execution via work_pipeline._work_delete_execute:
   - Notion unavailable → NotionUnavailable error
   - No delete criteria → ValidationError
"""
import unittest
from unittest.mock import patch, MagicMock
import json


class TestWorkDeleteIntegration(unittest.TestCase):
    """Integration tests for work delete flow."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Import here to allow patching
        pass
    
    @patch('assistant_os.webhook_server.NOTION_WORK_TRASH_DB_ID', 'test-trash-db-id')
    @patch('assistant_os.config.NOTION_WORK_DB_ID', 'test-work-db-id')
    @patch('assistant_os.config.NOTION_TOKEN', 'test-token')
    def test_delete_plan_requires_confirmation(self):
        """Delete plan should require confirmation."""
        from assistant_os.webhook_server import _create_plan_from_intent
        from assistant_os.contracts import ACTION_WORK_DELETE, RISK_MEDIUM
        
        # Create a minimal intent mock
        intent = {
            "domain": "WORK",
            "operation": "COMMAND",
            "confidence": 0.9,
            "alternatives": [],
        }
        
        # Create plan for delete action (keyword-based = RISK_MEDIUM)
        plan = _create_plan_from_intent("elimina tareas que contengan: UI", intent)
        
        # Verify plan properties
        self.assertEqual(plan.get("action"), ACTION_WORK_DELETE)
        self.assertTrue(plan.get("requires_confirmation"))
        self.assertEqual(plan.get("risk_level"), RISK_MEDIUM)
        self.assertFalse(plan.get("filters", {}).get("delete_all", False))
    
    @patch('assistant_os.integrations.notion.NOTION_WORK_TEST_DB_ID', 'test-test-db-id')
    @patch('assistant_os.integrations.notion.NOTION_TOKEN', 'test-token')
    @patch('assistant_os.integrations.notion.REQUESTS_AVAILABLE', True)
    def test_delete_test_plan_properties(self):
        """Delete test plan should target work_test and use archive mode."""
        from assistant_os.webhook_server import _create_plan_from_intent
        from assistant_os.contracts import ACTION_WORK_DELETE_TEST, TARGET_DB_WORK_TEST
        
        intent = {
            "domain": "WORK",
            "operation": "COMMAND",
            "confidence": 0.9,
            "alternatives": [],
        }
        
        plan = _create_plan_from_intent("elimina tareas de prueba que contengan: smoke", intent)
        
        self.assertEqual(plan.get("action"), ACTION_WORK_DELETE_TEST)
        self.assertEqual(plan.get("target_db"), TARGET_DB_WORK_TEST)
        self.assertTrue(plan.get("requires_confirmation"))
        
        # Check filters contain delete_mode=archive
        filters = plan.get("filters", {})
        self.assertEqual(filters.get("delete_mode"), "archive")
    
    def test_delete_validation_error_for_empty_keywords(self):
        """Delete with no keywords should produce validation error."""
        from assistant_os.webhook_server import _create_plan_from_intent
        
        intent = {
            "domain": "WORK",
            "operation": "COMMAND",
            "confidence": 0.9,
            "alternatives": [],
        }
        
        plan = _create_plan_from_intent("elimina tareas", intent)
        
        # Should have validation error
        self.assertIsNotNone(plan.get("validation_error"))
    
    def test_delete_all_no_validation_error(self):
        """Delete all (with 'de prueba' keyword filter) should NOT produce validation error.
        
        Note: 'elimina todas las tareas de prueba' extracts keywords=['prueba'], 
        which means delete_all=False per invariant: 'delete_all=true ONLY when no keywords/filters exist.'
        This still should not produce validation_error since keywords ARE present.
        """
        from assistant_os.webhook_server import _create_plan_from_intent
        
        intent = {
            "domain": "WORK",
            "operation": "COMMAND",
            "confidence": 0.9,
            "alternatives": [],
        }
        
        plan = _create_plan_from_intent("elimina todas las tareas de prueba", intent)
        
        # Should NOT have validation error (keywords are present)
        self.assertIsNone(plan.get("validation_error"))
        
        # With keywords present, delete_all should be False (invariant D)
        filters = plan.get("filters", {})
        self.assertEqual(filters.get("keywords"), ["prueba"])
        self.assertFalse(filters.get("delete_all"))
    
    def test_delete_all_no_keywords(self):
        """Delete all WITHOUT keywords should set delete_all=True."""
        from assistant_os.parsers.work_delete_parser import parse_work_delete_intent
        
        # This phrase has no keywords filter - should be delete_all=True
        result = parse_work_delete_intent("elimina todas las tareas")
        self.assertTrue(result.get("is_delete"))
        query = result.get("query", {})
        self.assertTrue(query.get("delete_all"))
        self.assertEqual(query.get("keywords"), [])


class TestNotionDeleteFunctions(unittest.TestCase):
    """Tests for Notion delete helper functions."""
    
    @patch('assistant_os.integrations.notion.REQUESTS_AVAILABLE', True)
    @patch('assistant_os.integrations.notion.NOTION_TOKEN', 'test-token')
    @patch('assistant_os.integrations.notion.requests')
    def test_query_work_items_by_keywords(self, mock_requests):
        """Test keyword-based query."""
        from assistant_os.integrations.notion import query_work_items_by_keywords
        
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "properties": {
                        "Name": {"title": [{"plain_text": "UI Test Task"}]},
                        "Status": {"status": {"name": "INBOX"}}
                    }
                },
                {
                    "id": "page-2",
                    "properties": {
                        "Name": {"title": [{"plain_text": "Test Smoke"}]},
                        "Status": {"status": {"name": "SCHEDULED"}}
                    }
                }
            ]
        }
        mock_requests.post.return_value = mock_response
        
        result = query_work_items_by_keywords(
            "test-db-id",
            keywords=["UI", "Test"],
            op="OR",
            limit=100
        )
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].get("id"), "page-1")
        self.assertEqual(result[0].get("title"), "UI Test Task")
    
    @patch('assistant_os.integrations.notion.REQUESTS_AVAILABLE', True)
    @patch('assistant_os.integrations.notion.NOTION_TOKEN', 'test-token')
    @patch('assistant_os.integrations.notion.requests')
    def test_archive_pages_batch(self, mock_requests):
        """Test batch archive operation."""
        from assistant_os.integrations.notion import archive_pages
        
        # Mock successful archive
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_requests.patch.return_value = mock_response
        
        page_ids = ["page-1", "page-2", "page-3"]
        archived_count = archive_pages(page_ids)
        
        # All should be archived
        self.assertEqual(archived_count, 3)
        self.assertEqual(mock_requests.patch.call_count, 3)
    
    @patch('assistant_os.integrations.notion.REQUESTS_AVAILABLE', True)
    @patch('assistant_os.integrations.notion.NOTION_TOKEN', 'test-token')
    @patch('assistant_os.integrations.notion.requests')
    def test_move_pages_to_db(self, mock_requests):
        """Test move to trash DB operation."""
        from assistant_os.integrations.notion import move_pages_to_db
        
        # Mock get page response
        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {
            "id": "page-1",
            "properties": {
                "Name": {"title": [{"plain_text": "Test Task"}]}
            }
        }
        
        # Mock create page response
        mock_post_response = MagicMock()
        mock_post_response.status_code = 201
        mock_post_response.json.return_value = {"id": "new-page-1"}
        
        # Mock archive response
        mock_patch_response = MagicMock()
        mock_patch_response.status_code = 200
        
        mock_requests.get.return_value = mock_get_response
        mock_requests.post.return_value = mock_post_response
        mock_requests.patch.return_value = mock_patch_response
        
        page_ids = ["page-1"]
        moved_count = move_pages_to_db(page_ids, "trash-db-id")
        
        self.assertEqual(moved_count, 1)


class TestWorkDeleteExecution(unittest.TestCase):
    """Tests for the canonical delete execution path (_work_delete_execute in work_pipeline)."""

    @patch('assistant_os.integrations.work_gateway.check_notion_available', return_value=False)
    @patch('assistant_os.integrations.work_gateway.get_notion_status')
    def test_delete_fails_without_notion(self, mock_status, mock_available):
        """Delete returns ok=False DomainResult when Notion is unavailable."""
        from assistant_os.pipelines.work_pipeline import _work_delete_execute
        from assistant_os.contracts import make_plan, ACTION_WORK_DELETE, RISK_HIGH

        mock_status.return_value = {"last_error": {"message": "Notion not configured"}}

        plan = make_plan(
            domain="WORK",
            action=ACTION_WORK_DELETE,
            target="test",
            requires_confirmation=True,
            risk_level=RISK_HIGH,
            filters={"keywords": ["UI"], "op": "OR"},
        )

        result = _work_delete_execute(plan, "test-context")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "NotionUnavailable")

    @patch('assistant_os.integrations.work_gateway.check_notion_available', return_value=True)
    def test_delete_fails_without_criteria(self, mock_available):
        """Delete with no keywords and no delete_all returns ok=False with ValidationError."""
        from assistant_os.pipelines.work_pipeline import _work_delete_execute
        from assistant_os.contracts import make_plan, ACTION_WORK_DELETE, RISK_HIGH

        plan = make_plan(
            domain="WORK",
            action=ACTION_WORK_DELETE,
            target="test",
            requires_confirmation=True,
            risk_level=RISK_HIGH,
            filters={},  # no keywords, no delete_all
        )

        result = _work_delete_execute(plan, "test-context")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "ValidationError")


if __name__ == "__main__":
    unittest.main()
