"""
Regression tests for WORK_QUERY summary renderer.

Validates:
- output.formatted is always used when present
- "No encontré" only shown when total==0
- Plan info propagates correctly
"""
import unittest

from assistant_os.summary import summarize, _summarize_work


class TestWorkSummaryRenderer(unittest.TestCase):
    """Tests for _summarize_work summary generation."""

    def test_formatted_used_when_present(self):
        """output.formatted MUST be used as summary when present."""
        output = {
            "type": "WORK_QUERY",
            "formatted": "📋 2 tareas:\n• Tarea A [NEXT]\n• Tarea B [SCHEDULED]",
            "total": 2,
            "filters": {},
            "plan": {"action": "WORK_QUERY"},
        }
        
        summary, details = _summarize_work(output)
        
        assert summary == output["formatted"], (
            f"Expected formatted output, got: {summary}"
        )
        assert details["total"] == 2

    def test_formatted_with_zero_total_still_uses_formatted(self):
        """Even with total=0, if formatted is present, use it."""
        output = {
            "type": "WORK_QUERY",
            "formatted": "No hay tareas para hoy ✓",
            "total": 0,
            "filters": {},
        }
        
        summary, details = _summarize_work(output)
        
        assert summary == "No hay tareas para hoy ✓"
        assert details["total"] == 0

    def test_no_formatted_with_items_shows_count(self):
        """Without formatted but with items, show count."""
        output = {
            "type": "WORK_QUERY",
            "total": 5,
            "filters": {"project": "CELLAB"},
        }
        
        summary, details = _summarize_work(output)
        
        assert "5" in summary
        assert "tarea" in summary.lower()

    def test_no_formatted_zero_total_shows_not_found(self):
        """Without formatted and total=0, show not found message."""
        output = {
            "type": "WORK_QUERY",
            "total": 0,
            "filters": {},
        }
        
        summary, details = _summarize_work(output)
        
        assert "no se encontraron" in summary.lower() or "no encontr" in summary.lower()

    def test_filters_in_details(self):
        """Filter info should appear in details."""
        output = {
            "type": "WORK_QUERY",
            "formatted": "Tasks found",
            "total": 3,
            "filters": {
                "project": "CELLAB",
                "status": ["NEXT", "SCHEDULED"],
            },
        }
        
        summary, details = _summarize_work(output)
        
        assert "proyecto=CELLAB" in details["filters"]
        assert any("NEXT" in f for f in details["filters"])

    def test_plan_action_in_details(self):
        """Plan action should appear in details."""
        output = {
            "type": "WORK_QUERY",
            "formatted": "Result",
            "total": 1,
            "filters": {},
            "plan": {
                "action": "WORK_QUERY",
                "preview": "Consultar tareas de hoy",
            },
        }
        
        summary, details = _summarize_work(output)
        
        assert details["action"] == "WORK_QUERY"
        assert details["preview"] == "Consultar tareas de hoy"


class TestDetailsTypeAlwaysPresent(unittest.TestCase):
    """
    details['type'] must be a non-empty string in ALL branches of _summarize_work,
    including the default branch where output has no 'type' key.
    """

    def test_details_type_non_empty_when_output_has_no_type_field(self):
        """Simulates raw query result from handle_work_query (no 'type' key)."""
        output = {
            "formatted": "📋 2 tareas activas",
            "total": 2,
            "filters": {},
        }
        _summary, details = _summarize_work(output)
        self.assertIn("type", details)
        self.assertTrue(details["type"], "details['type'] must be a non-empty string")

    def test_details_type_non_empty_when_output_type_is_empty_string(self):
        """output['type'] == '' should still yield a non-empty details['type']."""
        output = {
            "type": "",
            "formatted": "Resultado",
            "total": 1,
            "filters": {},
        }
        _summary, details = _summarize_work(output)
        self.assertTrue(details["type"])

    def test_details_type_preserved_when_output_type_is_set(self):
        """When output_type is non-empty, it should be passed through unchanged."""
        output = {
            "type": "WORK_QUERY",
            "formatted": "Results",
            "total": 3,
            "filters": {},
        }
        _summary, details = _summarize_work(output)
        self.assertEqual(details["type"], "WORK_QUERY")

    def test_details_type_present_for_work_create_result(self):
        output = {
            "type": "work_create",
            "formatted": "",
            "total": 0,
            "filters": {},
            "plan": {"action": "WORK_CREATE", "preview": "Crear tarea X"},
        }
        _summary, details = _summarize_work(output)
        self.assertEqual(details["type"], "work_create")

    def test_bulk_proposal_type_still_set(self):
        """Existing bulk proposal branch must also include details['type']."""
        output = {
            "type": "work_update_bulk_proposal",
            "formatted": "",
            "total": 2,
            "filters": {},
            "candidates": [
                {"title": "T1", "status": "NEXT"},
                {"title": "T2", "status": "INBOX"},
            ],
        }
        _summary, details = _summarize_work(output)
        self.assertEqual(details["type"], "work_update_bulk_proposal")

    def test_singular_proposal_type_still_set(self):
        """Existing singular proposal branch must also include details['type']."""
        output = {
            "type": "work_update_proposal",
            "resolved": True,
            "no_match": False,
            "formatted": "",
            "total": 1,
            "filters": {},
        }
        _summary, details = _summarize_work(output)
        self.assertEqual(details["type"], "work_update_proposal")


class TestFullSummarize(unittest.TestCase):
    """Tests for full summarize() with WORK agent responses."""

    def test_summarize_work_agent_ok_response(self):
        """Full summarize() for work agent with ok status."""
        response = {
            "context_id": "test-123",
            "agent": "work",
            "status": "ok",
            "output": {
                "type": "WORK_QUERY",
                "formatted": "📋 3 tareas activas",
                "total": 3,
                "filters": {},
                "plan": {"action": "WORK_QUERY"},
            },
            "error": None,
            "ts": "2026-03-03T10:00:00Z",
        }
        
        result = summarize(response)
        
        assert result["ok"] is True
        assert "work" in result["title"]
        assert result["summary"] == "📋 3 tareas activas"

    def test_summarize_work_agent_empty_result(self):
        """Full summarize() for work agent with no tasks."""
        response = {
            "context_id": "test-456",
            "agent": "work",
            "status": "ok",
            "output": {
                "type": "WORK_QUERY",
                "total": 0,
                "filters": {"project": "NonExistent"},
            },
            "error": None,
            "ts": "2026-03-03T10:00:00Z",
        }
        
        result = summarize(response)
        
        assert result["ok"] is True
        assert "no se encontraron" in result["summary"].lower()


if __name__ == "__main__":
    unittest.main()
