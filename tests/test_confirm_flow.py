"""
Tests for the confirmation execution flow (_execute_confirmed_plan).

Covers:
- context_id not found → ContextNotFound error with correct shape
- ContextNotFound logs confirm_not_found event (structured, filterable)
- Unsupported action → UnsupportedAction error
- Plan is removed from store after execution (success and error paths)
- ACTION_WORK_UPDATE_BULK routes through domain registry → work_pipeline → _work_update_bulk_execute
- ACTION_WORK_UPDATE (no notion_page_id) routes through domain registry → work_pipeline → _work_update_preview_execute
- _execute_work_update_bulk: updates each selected page
- _execute_work_update_bulk: skips page_ids not in matches
- _execute_work_update_bulk: marks invalid field values as failed
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import assistant_os.context_store as cs
from assistant_os.context_store import store_pending_plan, get_pending_plan, clear_store
from assistant_os.contracts import (
    make_plan,
    ACTION_WORK_CREATE, ACTION_WORK_UPDATE, ACTION_WORK_UPDATE_BULK, ACTION_COMMAND,
    RISK_MEDIUM,
)
from assistant_os.webhook_server import WebhookHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REMOTE = "127.0.0.1"


def _ok_response(ctx_id: str, agent: str = "work") -> dict:
    return {
        "context_id": ctx_id, "agent": agent,
        "status": "ok", "output": {}, "error": None,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Base: clean context store before/after each test
# ---------------------------------------------------------------------------

class ConfirmFlowTestBase(unittest.TestCase):
    def setUp(self):
        clear_store()

    def tearDown(self):
        clear_store()


# ---------------------------------------------------------------------------
# ContextNotFound cases
# ---------------------------------------------------------------------------

class TestConfirmContextNotFound(ConfirmFlowTestBase):
    @patch("assistant_os.webhook_server._log_webhook_event")
    def test_missing_context_returns_context_not_found(self, _mock_log):
        handler = MagicMock()
        result = WebhookHandler._execute_confirmed_plan(handler, "ctx-missing-001", _REMOTE)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["type"], "ContextNotFound")

    @patch("assistant_os.webhook_server._log_webhook_event")
    def test_missing_context_error_message_contains_context_id(self, _mock_log):
        ctx_id = "ctx-msg-check-001"
        handler = MagicMock()
        result = WebhookHandler._execute_confirmed_plan(handler, ctx_id, _REMOTE)

        self.assertIn(ctx_id, result["error"]["message"])

    @patch("assistant_os.webhook_server._log_webhook_event")
    def test_missing_context_logs_confirm_not_found_event(self, mock_log):
        ctx_id = "ctx-log-001"
        handler = MagicMock()
        WebhookHandler._execute_confirmed_plan(handler, ctx_id, _REMOTE)

        mock_log.assert_called_once()
        kwargs = mock_log.call_args[1]
        self.assertEqual(kwargs.get("event_type"), "confirm_not_found")
        self.assertFalse(kwargs.get("ok", True))
        self.assertEqual(kwargs.get("context_id"), ctx_id)

    @patch("assistant_os.webhook_server._log_webhook_event")
    def test_missing_context_agent_is_kernel(self, _mock_log):
        handler = MagicMock()
        result = WebhookHandler._execute_confirmed_plan(handler, "ctx-kernel-001", _REMOTE)

        self.assertEqual(result["agent"], "kernel")


# ---------------------------------------------------------------------------
# Unsupported action
# ---------------------------------------------------------------------------

class TestConfirmUnsupportedAction(ConfirmFlowTestBase):
    @patch("assistant_os.webhook_server._log_webhook_event")
    def test_unsupported_action_returns_error(self, _mock_log):
        plan = make_plan(domain="WORK", action=ACTION_COMMAND, target="test", risk_level=RISK_MEDIUM)
        ctx_id = "ctx-unsupported-001"
        store_pending_plan(ctx_id, plan, "COMMAND")

        handler = MagicMock()
        result = WebhookHandler._execute_confirmed_plan(handler, ctx_id, _REMOTE)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["type"], "UnsupportedAction")

    @patch("assistant_os.webhook_server._log_webhook_event")
    def test_unsupported_action_message_names_the_action(self, _mock_log):
        plan = make_plan(domain="WORK", action=ACTION_COMMAND, target="test", risk_level=RISK_MEDIUM)
        ctx_id = "ctx-unsupported-msg"
        store_pending_plan(ctx_id, plan, "COMMAND")

        handler = MagicMock()
        result = WebhookHandler._execute_confirmed_plan(handler, ctx_id, _REMOTE)

        self.assertIn(ACTION_COMMAND, result["error"]["message"])


# ---------------------------------------------------------------------------
# Plan removal after execution
# ---------------------------------------------------------------------------

class TestConfirmPlanRemoval(ConfirmFlowTestBase):
    @patch("assistant_os.webhook_server._log_webhook_event")
    @patch("assistant_os.pipelines.work_pipeline._work_create_execute")
    def test_plan_removed_after_successful_execution(self, mock_create, _mock_log):
        from assistant_os.contracts import make_domain_result, RESULT_TYPE_WORK_CREATE
        plan = make_plan(domain="WORK", action=ACTION_WORK_CREATE, target="test")
        ctx_id = "ctx-remove-ok"
        store_pending_plan(ctx_id, plan, "WORK_CREATE")

        mock_create.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_WORK_CREATE, domain="WORK",
            message="Tarea creada.", data={},
        )

        handler = MagicMock()
        WebhookHandler._execute_confirmed_plan(handler, ctx_id, _REMOTE)

        self.assertIsNone(get_pending_plan(ctx_id))

    @patch("assistant_os.webhook_server._log_webhook_event")
    def test_plan_removed_after_unsupported_action_error(self, _mock_log):
        """Plan is removed even when execution fails (unsupported action)."""
        plan = make_plan(domain="WORK", action=ACTION_COMMAND, target="test")
        ctx_id = "ctx-remove-err"
        store_pending_plan(ctx_id, plan, "COMMAND")

        handler = MagicMock()
        WebhookHandler._execute_confirmed_plan(handler, ctx_id, _REMOTE)

        self.assertIsNone(get_pending_plan(ctx_id))


# ---------------------------------------------------------------------------
# ACTION_WORK_UPDATE routing (bulk vs. singular)
# ---------------------------------------------------------------------------

class TestConfirmWorkUpdateRouting(ConfirmFlowTestBase):
    @patch("assistant_os.webhook_server._log_webhook_event")
    @patch("assistant_os.pipelines.work_pipeline._work_update_bulk_execute")
    def test_bulk_action_constant_calls_execute_work_update_bulk(self, mock_bulk_exec, _mock_log):
        """ACTION_WORK_UPDATE_BULK routes through domain registry → work_pipeline._work_update_bulk_execute."""
        from assistant_os.contracts import make_domain_result, RESULT_TYPE_WORK_UPDATE_BULK
        plan = make_plan(domain="WORK", action=ACTION_WORK_UPDATE_BULK, target="Multiple tasks")
        plan["matches"] = []
        plan["selected_notion_page_ids"] = []
        plan["applied_changes"] = {}

        ctx_id = "ctx-bulk-route-001"
        store_pending_plan(ctx_id, plan, "WORK_UPDATE_BULK")

        mock_bulk_exec.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_UPDATE_BULK,
            domain="WORK",
            message="0 actualizados.",
            data={"updated_count": 0, "updated_items": [], "failed_items": [], "skipped_items": []},
        )

        handler = MagicMock()
        result = WebhookHandler._execute_confirmed_plan(handler, ctx_id, _REMOTE)

        mock_bulk_exec.assert_called_once()
        self.assertEqual(result["status"], "ok")

    @patch("assistant_os.webhook_server._log_webhook_event")
    @patch("assistant_os.pipelines.work_pipeline._work_update_preview_execute")
    def test_work_update_action_calls_singular_executor(self, mock_preview_exec, _mock_log):
        """ACTION_WORK_UPDATE (no notion_page_id) routes through domain registry → _work_update_preview_execute."""
        from assistant_os.contracts import make_domain_result, RESULT_TYPE_WORK_UPDATE_PREVIEW
        plan = make_plan(domain="WORK", action=ACTION_WORK_UPDATE, target="Single task")
        # no notion_page_id in filters → preview path

        ctx_id = "ctx-singular-route-001"
        store_pending_plan(ctx_id, plan, "WORK_UPDATE")

        mock_preview_exec.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message="Preview generado.",
            data={},
        )

        handler = MagicMock()
        result = WebhookHandler._execute_confirmed_plan(handler, ctx_id, _REMOTE)

        mock_preview_exec.assert_called_once()
        self.assertEqual(result["status"], "ok")


# ---------------------------------------------------------------------------
# _execute_work_update_bulk logic
# ---------------------------------------------------------------------------

class TestExecuteWorkUpdateBulk(unittest.TestCase):
    """Direct tests of the WebhookHandler._execute_work_update_bulk method."""

    def _call(self, plan: dict, ctx_id: str = "ctx-bulk-test"):
        handler = MagicMock(spec=WebhookHandler)
        return WebhookHandler._execute_work_update_bulk(handler, plan, ctx_id)

    @patch("assistant_os.integrations.work_gateway.update_work_item", return_value={"ok": True})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {"status": ["NEXT", "INBOX", "DONE"]}})
    def test_updates_each_selected_page(self, _mock_opts, _mock_update):
        plan = {
            "matches": [
                {"notion_page_id": "page-1", "title": "Task 1"},
                {"notion_page_id": "page-2", "title": "Task 2"},
            ],
            "selected_notion_page_ids": ["page-1", "page-2"],
            "applied_changes": {"status": "NEXT"},
            "editable_fields": ["status"],
        }

        result = self._call(plan)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["output"]["updated_count"], 2)
        self.assertEqual(result["output"]["failed_items"], [])
        self.assertEqual(result["output"]["skipped_items"], [])

    @patch("assistant_os.integrations.work_gateway.update_work_item", return_value={"ok": True})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {}})
    def test_skips_page_ids_not_in_matches(self, _mock_opts, _mock_update):
        plan = {
            "matches": [{"notion_page_id": "page-1", "title": "Task 1"}],
            "selected_notion_page_ids": ["page-1", "page-ghost"],
            "applied_changes": {"status": "NEXT"},
            "editable_fields": ["status"],
        }

        result = self._call(plan)

        self.assertEqual(result["output"]["updated_count"], 1)
        self.assertIn("page-ghost", result["output"]["skipped_items"])

    @patch("assistant_os.integrations.work_gateway.update_work_item", return_value={"ok": True})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {"status": ["NEXT", "INBOX"]}})
    def test_marks_invalid_field_value_as_failed(self, _mock_opts, _mock_update):
        plan = {
            "matches": [{"notion_page_id": "page-1", "title": "Task 1"}],
            "selected_notion_page_ids": ["page-1"],
            "applied_changes": {"status": "INVALID_STATUS"},
            "editable_fields": ["status"],
        }

        result = self._call(plan)

        # update_work_item should not be called for invalid value
        _mock_update.assert_not_called()
        self.assertEqual(result["output"]["updated_count"], 0)
        self.assertEqual(len(result["output"]["failed_items"]), 1)
        self.assertEqual(result["output"]["failed_items"][0]["reason"], "Valor no válido")

    @patch("assistant_os.integrations.work_gateway.update_work_item",
           return_value={"ok": False, "error": "Notion API error"})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {}})
    def test_records_notion_api_failure(self, _mock_opts, _mock_update):
        plan = {
            "matches": [{"notion_page_id": "page-fail", "title": "Failing Task"}],
            "selected_notion_page_ids": ["page-fail"],
            "applied_changes": {"status": "NEXT"},
            "editable_fields": ["status"],
        }

        result = self._call(plan)

        self.assertEqual(result["output"]["updated_count"], 0)
        self.assertEqual(len(result["output"]["failed_items"]), 1)
        self.assertIn("error", result["output"]["failed_items"][0])

    @patch("assistant_os.integrations.work_gateway.update_work_item", return_value={"ok": True})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {}})
    def test_empty_selection_returns_zero_counts(self, _mock_opts, _mock_update):
        plan = {
            "matches": [{"notion_page_id": "page-1", "title": "Task 1"}],
            "selected_notion_page_ids": [],
            "applied_changes": {"status": "NEXT"},
            "editable_fields": ["status"],
        }

        result = self._call(plan)

        self.assertEqual(result["output"]["updated_count"], 0)
        self.assertEqual(result["status"], "ok")  # empty selection is not an error
        _mock_update.assert_not_called()

    @patch("assistant_os.integrations.work_gateway.update_work_item", return_value={"ok": True})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {}})
    def test_result_contains_summary_message(self, _mock_opts, mock_update):
        plan = {
            "matches": [{"notion_page_id": "p1", "title": "T1"}],
            "selected_notion_page_ids": ["p1"],
            "applied_changes": {"status": "NEXT"},
            "editable_fields": ["status"],
        }

        result = self._call(plan, "ctx-msg-001")

        msg = result["output"]["message"]
        self.assertIn("1 actualizados", msg)
        self.assertIn("ctx-msg-001", result["context_id"])


# ---------------------------------------------------------------------------
# failed_items canonical shape (Fix 1)
# ---------------------------------------------------------------------------

_CANONICAL_FAILED_KEYS = {"notion_page_id", "field", "value", "reason", "error"}


class TestFailedItemsCanonicalShape(unittest.TestCase):
    """
    Every entry in failed_items must have the same five keys regardless of
    whether the failure originated from field validation or a Notion API error.
    """

    def _call(self, plan, ctx_id="ctx-shape-test"):
        handler = MagicMock(spec=WebhookHandler)
        return WebhookHandler._execute_work_update_bulk(handler, plan, ctx_id)

    # --- validation failure shape ---

    @patch("assistant_os.integrations.work_gateway.update_work_item", return_value={"ok": True})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {"status": ["NEXT", "INBOX"]}})
    def test_validation_failure_has_all_five_keys(self, _mock_opts, _mock_update):
        plan = {
            "matches": [{"notion_page_id": "page-v", "title": "T"}],
            "selected_notion_page_ids": ["page-v"],
            "applied_changes": {"status": "INVALID"},
            "editable_fields": ["status"],
        }
        result = self._call(plan)
        item = result["output"]["failed_items"][0]
        self.assertEqual(set(item.keys()), _CANONICAL_FAILED_KEYS)

    @patch("assistant_os.integrations.work_gateway.update_work_item", return_value={"ok": True})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {"status": ["NEXT", "INBOX"]}})
    def test_validation_failure_error_is_none(self, _mock_opts, _mock_update):
        plan = {
            "matches": [{"notion_page_id": "page-v", "title": "T"}],
            "selected_notion_page_ids": ["page-v"],
            "applied_changes": {"status": "INVALID"},
            "editable_fields": ["status"],
        }
        result = self._call(plan)
        item = result["output"]["failed_items"][0]
        self.assertIsNone(item["error"])
        self.assertEqual(item["reason"], "Valor no válido")
        self.assertEqual(item["field"], "status")
        self.assertEqual(item["value"], "INVALID")

    # --- API failure shape ---

    @patch("assistant_os.integrations.work_gateway.update_work_item",
           return_value={"ok": False, "error": "Timeout"})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {}})
    def test_api_failure_has_all_five_keys(self, _mock_opts, _mock_update):
        plan = {
            "matches": [{"notion_page_id": "page-a", "title": "T"}],
            "selected_notion_page_ids": ["page-a"],
            "applied_changes": {"status": "NEXT"},
            "editable_fields": ["status"],
        }
        result = self._call(plan)
        item = result["output"]["failed_items"][0]
        self.assertEqual(set(item.keys()), _CANONICAL_FAILED_KEYS)

    @patch("assistant_os.integrations.work_gateway.update_work_item",
           return_value={"ok": False, "error": "Timeout"})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {}})
    def test_api_failure_field_value_reason_are_none(self, _mock_opts, _mock_update):
        plan = {
            "matches": [{"notion_page_id": "page-a", "title": "T"}],
            "selected_notion_page_ids": ["page-a"],
            "applied_changes": {"status": "NEXT"},
            "editable_fields": ["status"],
        }
        result = self._call(plan)
        item = result["output"]["failed_items"][0]
        self.assertIsNone(item["field"])
        self.assertIsNone(item["value"])
        self.assertIsNone(item["reason"])
        self.assertEqual(item["error"], "Timeout")

    # --- shape is uniform when both failure types occur in the same call ---

    @patch("assistant_os.integrations.work_gateway.update_work_item",
           return_value={"ok": False, "error": "API down"})
    @patch("assistant_os.integrations.work_gateway.get_editable_field_options",
           return_value={"ok": True, "options": {"status": ["NEXT"]}})
    def test_mixed_failures_all_have_canonical_shape(self, _mock_opts, _mock_update):
        """
        page-bad → invalid value (validation failure)
        page-api → valid value but API call fails (API failure)
        Both must have identical key sets.
        """
        plan = {
            "matches": [
                {"notion_page_id": "page-bad", "title": "Bad value"},
                {"notion_page_id": "page-api", "title": "API fails"},
            ],
            "selected_notion_page_ids": ["page-bad", "page-api"],
            "applied_changes": {"status": "INVALID"},
            "editable_fields": ["status"],
        }
        result = self._call(plan)
        for item in result["output"]["failed_items"]:
            self.assertEqual(set(item.keys()), _CANONICAL_FAILED_KEYS,
                             f"Item with page_id={item['notion_page_id']} missing keys")


if __name__ == "__main__":
    unittest.main()
