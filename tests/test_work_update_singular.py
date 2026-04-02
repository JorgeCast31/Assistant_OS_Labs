"""
Unit tests for WebhookHandler._execute_work_update (singular update path).

Mocks:
  - check_notion_available / get_notion_status
  - get_editable_field_options
  - update_work_item

Test matrix:
  - page_id missing → ValidationError
  - Notion unavailable → NotionUnavailable error
  - No valid changes after validation → ValidationError
  - Field not in ALLOWED_FIELDS → skipped, ValidationError if only change
  - Value invalid (no options constraint) → accepted
  - Value invalid against Notion options (no fuzzy match) → skipped / ValidationError
  - Value with fuzzy match → accepted with corrected casing
  - Exact match: update_work_item returns ok → success response
  - update_work_item returns not ok → NotionUpdateError
  - Multiple proposed changes: some valid, some invalid → apply only valid ones
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from assistant_os.webhook_server import WebhookHandler
from assistant_os.contracts import make_plan, ACTION_WORK_UPDATE, RISK_MEDIUM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CTX = "ctx-update-test"


def _plan_with(page_id, proposed_changes):
    plan = make_plan(domain="WORK", action=ACTION_WORK_UPDATE, target="some task")
    plan["filters"] = {
        "notion_page_id": page_id,
        "title": "Test Task",
        "current_values": {"status": "INBOX"},
        "proposed_changes": proposed_changes,
    }
    return plan


def _call(plan):
    handler = MagicMock(spec=WebhookHandler)
    return WebhookHandler._execute_work_update(handler, plan, _CTX)


# Shared patches applied to most tests.
# Targets: assistant_os.integrations.work_gateway.* — the patchable namespace
# declared in work_pipeline's module docstring (M0.8 architecture).
_PATCH_NOTION_OK = patch(
    "assistant_os.integrations.work_gateway.check_notion_available", return_value=True
)
_PATCH_OPTS_EMPTY = patch(
    "assistant_os.integrations.work_gateway.get_editable_field_options",
    return_value={"ok": True, "options": {}},
)
_PATCH_OPTS_STATUS = patch(
    "assistant_os.integrations.work_gateway.get_editable_field_options",
    return_value={"ok": True, "options": {"status": ["INBOX", "NEXT", "DONE", "SCHEDULED", "WAITING"]}},
)
_PATCH_UPDATE_OK = patch(
    "assistant_os.integrations.work_gateway.update_work_item",
    return_value={"ok": True, "changes_applied": [{"field": "status", "new_value": "NEXT"}]},
)
_PATCH_UPDATE_FAIL = patch(
    "assistant_os.integrations.work_gateway.update_work_item",
    return_value={"ok": False, "error": "Notion API timeout"},
)


# ---------------------------------------------------------------------------
# Validation: missing page_id
# ---------------------------------------------------------------------------

class TestWorkUpdateMissingPageId(unittest.TestCase):
    def test_missing_page_id_returns_validation_error(self):
        plan = _plan_with(None, [{"field": "status", "new_value": "NEXT"}])
        result = _call(plan)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["type"], "ValidationError")
        self.assertIn("notion_page_id", result["error"]["message"])

    def test_missing_page_id_does_not_call_notion(self):
        plan = _plan_with(None, [])
        with patch("assistant_os.integrations.work_gateway.check_notion_available") as mock_notion:
            _call(plan)
        mock_notion.assert_not_called()


# ---------------------------------------------------------------------------
# Validation: Notion unavailable
# ---------------------------------------------------------------------------

class TestWorkUpdateNotionUnavailable(unittest.TestCase):
    @patch("assistant_os.integrations.work_gateway.get_notion_status",
           return_value={"last_error": {"message": "Token not set"}})
    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=False)
    def test_notion_unavailable_returns_error(self, _mock_avail, _mock_status):
        plan = _plan_with("page-001", [{"field": "status", "new_value": "NEXT"}])
        result = _call(plan)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["type"], "NotionUnavailable")

    @patch("assistant_os.integrations.work_gateway.get_notion_status",
           return_value={"last_error": {"message": "Token not set"}})
    @patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=False)
    def test_notion_unavailable_error_message_from_status(self, _mock_avail, _mock_status):
        plan = _plan_with("page-001", [{"field": "status", "new_value": "NEXT"}])
        result = _call(plan)
        self.assertIn("Token not set", result["error"]["message"])


# ---------------------------------------------------------------------------
# Field validation
# ---------------------------------------------------------------------------

class TestWorkUpdateFieldValidation(unittest.TestCase):
    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    def test_disallowed_field_skipped_causes_no_valid_changes(self, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "title", "new_value": "New title"}])
        result = _call(plan)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["type"], "ValidationError")

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    @_PATCH_UPDATE_OK
    def test_allowed_field_status_accepted(self, _mock_update, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "status", "new_value": "NEXT"}])
        result = _call(plan)

        self.assertEqual(result["status"], "ok")

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    @_PATCH_UPDATE_OK
    def test_allowed_field_domain_accepted(self, _mock_update, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "domain", "new_value": "FIN"}])
        result = _call(plan)

        self.assertEqual(result["status"], "ok")

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    @_PATCH_UPDATE_OK
    def test_allowed_field_project_accepted(self, _mock_update, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "project", "new_value": "THCyE"}])
        result = _call(plan)

        self.assertEqual(result["status"], "ok")

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    def test_empty_field_in_change_is_skipped(self, _mock_opts, _mock_avail):
        """Change with empty field key is silently skipped."""
        plan = _plan_with("page-001", [{"field": "", "new_value": "NEXT"}])
        result = _call(plan)
        # No valid changes → ValidationError
        self.assertEqual(result["status"], "error")

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    def test_empty_value_in_change_is_skipped(self, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "status", "new_value": ""}])
        result = _call(plan)
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# Value validation against Notion options
# ---------------------------------------------------------------------------

class TestWorkUpdateValueValidation(unittest.TestCase):
    @_PATCH_NOTION_OK
    @_PATCH_OPTS_STATUS
    @_PATCH_UPDATE_OK
    def test_exact_case_match_passes(self, _mock_update, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "status", "new_value": "NEXT"}])
        result = _call(plan)
        self.assertEqual(result["status"], "ok")

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_STATUS
    @_PATCH_UPDATE_OK
    def test_case_insensitive_match_corrects_casing(self, _mock_update, _mock_opts, _mock_avail):
        """'next' (lowercase) should resolve to 'NEXT' (Notion canonical value)."""
        plan = _plan_with("page-001", [{"field": "status", "new_value": "next"}])
        result = _call(plan)
        self.assertEqual(result["status"], "ok")
        # Verify update_work_item was called with the corrected canonical value
        args, kwargs = _mock_update.call_args
        self.assertEqual(kwargs["changes"]["status"], "NEXT")

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_STATUS
    def test_invalid_value_no_fuzzy_match_causes_validation_error(self, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "status", "new_value": "INVALID_XYZ"}])
        result = _call(plan)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["type"], "ValidationError")
        self.assertIn("INVALID_XYZ", result["error"]["message"])

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_STATUS
    @_PATCH_UPDATE_OK
    def test_partial_fuzzy_match_accepted(self, _mock_update, _mock_opts, _mock_avail):
        """'SCHED' partially matches 'SCHEDULED' → accepted with corrected value."""
        plan = _plan_with("page-001", [{"field": "status", "new_value": "SCHED"}])
        result = _call(plan)
        self.assertEqual(result["status"], "ok")
        args, kwargs = _mock_update.call_args
        self.assertEqual(kwargs["changes"]["status"], "SCHEDULED")


# ---------------------------------------------------------------------------
# Successful update
# ---------------------------------------------------------------------------

class TestWorkUpdateSuccess(unittest.TestCase):
    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    @_PATCH_UPDATE_OK
    def test_success_response_shape(self, _mock_update, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "status", "new_value": "NEXT"}])
        result = _call(plan)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["agent"], "work")
        self.assertIsNone(result["error"])
        self.assertEqual(result["context_id"], _CTX)
        self.assertEqual(result["output"]["type"], "work_update_result")
        self.assertTrue(result["output"]["updated"])
        self.assertEqual(result["output"]["notion_page_id"], "page-001")

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    @_PATCH_UPDATE_OK
    def test_update_work_item_receives_correct_page_id(self, mock_update, _mock_opts, _mock_avail):
        plan = _plan_with("page-abc-123", [{"field": "status", "new_value": "DONE"}])
        _call(plan)
        args, kwargs = mock_update.call_args
        self.assertEqual(kwargs["page_id"], "page-abc-123")

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    @_PATCH_UPDATE_OK
    def test_update_work_item_receives_current_values(self, mock_update, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "status", "new_value": "DONE"}])
        plan["filters"]["current_values"] = {"status": "INBOX", "domain": "WORK"}
        _call(plan)
        args, kwargs = mock_update.call_args
        self.assertEqual(kwargs["current_values"], {"status": "INBOX", "domain": "WORK"})


# ---------------------------------------------------------------------------
# API failure from update_work_item
# ---------------------------------------------------------------------------

class TestWorkUpdateApiFailure(unittest.TestCase):
    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    @_PATCH_UPDATE_FAIL
    def test_notion_api_failure_returns_error(self, _mock_update, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "status", "new_value": "NEXT"}])
        result = _call(plan)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["type"], "NotionUpdateError")

    @_PATCH_NOTION_OK
    @_PATCH_OPTS_EMPTY
    @_PATCH_UPDATE_FAIL
    def test_notion_api_failure_message_propagated(self, _mock_update, _mock_opts, _mock_avail):
        plan = _plan_with("page-001", [{"field": "status", "new_value": "NEXT"}])
        result = _call(plan)
        self.assertIn("Notion API timeout", result["error"]["message"])


# ---------------------------------------------------------------------------
# Mixed valid / invalid changes in a single call
# ---------------------------------------------------------------------------

class TestWorkUpdateMixedChanges(unittest.TestCase):
    @_PATCH_NOTION_OK
    @_PATCH_OPTS_STATUS
    @_PATCH_UPDATE_OK
    def test_valid_change_applied_invalid_skipped(self, mock_update, _mock_opts, _mock_avail):
        """status=NEXT (valid) + title=Foo (disallowed field) → only status applied."""
        plan = _plan_with("page-001", [
            {"field": "status", "new_value": "NEXT"},
            {"field": "title", "new_value": "New title"},
        ])
        result = _call(plan)
        self.assertEqual(result["status"], "ok")
        args, kwargs = mock_update.call_args
        self.assertIn("status", kwargs["changes"])
        self.assertNotIn("title", kwargs["changes"])


if __name__ == "__main__":
    unittest.main()
