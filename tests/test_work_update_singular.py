"""
A2-FIX: Dead-code-guard tests for WebhookHandler._execute_work_update.

Previously this file contained ~300 lines of unit tests that exercised
WebhookHandler._execute_work_update directly — a bypass method that called
work_pipeline._work_update_execute without any policy, token issuance, or
token verification.

That bypass is removed in A2-FIX.  The method now raises RuntimeError on
any call.  WORK_UPDATE execution routes exclusively through:

  handle_request() → evaluate_policy (S10) → issue_token (S12) →
  verify_token → consume_token → work_pipeline._work_update_execute()

The singular WORK_UPDATE business logic (field validation, fuzzy matching,
Notion API calls) is still covered by work_pipeline integration tests.
"""

import unittest
from unittest.mock import MagicMock

from assistant_os.webhook_server import WebhookHandler
from assistant_os.contracts import make_plan, ACTION_WORK_UPDATE


_CTX = "ctx-a2fix-singular"


def _plan_with(page_id=None, proposed_changes=None):
    plan = make_plan(domain="WORK", action=ACTION_WORK_UPDATE, target="some task")
    plan["filters"] = {
        "notion_page_id": page_id or "",
        "title": "Test Task",
        "proposed_changes": proposed_changes or [],
    }
    return plan


class TestWorkUpdateSingularBypassRemoved(unittest.TestCase):
    """
    _execute_work_update is a neutered unsafe bypass method (A2-FIX).

    Every call must raise RuntimeError immediately — no execution occurs.
    """

    def _call(self, plan=None):
        handler = MagicMock(spec=WebhookHandler)
        return WebhookHandler._execute_work_update(handler, plan or _plan_with("pg-x"), _CTX)

    def test_raises_runtime_error_on_any_call(self):
        with self.assertRaises(RuntimeError):
            self._call()

    def test_raises_before_executing_any_notion_code(self):
        """RuntimeError is raised immediately — no Notion I/O should occur."""
        import unittest.mock as _mock
        with _mock.patch(
            "assistant_os.integrations.work_gateway.update_work_item"
        ) as mock_update:
            with self.assertRaises(RuntimeError):
                self._call(_plan_with("pg-x", [{"field": "status", "new_value": "NEXT"}]))
            mock_update.assert_not_called()

    def test_error_message_names_handle_request(self):
        try:
            self._call()
        except RuntimeError as exc:
            self.assertIn("handle_request", str(exc), (
                "RuntimeError must name the correct replacement path"
            ))

    def test_error_message_names_policy(self):
        try:
            self._call()
        except RuntimeError as exc:
            self.assertIn("policy", str(exc).lower())

    def test_raises_for_any_plan_shape(self):
        """RuntimeError is unconditional — not conditional on plan content."""
        cases = [
            _plan_with(),                                # missing page_id
            _plan_with("pg-x"),                          # no proposed_changes
            _plan_with("pg-x", [{"field": "status"}]),  # partial change
            {},                                          # empty plan
        ]
        for plan in cases:
            with self.subTest(plan=plan):
                with self.assertRaises(RuntimeError):
                    handler = MagicMock(spec=WebhookHandler)
                    WebhookHandler._execute_work_update(handler, plan, _CTX)


if __name__ == "__main__":
    unittest.main()
