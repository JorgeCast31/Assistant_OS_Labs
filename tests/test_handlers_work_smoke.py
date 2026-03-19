"""
Smoke tests for WORK handler delegation.

Verifies that the one-liner delegation methods in WebhookHandler correctly
forward to the handler functions in assistant_os.handlers.work, and that
test-critical arguments (trash_db_id) are passed at call time so existing
@patch('assistant_os.webhook_server.NOTION_WORK_TRASH_DB_ID', ...) tests
keep working.
"""
import unittest
from unittest.mock import MagicMock, patch

from assistant_os.webhook_server import WebhookHandler

_REMOTE = "127.0.0.1"


class TestWorkQueryDelegation(unittest.TestCase):
    @patch("assistant_os.handlers.work.handle_work_query")
    def test_delegates_to_handle_work_query(self, mock_fn):
        handler = MagicMock(spec=WebhookHandler)
        WebhookHandler._handle_work_query(handler, _REMOTE)
        mock_fn.assert_called_once_with(handler, _REMOTE)

    @patch("assistant_os.handlers.work.handle_work_query")
    def test_no_extra_args_passed(self, mock_fn):
        """Delegation must not inject extra positional arguments."""
        handler = MagicMock(spec=WebhookHandler)
        WebhookHandler._handle_work_query(handler, _REMOTE)
        args, kwargs = mock_fn.call_args
        self.assertEqual(args, (handler, _REMOTE))
        self.assertEqual(kwargs, {})


class TestWorkCreateDelegation(unittest.TestCase):
    @patch("assistant_os.handlers.work.handle_work_create")
    def test_delegates_to_handle_work_create(self, mock_fn):
        handler = MagicMock(spec=WebhookHandler)
        WebhookHandler._handle_work_create(handler, _REMOTE)
        mock_fn.assert_called_once_with(handler, _REMOTE)


class TestWorkDeleteDelegation(unittest.TestCase):
    @patch("assistant_os.handlers.work.handle_work_delete")
    @patch("assistant_os.webhook_server.NOTION_WORK_TRASH_DB_ID", "test-trash-db-id")
    def test_delegates_with_patched_trash_db_id(self, mock_fn):
        """
        When the module-level NOTION_WORK_TRASH_DB_ID is patched, the patched
        value must reach handle_work_delete as trash_db_id kwarg.
        """
        handler = MagicMock(spec=WebhookHandler)
        WebhookHandler._handle_work_delete(handler, _REMOTE)
        mock_fn.assert_called_once_with(handler, _REMOTE, trash_db_id="test-trash-db-id")

    @patch("assistant_os.handlers.work.handle_work_delete")
    @patch("assistant_os.webhook_server.NOTION_WORK_TRASH_DB_ID", None)
    def test_delegates_with_none_when_trash_not_configured(self, mock_fn):
        handler = MagicMock(spec=WebhookHandler)
        WebhookHandler._handle_work_delete(handler, _REMOTE)
        mock_fn.assert_called_once_with(handler, _REMOTE, trash_db_id=None)

    @patch("assistant_os.handlers.work.handle_work_delete")
    @patch("assistant_os.webhook_server.NOTION_WORK_TRASH_DB_ID", "trash-id-at-call-time")
    def test_trash_db_id_evaluated_at_call_time(self, mock_fn):
        """
        Verify trash_db_id is read from the module namespace at invocation time,
        not at import time — critical for test patching to work.
        """
        handler = MagicMock(spec=WebhookHandler)
        WebhookHandler._handle_work_delete(handler, _REMOTE)
        _, kwargs = mock_fn.call_args
        self.assertEqual(kwargs["trash_db_id"], "trash-id-at-call-time")


class TestHandlersWorkImports(unittest.TestCase):
    """Verify the handler module imports cleanly and exports the expected symbols."""

    def test_handle_work_query_importable(self):
        from assistant_os.handlers.work import handle_work_query
        self.assertTrue(callable(handle_work_query))

    def test_handle_work_create_importable(self):
        from assistant_os.handlers.work import handle_work_create
        self.assertTrue(callable(handle_work_create))

    def test_handle_work_delete_importable(self):
        from assistant_os.handlers.work import handle_work_delete
        self.assertTrue(callable(handle_work_delete))

    def test_execute_work_delete_importable(self):
        from assistant_os.handlers.work import _execute_work_delete
        self.assertTrue(callable(_execute_work_delete))


if __name__ == "__main__":
    unittest.main()
