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

        # A1-FIX: _execute_confirmed_plan now routes through handle_request().
        # The orchestrator's _execute_confirmed_plan returns "NoPipeline" when no
        # domain pipeline is registered for the action, replacing the old
        # webhook-level "UnsupportedAction" error that was produced without policy.
        self.assertEqual(result["status"], "error")
        self.assertIsNotNone(result["error"])
        self.assertIsNotNone(result["error"]["type"])
        # The error type must be a non-empty string indicating pipeline absence.
        self.assertIn(result["error"]["type"], ("NoPipeline", "UnsupportedAction"))

    @patch("assistant_os.webhook_server._log_webhook_event")
    def test_unsupported_action_message_names_the_action(self, _mock_log):
        plan = make_plan(domain="WORK", action=ACTION_COMMAND, target="test", risk_level=RISK_MEDIUM)
        ctx_id = "ctx-unsupported-msg"
        store_pending_plan(ctx_id, plan, "COMMAND")

        handler = MagicMock()
        result = WebhookHandler._execute_confirmed_plan(handler, ctx_id, _REMOTE)

        # A1-FIX: _execute_confirmed_plan routes through handle_request().
        # The orchestrator returns a "NoPipeline" error whose message names the
        # domain (UNKNOWN) rather than the raw action string.  The invariant that
        # an error is returned for unsupported actions is preserved; the exact
        # message format is now owned by the orchestrator layer.
        self.assertEqual(result["status"], "error")
        self.assertIsNotNone(result["error"])
        # Error message must be a non-empty string describing the failure.
        self.assertGreater(len(result["error"]["message"]), 0)


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
    @patch("assistant_os.police.enforcement.check")
    def test_bulk_action_constant_calls_execute_work_update_bulk(self, mock_police, mock_bulk_exec, _mock_log):
        """ACTION_WORK_UPDATE_BULK routes through domain registry → work_pipeline._work_update_bulk_execute."""
        mock_police.return_value.permitted = True

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
    @patch("assistant_os.police.enforcement.check")
    def test_work_update_action_calls_singular_executor(self, mock_police, mock_preview_exec, _mock_log):
        """ACTION_WORK_UPDATE (no notion_page_id) routes through domain registry → _work_update_preview_execute."""
        mock_police.return_value.permitted = True

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

class TestExecuteWorkUpdateBulkBypassRemoved(unittest.TestCase):
    """
    A2-FIX: _execute_work_update_bulk is a neutered bypass method.

    Previously this class tested the direct output format of
    WebhookHandler._execute_work_update_bulk (which called
    work_pipeline._work_update_bulk_execute without policy/token gating).
    That bypass is removed in A2-FIX.

    WORK_UPDATE_BULK routes through:
      handle_request() → evaluate_policy (S10) → token (S12) → work_pipeline
    """

    def test_raises_runtime_error(self):
        handler = MagicMock(spec=WebhookHandler)
        plan = {"matches": [], "selected_notion_page_ids": [], "applied_changes": {}}
        with self.assertRaises(RuntimeError, msg="_execute_work_update_bulk must raise (A2-FIX)"):
            WebhookHandler._execute_work_update_bulk(handler, plan, "ctx-bulk")

    def test_error_message_names_handle_request(self):
        handler = MagicMock(spec=WebhookHandler)
        plan = {"matches": [], "selected_notion_page_ids": [], "applied_changes": {}}
        try:
            WebhookHandler._execute_work_update_bulk(handler, plan, "ctx-bulk")
        except RuntimeError as exc:
            self.assertIn("handle_request", str(exc))


# ---------------------------------------------------------------------------
# failed_items canonical shape (Fix 1)
# ---------------------------------------------------------------------------

_CANONICAL_FAILED_KEYS = {"notion_page_id", "field", "value", "reason", "error"}


class TestFailedItemsCanonicalShapeBypassRemoved(unittest.TestCase):
    """
    A2-FIX: _execute_work_update_bulk is a neutered bypass method.

    This class previously tested the failed_items canonical shape
    (5-key structure: notion_page_id, field, value, reason, error) via the
    bypass path. That path is removed in A2-FIX.

    The failed_items contract is now verified through the pipeline integration
    tests (test_work_pipeline.py) which call _work_update_bulk_execute directly.
    """

    def test_raises_runtime_error_on_direct_call(self):
        handler = MagicMock(spec=WebhookHandler)
        plan = {
            "matches": [{"notion_page_id": "p1"}],
            "selected_notion_page_ids": ["p1"],
            "applied_changes": {"status": "NEXT"},
        }
        with self.assertRaises(RuntimeError):
            WebhookHandler._execute_work_update_bulk(handler, plan, "ctx")



if __name__ == "__main__":
    unittest.main()
