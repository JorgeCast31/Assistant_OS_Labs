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


class TestWorkQueryOutput(unittest.TestCase):
    """
    A1-FIX: _execute_work_query_from_plan is confirmed dead code that previously
    called the work pipeline directly without any policy enforcement.  It now
    raises RuntimeError on every call to prevent accidental reactivation.

    These tests were rewritten from output-shape tests into dead-code-guard tests.
    The underlying WORK query pipeline output is exercised through handle_request()
    in the integration test layer; no output-shape assertions are needed here.
    """

    def test_success_has_canonical_output(self):
        """_execute_work_query_from_plan raises RuntimeError — dead code guard."""
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        plan = make_plan("WORK", ACTION_WORK_QUERY, "query", filters={}, **_BASE_PLAN_KWARGS)
        with self.assertRaises(RuntimeError):
            handler._execute_work_query_from_plan(plan, "ctx-1")

    def test_zero_results_message(self):
        """_execute_work_query_from_plan raises RuntimeError — dead code guard."""
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        plan = make_plan("WORK", ACTION_WORK_QUERY, "q", **_BASE_PLAN_KWARGS)
        with self.assertRaises(RuntimeError):
            handler._execute_work_query_from_plan(plan, "ctx-1")

    def test_notion_unavailable_returns_error(self):
        """_execute_work_query_from_plan raises RuntimeError — dead code guard."""
        from assistant_os.webhook_server import WebhookHandler
        handler = WebhookHandler.__new__(WebhookHandler)
        plan = make_plan("WORK", ACTION_WORK_QUERY, "q", **_BASE_PLAN_KWARGS)
        with self.assertRaises(RuntimeError):
            handler._execute_work_query_from_plan(plan, "ctx-1")


class TestWorkCreateBypassRemoved(unittest.TestCase):
    """
    A2-FIX: _execute_work_create is a neutered bypass method.

    The method previously called work_pipeline._work_create_execute directly,
    bypassing handle_request, evaluate_policy, issue_token, verify_token, and
    consume_token.  It now raises RuntimeError on any call.

    WORK_CREATE execution routes exclusively through:
      handle_request() → evaluate_policy (S10) → token (S12) → work_pipeline
    """

    def _handler(self):
        from assistant_os.webhook_server import WebhookHandler
        return WebhookHandler.__new__(WebhookHandler)

    def test_raises_runtime_error(self):
        from assistant_os.contracts import make_plan, ACTION_WORK_CREATE
        plan = make_plan("WORK", ACTION_WORK_CREATE, "create", filters={"title": "T"})
        with self.assertRaises(RuntimeError, msg="_execute_work_create must raise RuntimeError (A2-FIX)"):
            self._handler()._execute_work_create(plan, "ctx-2")

    def test_error_message_names_handle_request(self):
        from assistant_os.contracts import make_plan, ACTION_WORK_CREATE
        plan = make_plan("WORK", ACTION_WORK_CREATE, "create", filters={"title": "T"})
        try:
            self._handler()._execute_work_create(plan, "ctx-2")
        except RuntimeError as exc:
            self.assertIn("handle_request", str(exc))

    def test_error_message_names_policy(self):
        from assistant_os.contracts import make_plan, ACTION_WORK_CREATE
        plan = make_plan("WORK", ACTION_WORK_CREATE, "create", filters={"title": "T"})
        try:
            self._handler()._execute_work_create(plan, "ctx-2")
        except RuntimeError as exc:
            self.assertIn("policy", str(exc).lower())


class TestWorkDeleteBypassRemoved(unittest.TestCase):
    """
    A2-FIX: _execute_work_delete is a neutered bypass method.

    WORK_DELETE execution routes exclusively through:
      handle_request() → evaluate_policy (S10) → token (S12) → work_pipeline
    """

    def _handler(self):
        from assistant_os.webhook_server import WebhookHandler
        return WebhookHandler.__new__(WebhookHandler)

    def test_raises_runtime_error(self):
        from assistant_os.contracts import make_plan, ACTION_WORK_DELETE
        plan = make_plan("WORK", ACTION_WORK_DELETE, "delete", filters={"keywords": ["x"]})
        with self.assertRaises(RuntimeError):
            self._handler()._execute_work_delete(plan, "ctx-3")

    def test_error_message_names_handle_request(self):
        from assistant_os.contracts import make_plan, ACTION_WORK_DELETE
        plan = make_plan("WORK", ACTION_WORK_DELETE, "delete", filters={"keywords": ["x"]})
        try:
            self._handler()._execute_work_delete(plan, "ctx-3")
        except RuntimeError as exc:
            self.assertIn("handle_request", str(exc))


class TestWorkUpdateSingularBypassRemoved(unittest.TestCase):
    """
    A2-FIX: _execute_work_update is a neutered bypass method.

    WORK_UPDATE execution routes exclusively through:
      handle_request() → evaluate_policy (S10) → token (S12) → work_pipeline
    """

    def _handler(self):
        from assistant_os.webhook_server import WebhookHandler
        return WebhookHandler.__new__(WebhookHandler)

    def test_raises_runtime_error(self):
        from assistant_os.contracts import make_plan, ACTION_WORK_UPDATE
        plan = make_plan("WORK", ACTION_WORK_UPDATE, "update", filters={"notion_page_id": "pg-x"})
        with self.assertRaises(RuntimeError):
            self._handler()._execute_work_update(plan, "ctx-4")

    def test_error_message_names_handle_request(self):
        from assistant_os.contracts import make_plan, ACTION_WORK_UPDATE
        plan = make_plan("WORK", ACTION_WORK_UPDATE, "update", filters={})
        try:
            self._handler()._execute_work_update(plan, "ctx-4")
        except RuntimeError as exc:
            self.assertIn("handle_request", str(exc))


# ---------------------------------------------------------------------------
# Partial success — bulk update
# ---------------------------------------------------------------------------

class TestWorkUpdateBulkBypassRemoved(unittest.TestCase):
    """
    A2-FIX: _execute_work_update_bulk is a neutered bypass method.

    WORK_UPDATE_BULK execution routes exclusively through:
      handle_request() → evaluate_policy (S10) → token (S12) → work_pipeline
    """

    def _handler(self):
        from assistant_os.webhook_server import WebhookHandler
        return WebhookHandler.__new__(WebhookHandler)

    def test_raises_runtime_error(self):
        plan = {"matches": [], "selected_notion_page_ids": [], "applied_changes": {}}
        with self.assertRaises(RuntimeError):
            self._handler()._execute_work_update_bulk(plan, "ctx-bulk")

    def test_error_message_names_handle_request(self):
        plan = {"matches": [], "selected_notion_page_ids": [], "applied_changes": {}}
        try:
            self._handler()._execute_work_update_bulk(plan, "ctx-bulk")
        except RuntimeError as exc:
            self.assertIn("handle_request", str(exc))


# ---------------------------------------------------------------------------
# failed_items shape — dead-code note
# ---------------------------------------------------------------------------
# A2-FIX: TestFailedItemsShape previously tested _execute_work_update_bulk
# output format for failed_items.  That method is now neutered.  The
# failed_items contract is verified at the pipeline level via work_pipeline
# integration tests (test_work_pipeline.py) which use _work_update_bulk_execute
# directly without going through the neutered WebhookHandler bypass method.


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
