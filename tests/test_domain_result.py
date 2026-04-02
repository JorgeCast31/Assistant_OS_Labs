"""
Tests for DomainResult v1 — contracts and WORK handler output semantics.

Covers:
- DomainResult TypedDict factory invariants
- make_domain_result() enforced rules (ok/error consistency, data normalization)
- RESULT_TYPE_* constants present and distinct
- _wrap_work_result() transport adapter (backward compat + canonical fields)
- Each WORK handler produces DomainResult-aligned output:
    _execute_work_query_from_plan
    _execute_work_create
    _execute_work_delete
    _execute_work_update
    _execute_work_update_bulk
    _execute_work_update_preview (all branches)
- Partial success: bulk update ok=True with failures in data
- Failure: structured error, data always a dict
- Backward compat: output["type"] still present for summary.py
"""
import unittest
from unittest.mock import patch, MagicMock

from assistant_os.contracts import (
    make_domain_result,
    DomainResult,
    make_plan,
    ErrorDetail,
    RESULT_TYPE_WORK_QUERY,
    RESULT_TYPE_WORK_CREATE,
    RESULT_TYPE_WORK_UPDATE,
    RESULT_TYPE_WORK_UPDATE_PREVIEW,
    RESULT_TYPE_WORK_UPDATE_BULK,
    RESULT_TYPE_WORK_DELETE,
    ACTION_WORK_QUERY,
    ACTION_WORK_CREATE,
    ACTION_WORK_UPDATE,
    ACTION_WORK_UPDATE_BULK,
    ACTION_WORK_DELETE,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
)
from assistant_os.webhook_server import _wrap_work_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_work_plan(action=ACTION_WORK_CREATE, **kwargs):
    return make_plan("WORK", action, "test target", **kwargs)


def _assert_domain_result_shape(tc: unittest.TestCase, dr: dict):
    """Assert the canonical DomainResult v1 wrapper fields are all present."""
    tc.assertIn("ok", dr, "missing 'ok'")
    tc.assertIn("result_type", dr, "missing 'result_type'")
    tc.assertIn("domain", dr, "missing 'domain'")
    tc.assertIn("message", dr, "missing 'message'")
    tc.assertIn("data", dr, "missing 'data'")
    tc.assertIn("error", dr, "missing 'error'")

    tc.assertIsInstance(dr["ok"], bool)
    tc.assertIsInstance(dr["result_type"], str)
    tc.assertTrue(dr["result_type"], "result_type must be non-empty")
    tc.assertIsInstance(dr["domain"], str)
    tc.assertIsInstance(dr["message"], str)
    tc.assertTrue(dr["message"], "message must be non-empty")
    tc.assertIsInstance(dr["data"], dict)

    if dr["ok"]:
        tc.assertIsNone(dr["error"], "ok=True must have error=None")
    else:
        tc.assertIsNotNone(dr["error"], "ok=False must have a non-None error")
        tc.assertIsInstance(dr["error"], dict)
        tc.assertIn("type", dr["error"])
        tc.assertIn("message", dr["error"])


def _assert_response_shape(tc: unittest.TestCase, resp: dict):
    """Assert top-level transport Response fields are present."""
    for key in ("context_id", "agent", "status", "output", "error", "ts"):
        tc.assertIn(key, resp, f"Response missing '{key}'")
    tc.assertEqual(resp["agent"], "work")
    tc.assertIn(resp["status"], ("ok", "error"))


def _assert_output_canonical(tc: unittest.TestCase, output: dict):
    """Assert canonical DomainResult fields are present inside output."""
    for key in ("ok", "result_type", "domain", "message", "data"):
        tc.assertIn(key, output, f"output missing canonical field '{key}'")
    tc.assertIn("type", output, "output missing backward-compat 'type' field")
    tc.assertIsInstance(output["data"], dict)
    tc.assertIsInstance(output["result_type"], str)
    tc.assertTrue(output["result_type"])
    tc.assertIsInstance(output["message"], str)
    tc.assertTrue(output["message"])


# ---------------------------------------------------------------------------
# make_domain_result() factory invariants
# ---------------------------------------------------------------------------

