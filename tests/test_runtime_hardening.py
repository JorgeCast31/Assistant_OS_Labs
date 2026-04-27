"""Regression tests for Sprint 3 — Runtime Hardening.

Verifies:
1. WebhookHTTPServer uses ThreadingMixIn with daemon_threads=True
2. Notion integration calls include timeout= on all external requests
"""
import inspect
import socketserver
import unittest
from unittest.mock import MagicMock, patch


class TestWebhookServerThreading(unittest.TestCase):
    def test_threading_mixin_in_mro(self):
        from assistant_os.webhook_server import WebhookHTTPServer
        self.assertIn(
            socketserver.ThreadingMixIn,
            WebhookHTTPServer.__mro__,
            "WebhookHTTPServer must inherit from ThreadingMixIn",
        )

    def test_daemon_threads_true(self):
        from assistant_os.webhook_server import WebhookHTTPServer
        self.assertTrue(
            WebhookHTTPServer.daemon_threads,
            "daemon_threads must be True so threads die with the main process",
        )


class TestNotionTimeouts(unittest.TestCase):
    """Verify that all external Notion requests include a timeout parameter."""

    def _make_mock_response(self, status=200, json_data=None):
        m = MagicMock()
        m.status_code = status
        m.json.return_value = json_data or {}
        return m

    def test_query_work_items_by_keywords_has_timeout(self):
        from assistant_os.integrations import notion as notion_mod
        captured = {}

        def fake_post(url, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return self._make_mock_response(200, {"results": []})

        with patch.object(notion_mod.requests, "post", side_effect=fake_post):
            try:
                notion_mod.query_work_items_by_keywords("db-id", ["keyword"], limit=1)
            except Exception:
                pass
        self.assertIsNotNone(captured.get("timeout"), "query_work_items_by_keywords must pass timeout= to requests.post")

    def test_archive_pages_has_timeout(self):
        from assistant_os.integrations import notion as notion_mod
        captured = {}

        def fake_patch(url, **kwargs):
            captured.setdefault("timeouts", []).append(kwargs.get("timeout"))
            return self._make_mock_response(200)

        with patch.object(notion_mod.requests, "patch", side_effect=fake_patch):
            try:
                notion_mod.archive_pages(["page-abc"])
            except Exception:
                pass
        timeouts = captured.get("timeouts", [])
        self.assertTrue(
            timeouts and all(t is not None for t in timeouts),
            f"archive_pages must pass timeout= to requests.patch; got timeouts={timeouts}",
        )

    def test_move_pages_to_db_has_timeout(self):
        from assistant_os.integrations import notion as notion_mod
        get_captured: list = []
        post_captured: list = []
        patch_captured: list = []

        def fake_get(url, **kwargs):
            get_captured.append(kwargs.get("timeout"))
            return self._make_mock_response(200, {"properties": {"Name": {}}})

        def fake_post(url, **kwargs):
            post_captured.append(kwargs.get("timeout"))
            return self._make_mock_response(201, {"id": "new-page"})

        def fake_patch(url, **kwargs):
            patch_captured.append(kwargs.get("timeout"))
            return self._make_mock_response(200)

        with patch.object(notion_mod.requests, "get", side_effect=fake_get), \
             patch.object(notion_mod.requests, "post", side_effect=fake_post), \
             patch.object(notion_mod.requests, "patch", side_effect=fake_patch):
            try:
                notion_mod.move_pages_to_db(["page-xyz"], "target-db")
            except Exception:
                pass

        self.assertTrue(
            get_captured and all(t is not None for t in get_captured),
            f"move_pages_to_db GET must have timeout; got {get_captured}",
        )
        self.assertTrue(
            post_captured and all(t is not None for t in post_captured),
            f"move_pages_to_db POST must have timeout; got {post_captured}",
        )
        self.assertTrue(
            patch_captured and all(t is not None for t in patch_captured),
            f"move_pages_to_db PATCH must have timeout; got {patch_captured}",
        )


if __name__ == "__main__":
    unittest.main()