class TestMakeDomainResult(unittest.TestCase):

    def test_ok_true_has_no_error(self):
        dr = make_domain_result(ok=True, result_type="work_query", domain="WORK",
                                message="ok", data={})
        self.assertTrue(dr["ok"])
        self.assertIsNone(dr["error"])

    def test_ok_true_forces_error_to_none(self):
        """Even if caller provides error, ok=True must force error=None."""
        dr = make_domain_result(
            ok=True, result_type="work_query", domain="WORK",
            message="ok", data={},
            error={"type": "SomeError", "message": "ignored"},
        )
        self.assertIsNone(dr["error"])

    def test_ok_false_requires_error(self):
        with self.assertRaises(ValueError):
            make_domain_result(ok=False, result_type="work_query", domain="WORK",
                               message="fail", data={}, error=None)

    def test_ok_false_requires_error_dict(self):
        with self.assertRaises(ValueError):
            make_domain_result(ok=False, result_type="work_query", domain="WORK",
                               message="fail", data={})  # error not provided

    def test_ok_false_with_valid_error(self):
        dr = make_domain_result(
            ok=False, result_type="work_query", domain="WORK",
            message="fail", data={},
            error={"type": "NotionUnavailable", "message": "down"},
        )
        self.assertFalse(dr["ok"])
        self.assertIsNotNone(dr["error"])
        self.assertEqual(dr["error"]["type"], "NotionUnavailable")

    def test_data_none_becomes_empty_dict(self):
        dr = make_domain_result(ok=True, result_type="work_query", domain="WORK",
                                message="ok", data=None)
        self.assertEqual(dr["data"], {})

    def test_data_default_is_empty_dict(self):
        dr = make_domain_result(ok=True, result_type="work_query", domain="WORK",
                                message="ok")
        self.assertEqual(dr["data"], {})

    def test_all_required_fields_present(self):
        dr = make_domain_result(ok=True, result_type="work_query", domain="WORK",
                                message="ok", data={"x": 1})
        _assert_domain_result_shape(self, dr)

    def test_optional_trace_id(self):
        dr = make_domain_result(ok=True, result_type="work_query", domain="WORK",
                                message="ok", trace_id="abc123")
        self.assertEqual(dr["trace_id"], "abc123")

    def test_optional_plan_id(self):
        dr = make_domain_result(ok=True, result_type="work_query", domain="WORK",
                                message="ok", plan_id="plan-uuid-1")
        self.assertEqual(dr["plan_id"], "plan-uuid-1")

    def test_optional_warnings(self):
        dr = make_domain_result(ok=True, result_type="work_query", domain="WORK",
                                message="ok", warnings=["warning1"])
        self.assertEqual(dr["warnings"], ["warning1"])

    def test_no_optional_fields_by_default(self):
        dr = make_domain_result(ok=True, result_type="work_query", domain="WORK",
                                message="ok")
        self.assertNotIn("trace_id", dr)
        self.assertNotIn("plan_id", dr)
        self.assertNotIn("warnings", dr)


# ---------------------------------------------------------------------------
# RESULT_TYPE_* constants
# ---------------------------------------------------------------------------

class TestResultTypeConstants(unittest.TestCase):

    def test_all_constants_are_strings(self):
        for const in (
            RESULT_TYPE_WORK_QUERY,
            RESULT_TYPE_WORK_CREATE,
            RESULT_TYPE_WORK_UPDATE,
            RESULT_TYPE_WORK_UPDATE_PREVIEW,
            RESULT_TYPE_WORK_UPDATE_BULK,
            RESULT_TYPE_WORK_DELETE,
        ):
            self.assertIsInstance(const, str)
            self.assertTrue(const)

    def test_all_constants_are_distinct(self):
        constants = [
            RESULT_TYPE_WORK_QUERY,
            RESULT_TYPE_WORK_CREATE,
            RESULT_TYPE_WORK_UPDATE,
            RESULT_TYPE_WORK_UPDATE_PREVIEW,
            RESULT_TYPE_WORK_UPDATE_BULK,
            RESULT_TYPE_WORK_DELETE,
        ]
        self.assertEqual(len(constants), len(set(constants)))

    def test_expected_values(self):
        self.assertEqual(RESULT_TYPE_WORK_QUERY,          "work_query")
        self.assertEqual(RESULT_TYPE_WORK_CREATE,         "work_create")
        self.assertEqual(RESULT_TYPE_WORK_UPDATE,         "work_update")
        self.assertEqual(RESULT_TYPE_WORK_UPDATE_PREVIEW, "work_update_preview")
        self.assertEqual(RESULT_TYPE_WORK_UPDATE_BULK,    "work_update_bulk")
        self.assertEqual(RESULT_TYPE_WORK_DELETE,         "work_delete")


# ---------------------------------------------------------------------------
# _wrap_work_result() transport adapter
# ---------------------------------------------------------------------------

class TestWrapWorkResult(unittest.TestCase):

    def _make_success_dr(self, result_type=RESULT_TYPE_WORK_QUERY, data=None):
        return make_domain_result(
            ok=True,
            result_type=result_type,
            domain="WORK",
            message="all good",
            data=data or {"type": result_type, "items": []},
        )

    def _make_failure_dr(self, result_type=RESULT_TYPE_WORK_QUERY):
        return make_domain_result(
            ok=False,
            result_type=result_type,
            domain="WORK",
            message="something failed",
            data={},
            error={"type": "TestError", "message": "test failure"},
        )

    def test_success_response_shape(self):
        dr = self._make_success_dr()
        resp = _wrap_work_result(dr, "ctx-123")
        _assert_response_shape(self, resp)
        self.assertEqual(resp["status"], "ok")
        self.assertIsNone(resp["error"])

    def test_failure_response_shape(self):
        dr = self._make_failure_dr()
        resp = _wrap_work_result(dr, "ctx-456")
        _assert_response_shape(self, resp)
        self.assertEqual(resp["status"], "error")
        self.assertIsNotNone(resp["error"])
        self.assertEqual(resp["error"]["type"], "TestError")

    def test_output_canonical_fields_present(self):
        dr = self._make_success_dr()
        resp = _wrap_work_result(dr, "ctx-123")
        _assert_output_canonical(self, resp["output"])

    def test_output_data_field_is_the_data_dict(self):
        dr = self._make_success_dr(data={"type": "work_query", "items": [1, 2], "total": 2})
        resp = _wrap_work_result(dr, "ctx-123")
        self.assertEqual(resp["output"]["data"]["items"], [1, 2])
        self.assertEqual(resp["output"]["data"]["total"], 2)

    def test_data_fields_promoted_to_top_level(self):
        """Backward compat: data fields appear at output top level for summary.py."""
        dr = self._make_success_dr(data={"type": "work_query", "items": [{"id": 1}], "total": 1})
        resp = _wrap_work_result(dr, "ctx-123")
        output = resp["output"]
        # Promoted to top level
        self.assertIn("items", output)
        self.assertEqual(output["items"], [{"id": 1}])
        self.assertIn("total", output)
        self.assertEqual(output["total"], 1)

    def test_type_field_present_at_top_level(self):
        """summary.py reads output.get('type') — must still be present."""
        dr = self._make_success_dr(data={"type": "work_query"})
        resp = _wrap_work_result(dr, "ctx-123")
        self.assertIn("type", resp["output"])
        self.assertEqual(resp["output"]["type"], "work_query")

    def test_type_falls_back_to_result_type_when_not_in_data(self):
        dr = self._make_success_dr(data={"items": []})  # no "type" in data
        resp = _wrap_work_result(dr, "ctx-123")
        self.assertEqual(resp["output"]["type"], RESULT_TYPE_WORK_QUERY)

    def test_context_id_correct(self):
        dr = self._make_success_dr()
        resp = _wrap_work_result(dr, "ctx-XYZ")
        self.assertEqual(resp["context_id"], "ctx-XYZ")

    def test_warnings_propagated(self):
        dr = make_domain_result(
            ok=True, result_type=RESULT_TYPE_WORK_QUERY, domain="WORK",
            message="ok", data={}, warnings=["warn1", "warn2"],
        )
        resp = _wrap_work_result(dr, "ctx-123")
        self.assertIn("warnings", resp["output"])
        self.assertEqual(resp["output"]["warnings"], ["warn1", "warn2"])

    def test_no_warnings_key_when_empty(self):
        dr = self._make_success_dr()
        resp = _wrap_work_result(dr, "ctx-123")
        self.assertNotIn("warnings", resp["output"])


# ---------------------------------------------------------------------------
# WORK handler output semantics — mocked Notion
# ---------------------------------------------------------------------------

MOCK_PLAN_ID = "plan-id-abc123"
MOCK_TRACE_ID = "trace-ab"

_BASE_PLAN_KWARGS = dict(
    requires_confirmation=False,
    risk_level=RISK_LOW,
    plan_id=MOCK_PLAN_ID,
    trace_id=MOCK_TRACE_ID,
)


@patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
class TestWorkQueryOutput(unittest.TestCase):

    @patch("assistant_os.webhook_server.query_work_db")
    @patch("assistant_os.webhook_server.format_work_query_response", return_value="formatted text")
    def test_success_has_canonical_output(self, _fmt, mock_query, _notion):
        mock_query.return_value = {"items": [{"title": "T1"}], "total": 1}
        plan = make_plan("WORK", ACTION_WORK_QUERY, "query", filters={}, **_BASE_PLAN_KWARGS)

        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_query_from_plan(plan, "ctx-1")

        _assert_response_shape(self, resp)
        self.assertEqual(resp["status"], "ok")
        output = resp["output"]
        _assert_output_canonical(self, output)
        self.assertEqual(output["result_type"], RESULT_TYPE_WORK_QUERY)
        self.assertEqual(output["domain"], "WORK")
        self.assertTrue(output["message"])
        self.assertEqual(output["type"], "work_query")   # backward compat
        self.assertIn("items", output["data"])
        self.assertIn("total", output["data"])
        self.assertIn("formatted", output["data"])

    @patch("assistant_os.webhook_server.query_work_db")
    @patch("assistant_os.webhook_server.format_work_query_response", return_value="")
    def test_zero_results_message(self, _fmt, mock_query, _notion):
        mock_query.return_value = {"items": [], "total": 0}
        plan = make_plan("WORK", ACTION_WORK_QUERY, "q", **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_query_from_plan(plan, "ctx-1")
        self.assertIn("No se encontraron", resp["output"]["message"])

    @patch("assistant_os.integrations.work_gateway.get_notion_status",
           return_value={"last_error": {"message": "down"}})
    def test_notion_unavailable_returns_error(self, _status, _notion):
        _notion.return_value = False
        plan = make_plan("WORK", ACTION_WORK_QUERY, "q", **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_query_from_plan(plan, "ctx-1")
        self.assertEqual(resp["status"], "error")
        self.assertFalse(resp["output"]["ok"])
        self.assertEqual(resp["output"]["result_type"], RESULT_TYPE_WORK_QUERY)
        self.assertIsNotNone(resp["error"])
        self.assertIsInstance(resp["output"]["data"], dict)


@patch("assistant_os.webhook_server.check_notion_available", return_value=True)
class TestWorkCreateOutput(unittest.TestCase):

    @patch("assistant_os.webhook_server.create_work_item")
    def test_success_has_canonical_output(self, mock_create, _notion):
        mock_create.return_value = {"ok": True, "page_id": "pg1", "url": "http://x", "title": "T1"}
        plan = make_plan("WORK", ACTION_WORK_CREATE, "create",
                         filters={"title": "T1"}, **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_create(plan, "ctx-2")

        _assert_response_shape(self, resp)
        self.assertEqual(resp["status"], "ok")
        output = resp["output"]
        _assert_output_canonical(self, output)
        self.assertEqual(output["result_type"], RESULT_TYPE_WORK_CREATE)
        self.assertEqual(output["type"], "work_create")   # backward compat
        self.assertIn("page_id", output["data"])
        self.assertIn("T1", output["message"])

    def test_missing_title_is_validation_error(self, _notion):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "create",
                         filters={}, **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_create(plan, "ctx-2")

        self.assertEqual(resp["status"], "error")
        self.assertFalse(resp["output"]["ok"])
        self.assertEqual(resp["output"]["result_type"], RESULT_TYPE_WORK_CREATE)
        self.assertEqual(resp["error"]["type"], "ValidationError")
        self.assertIsInstance(resp["output"]["data"], dict)

    @patch("assistant_os.webhook_server.create_work_item")
    def test_notion_failure_returns_error(self, mock_create, _notion):
        mock_create.return_value = {"ok": False, "error": "API timeout"}
        plan = make_plan("WORK", ACTION_WORK_CREATE, "create",
                         filters={"title": "T1"}, **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_create(plan, "ctx-2")

        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error"]["type"], "WorkCreateError")
        self.assertIsInstance(resp["output"]["data"], dict)


@patch("assistant_os.webhook_server.check_notion_available", return_value=True)
class TestWorkDeleteOutput(unittest.TestCase):

    @patch("assistant_os.integrations.notion.archive_pages", return_value=2)
    @patch("assistant_os.webhook_server.query_work_db")
    def test_success_has_canonical_output(self, mock_query, _archive, _notion):
        mock_query.return_value = {
            "items": [
                {"notion_page_id": "p1", "title": "task alpha"},
                {"notion_page_id": "p2", "title": "task alpha 2"},
            ],
            "total": 2,
        }
        plan = make_plan("WORK", ACTION_WORK_DELETE, "delete",
                         filters={"keywords": ["alpha"], "delete_all": False},
                         **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_delete(plan, "ctx-3")

        _assert_response_shape(self, resp)
        self.assertEqual(resp["status"], "ok")
        output = resp["output"]
        _assert_output_canonical(self, output)
        self.assertEqual(output["result_type"], RESULT_TYPE_WORK_DELETE)
        self.assertEqual(output["type"], "work_delete")
        self.assertIn("deleted_count", output["data"])
        self.assertIn("total_matched", output["data"])

    @patch("assistant_os.webhook_server.query_work_db")
    def test_no_matches_is_ok_not_error(self, mock_query, _notion):
        mock_query.return_value = {"items": [], "total": 0}
        plan = make_plan("WORK", ACTION_WORK_DELETE, "delete",
                         filters={"keywords": ["notfound"], "delete_all": False},
                         **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_delete(plan, "ctx-3")

        self.assertEqual(resp["status"], "ok")
        self.assertTrue(resp["output"]["ok"])
        self.assertEqual(resp["output"]["data"]["deleted_count"], 0)

    def test_no_criteria_is_validation_error(self, _notion):
        plan = make_plan("WORK", ACTION_WORK_DELETE, "delete",
                         filters={"keywords": [], "delete_all": False},
                         **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_delete(plan, "ctx-3")

        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error"]["type"], "ValidationError")
        self.assertIsInstance(resp["output"]["data"], dict)


@patch("assistant_os.integrations.work_gateway.check_notion_available", return_value=True)
@patch("assistant_os.integrations.work_gateway.get_editable_field_options",
       return_value={"ok": True, "options": {"domain": ["Tech"], "project": ["P1"], "status": ["NEXT"]}})
class TestWorkUpdateSingularOutput(unittest.TestCase):

    @patch("assistant_os.integrations.work_gateway.update_work_item")
    def test_success_has_canonical_output(self, mock_update, _opts, _notion):
        mock_update.return_value = {"ok": True, "changes_applied": [{"field": "status", "new_value": "NEXT"}]}
        plan = make_plan("WORK", ACTION_WORK_UPDATE, "update",
                         filters={
                             "notion_page_id": "pg-abc",
                             "title": "My Task",
                             "current_values": {"status": "INBOX"},
                             "proposed_changes": [{"field": "status", "new_value": "NEXT", "confidence": 1.0}],
                         },
                         **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_update(plan, "ctx-4")

        _assert_response_shape(self, resp)
        self.assertEqual(resp["status"], "ok")
        output = resp["output"]
        _assert_output_canonical(self, output)
        self.assertEqual(output["result_type"], RESULT_TYPE_WORK_UPDATE)
        self.assertEqual(output["type"], "work_update_result")   # backward compat
        self.assertIn("notion_page_id", output["data"])
        self.assertIn("changes_applied", output["data"])

    def test_missing_page_id_is_validation_error(self, _opts, _notion):
        plan = make_plan("WORK", ACTION_WORK_UPDATE, "update",
                         filters={"proposed_changes": [{"field": "status", "new_value": "NEXT"}]},
                         **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_update(plan, "ctx-4")

        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error"]["type"], "ValidationError")
        self.assertFalse(resp["output"]["ok"])
        self.assertIsInstance(resp["output"]["data"], dict)

    @patch("assistant_os.integrations.work_gateway.update_work_item")
    def test_no_valid_changes_is_error(self, mock_update, _opts, _notion):
        # proposed_changes has invalid field → no changes_dict built
        plan = make_plan("WORK", ACTION_WORK_UPDATE, "update",
                         filters={
                             "notion_page_id": "pg-abc",
                             "proposed_changes": [{"field": "status", "new_value": "INVALID_VALUE"}],
                         },
                         **_BASE_PLAN_KWARGS)
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_update(plan, "ctx-4")

        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["error"]["type"], "ValidationError")
        self.assertIsInstance(resp["output"]["data"], dict)


# ---------------------------------------------------------------------------
# Partial success — bulk update
# ---------------------------------------------------------------------------

class TestWorkUpdateBulkPartialSuccess(unittest.TestCase):
    """
    Bulk update with mixed results must be ok=True (partial success).
    Failures go to data.failed_items, not top-level error.
    """

    @patch("assistant_os.integrations.work_gateway.get_editable_field_options")
    @patch("assistant_os.integrations.work_gateway.update_work_item")
    def test_partial_success_is_ok_true(self, mock_update, mock_opts):
        mock_opts.return_value = {"ok": True, "options": {"status": ["NEXT", "DONE"]}}
        # page1 succeeds, page2 fails
        mock_update.side_effect = [
            {"ok": True, "changes_applied": [{"field": "status", "new_value": "NEXT"}]},
            {"ok": False, "error": "Notion timeout"},
        ]
        plan = {
            "matches": [
                {"notion_page_id": "p1", "title": "T1"},
                {"notion_page_id": "p2", "title": "T2"},
            ],
            "selected_notion_page_ids": ["p1", "p2"],
            "applied_changes": {"status": "NEXT"},
            "editable_fields": ["status"],
        }
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_update_bulk(plan, "ctx-bulk")

        self.assertEqual(resp["status"], "ok")
        self.assertTrue(resp["output"]["ok"])
        self.assertIsNone(resp["error"])
        data = resp["output"]["data"]
        self.assertEqual(data["updated_count"], 1)
        self.assertEqual(len(data["failed_items"]), 1)
        self.assertEqual(data["failed_items"][0]["notion_page_id"], "p2")

    @patch("assistant_os.integrations.work_gateway.get_editable_field_options")
    @patch("assistant_os.integrations.work_gateway.update_work_item")
    def test_all_succeed_is_ok_true(self, mock_update, mock_opts):
        mock_opts.return_value = {"ok": True, "options": {"status": ["NEXT"]}}
        mock_update.return_value = {"ok": True, "changes_applied": []}
        plan = {
            "matches": [{"notion_page_id": "p1", "title": "T1"}],
            "selected_notion_page_ids": ["p1"],
            "applied_changes": {"status": "NEXT"},
            "editable_fields": ["status"],
        }
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_update_bulk(plan, "ctx-bulk")

        self.assertEqual(resp["status"], "ok")
        self.assertIsNone(resp["error"])
        self.assertEqual(resp["output"]["data"]["updated_count"], 1)
        self.assertEqual(resp["output"]["data"]["failed_items"], [])

    @patch("assistant_os.integrations.work_gateway.get_editable_field_options")
    def test_validation_failure_in_data_not_top_level_error(self, mock_opts):
        """Invalid field value goes to failed_items, not response.error."""
        mock_opts.return_value = {"ok": True, "options": {"status": ["NEXT", "DONE"]}}
        plan = {
            "matches": [{"notion_page_id": "p1", "title": "T1"}],
            "selected_notion_page_ids": ["p1"],
            "applied_changes": {"status": "INVALID_STATUS"},
            "editable_fields": ["status"],
        }
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_update_bulk(plan, "ctx-bulk")

        self.assertEqual(resp["status"], "ok")
        self.assertIsNone(resp["error"])
        data = resp["output"]["data"]
        self.assertEqual(data["updated_count"], 0)
        self.assertEqual(len(data["failed_items"]), 1)
        failed = data["failed_items"][0]
        self.assertIn("notion_page_id", failed)
        self.assertIn("field", failed)
        self.assertIn("value", failed)
        self.assertIn("reason", failed)
        self.assertIn("error", failed)

    @patch("assistant_os.integrations.work_gateway.get_editable_field_options")
    def test_bulk_result_type_and_canonical_fields(self, mock_opts):
        mock_opts.return_value = {"ok": True, "options": {}}
        plan = {
            "matches": [],
            "selected_notion_page_ids": [],
            "applied_changes": {},
            "editable_fields": ["status"],
        }
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_update_bulk(plan, "ctx-bulk")

        _assert_output_canonical(self, resp["output"])
        self.assertEqual(resp["output"]["result_type"], RESULT_TYPE_WORK_UPDATE_BULK)
        self.assertEqual(resp["output"]["type"], "work_update_bulk_result")   # backward compat


# ---------------------------------------------------------------------------
# failed_items canonical 5-key shape
# ---------------------------------------------------------------------------

class TestFailedItemsShape(unittest.TestCase):
    """Each failed_item must have exactly the 5-key canonical shape."""

    _REQUIRED_KEYS = {"notion_page_id", "field", "value", "reason", "error"}

    def _check_failed_item(self, item: dict):
        for key in self._REQUIRED_KEYS:
            self.assertIn(key, item, f"failed_item missing key '{key}'")

    @patch("assistant_os.integrations.work_gateway.get_editable_field_options")
    def test_validation_failure_item_has_5_keys(self, mock_opts):
        mock_opts.return_value = {"ok": True, "options": {"status": ["NEXT"]}}
        plan = {
            "matches": [{"notion_page_id": "p1"}],
            "selected_notion_page_ids": ["p1"],
            "applied_changes": {"status": "BAD"},
            "editable_fields": ["status"],
        }
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_update_bulk(plan, "ctx")
        failed = resp["output"]["data"]["failed_items"]
        self.assertEqual(len(failed), 1)
        self._check_failed_item(failed[0])

    @patch("assistant_os.integrations.work_gateway.get_editable_field_options")
    @patch("assistant_os.integrations.work_gateway.update_work_item")
    def test_api_failure_item_has_5_keys(self, mock_update, mock_opts):
        mock_opts.return_value = {"ok": True, "options": {"status": ["NEXT"]}}
        mock_update.return_value = {"ok": False, "error": "API error"}
        plan = {
            "matches": [{"notion_page_id": "p1"}],
            "selected_notion_page_ids": ["p1"],
            "applied_changes": {"status": "NEXT"},
            "editable_fields": ["status"],
        }
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        resp = handler._execute_work_update_bulk(plan, "ctx")
        failed = resp["output"]["data"]["failed_items"]
        self.assertEqual(len(failed), 1)
        self._check_failed_item(failed[0])
        # API failure: field/value/reason are None, error is the message
        self.assertIsNone(failed[0]["field"])
        self.assertIsNone(failed[0]["value"])
        self.assertIsNone(failed[0]["reason"])
        self.assertEqual(failed[0]["error"], "API error")


# ---------------------------------------------------------------------------
# Backward compatibility: existing transport shape preserved
# ---------------------------------------------------------------------------

class TestTransportCompatibility(unittest.TestCase):
    """Verify existing tests' assumptions about Response shape still hold."""

    def _make_resp(self, result_type=RESULT_TYPE_WORK_QUERY, ok=True, data=None, error=None):
        if ok:
            dr = make_domain_result(ok=True, result_type=result_type, domain="WORK",
                                    message="ok", data=data or {})
        else:
            dr = make_domain_result(ok=False, result_type=result_type, domain="WORK",
                                    message="fail", data={},
                                    error=error or {"type": "E", "message": "err"})
        return _wrap_work_result(dr, "ctx-test")

    def test_context_id_at_top_level(self):
        resp = self._make_resp()
        self.assertEqual(resp["context_id"], "ctx-test")

    def test_agent_is_work(self):
        resp = self._make_resp()
        self.assertEqual(resp["agent"], "work")

    def test_status_ok_when_ok(self):
        resp = self._make_resp(ok=True)
        self.assertEqual(resp["status"], "ok")

    def test_status_error_when_not_ok(self):
        resp = self._make_resp(ok=False)
        self.assertEqual(resp["status"], "error")

    def test_ts_present(self):
        resp = self._make_resp()
        self.assertIn("ts", resp)
        self.assertTrue(resp["ts"])

    def test_top_level_error_is_none_on_success(self):
        resp = self._make_resp(ok=True)
        self.assertIsNone(resp["error"])

    def test_top_level_error_is_error_detail_on_failure(self):
        resp = self._make_resp(ok=False, error={"type": "TestErr", "message": "bad"})
        self.assertIsNotNone(resp["error"])
        self.assertEqual(resp["error"]["type"], "TestErr")

    def test_output_is_dict(self):
        resp = self._make_resp()
        self.assertIsInstance(resp["output"], dict)

    def test_output_type_field_still_accessible(self):
        """summary.py reads output.get('type') — must not break."""
        resp = self._make_resp(data={"type": "work_query", "items": []})
        self.assertIn("type", resp["output"])


if __name__ == "__main__":
    unittest.main()
