"""
Sprint 1 — WORK/FIN Canonical Entry Baseline Tests

Verifies that the three WORK handlers and the FIN expense handler now route
through the canonical pipeline instead of calling Notion / parse_expense
directly.

Acceptance criteria
-------------------
1. /work/query  routes through work_pipeline.execute()
2. /work/create routes through work_pipeline.execute()
3. /work/delete routes through work_pipeline.execute()
4. /fin/expense  routes through fin_pipeline.execute()
5. WORK responses contain execution_id (non-None UUID string)
6. FIN expense response contains execution_id
7. WORK responses contain result_type
8. DomainResult invariants are preserved (ok / error / data shapes)
9. Error responses still include execution_id (None is acceptable for pre-plan errors)
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from assistant_os.contracts import (
    make_domain_result,
    RESULT_TYPE_WORK_QUERY,
    RESULT_TYPE_WORK_CREATE,
    RESULT_TYPE_WORK_DELETE,
    RESULT_TYPE_FIN_EXPENSE,
)
from assistant_os.webhook_server import WebhookHandler

_REMOTE = "127.0.0.1:9999"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(body: bytes = b"{}") -> WebhookHandler:
    """Build a minimal fake WebhookHandler with pre-wired helpers."""
    handler = MagicMock(spec=WebhookHandler)
    handler._check_auth.return_value = None  # auth passes
    handler._read_body.return_value = (body, None)
    return handler


def _captured_response(handler: MagicMock) -> dict:
    """Return the dict passed to _send_json_response."""
    assert handler._send_json_response.called, "_send_json_response was never called"
    _, response_dict = handler._send_json_response.call_args[0]
    return response_dict


# ---------------------------------------------------------------------------
# 1. /work/query → work_pipeline.execute()
# ---------------------------------------------------------------------------

class TestWorkQueryCanonicalPath(unittest.TestCase):

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_routes_through_pipeline(self, mock_execute):
        """handle_work_query must call work_pipeline.execute, not query_work_db."""
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_QUERY,
            domain="WORK",
            message="2 tareas encontradas.",
            data={"type": "work_query", "items": [{"title": "T1"}, {"title": "T2"}], "total": 2, "formatted": "T1\nT2", "filters": {}},
        )
        body = json.dumps({"filters": {"status": ["NEXT"]}}).encode()
        handler = _make_handler(body)

        from assistant_os.handlers.work import handle_work_query
        handle_work_query(handler, _REMOTE)

        mock_execute.assert_called_once()
        plan_arg, context_id_arg = mock_execute.call_args[0]
        self.assertEqual(plan_arg.get("action"), "WORK_QUERY")
        self.assertIsNotNone(plan_arg.get("plan_id"))

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_response_contains_execution_id(self, mock_execute):
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_QUERY,
            domain="WORK",
            message="OK",
            data={"items": [], "total": 0, "formatted": "", "filters": {}},
            plan_id="plan-wq-1",
        )
        handler = _make_handler(b"{}")
        from assistant_os.handlers.work import handle_work_query
        handle_work_query(handler, _REMOTE)

        resp = _captured_response(handler)
        self.assertIn("execution_id", resp)
        self.assertIsNotNone(resp["execution_id"])

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_response_contains_result_type(self, mock_execute):
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_QUERY,
            domain="WORK",
            message="OK",
            data={"items": [], "total": 0, "formatted": "", "filters": {}},
        )
        handler = _make_handler(b"{}")
        from assistant_os.handlers.work import handle_work_query
        handle_work_query(handler, _REMOTE)

        resp = _captured_response(handler)
        self.assertEqual(resp.get("result_type"), RESULT_TYPE_WORK_QUERY)

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_backward_compat_fields_present(self, mock_execute):
        """Legacy fields (ok, items, total, formatted) must still be in response."""
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_QUERY,
            domain="WORK",
            message="OK",
            data={"items": [{"title": "X"}], "total": 1, "formatted": "X", "filters": {}},
        )
        handler = _make_handler(b"{}")
        from assistant_os.handlers.work import handle_work_query
        handle_work_query(handler, _REMOTE)

        resp = _captured_response(handler)
        self.assertIn("ok", resp)
        self.assertIn("items", resp)
        self.assertIn("total", resp)
        self.assertIn("formatted", resp)

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_pipeline_error_still_returns_execution_id(self, mock_execute):
        mock_execute.return_value = make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_QUERY,
            domain="WORK",
            message="Notion no disponible.",
            data={},
            error={"type": "NotionUnavailable", "message": "Notion not configured"},
            plan_id="plan-wq-err",
        )
        handler = _make_handler(b"{}")
        from assistant_os.handlers.work import handle_work_query
        handle_work_query(handler, _REMOTE)

        resp = _captured_response(handler)
        self.assertFalse(resp["ok"])
        self.assertIn("execution_id", resp)
        self.assertIsNotNone(resp["execution_id"])


# ---------------------------------------------------------------------------
# 2. /work/create → work_pipeline.execute()
# ---------------------------------------------------------------------------

class TestWorkCreateCanonicalPath(unittest.TestCase):

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_routes_through_pipeline(self, mock_execute):
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_CREATE,
            domain="WORK",
            message="Tarea creada: Mi tarea",
            data={"type": "work_create", "page_id": "abc123", "url": "https://notion.so/abc123", "title": "Mi tarea"},
        )
        body = json.dumps({"title": "Mi tarea"}).encode()
        handler = _make_handler(body)

        from assistant_os.handlers.work import handle_work_create
        handle_work_create(handler, _REMOTE)

        mock_execute.assert_called_once()
        plan_arg, _ = mock_execute.call_args[0]
        self.assertEqual(plan_arg.get("action"), "WORK_CREATE")
        self.assertEqual(plan_arg.get("filters", {}).get("title"), "Mi tarea")

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_response_contains_execution_id(self, mock_execute):
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_CREATE,
            domain="WORK",
            message="Tarea creada.",
            data={"page_id": "x", "url": "", "title": "T"},
            plan_id="plan-wc-1",
        )
        handler = _make_handler(json.dumps({"title": "T"}).encode())
        from assistant_os.handlers.work import handle_work_create
        handle_work_create(handler, _REMOTE)

        resp = _captured_response(handler)
        self.assertIn("execution_id", resp)
        self.assertIsNotNone(resp["execution_id"])

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_backward_compat_fields_present(self, mock_execute):
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_CREATE,
            domain="WORK",
            message="OK",
            data={"page_id": "p1", "url": "http://x", "title": "T"},
        )
        handler = _make_handler(json.dumps({"title": "T"}).encode())
        from assistant_os.handlers.work import handle_work_create
        handle_work_create(handler, _REMOTE)

        resp = _captured_response(handler)
        for field in ("ok", "page_id", "url", "title"):
            self.assertIn(field, resp)

    def test_missing_title_returns_400_without_calling_pipeline(self):
        handler = _make_handler(json.dumps({}).encode())
        with patch("assistant_os.pipelines.work_pipeline.execute") as mock_execute:
            from assistant_os.handlers.work import handle_work_create
            handle_work_create(handler, _REMOTE)
            mock_execute.assert_not_called()
        status_code, _ = handler._send_json_response.call_args[0]
        self.assertEqual(status_code, 400)


# ---------------------------------------------------------------------------
# 3. /work/delete → work_pipeline.execute()
# ---------------------------------------------------------------------------

class TestWorkDeleteCanonicalPath(unittest.TestCase):

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_routes_through_pipeline(self, mock_execute):
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_DELETE,
            domain="WORK",
            message="Tareas eliminadas: 2/2",
            data={"type": "work_delete", "deleted_count": 2, "total_matched": 2},
        )
        body = json.dumps({"keywords": ["test"], "delete_all": False}).encode()
        handler = _make_handler(body)

        from assistant_os.handlers.work import handle_work_delete
        handle_work_delete(handler, _REMOTE)

        mock_execute.assert_called_once()
        plan_arg, _ = mock_execute.call_args[0]
        self.assertEqual(plan_arg.get("action"), "WORK_DELETE")
        self.assertEqual(plan_arg.get("filters", {}).get("keywords"), ["test"])

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_response_contains_execution_id(self, mock_execute):
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_DELETE,
            domain="WORK",
            message="OK",
            data={"deleted_count": 0},
            plan_id="plan-wd-1",
        )
        body = json.dumps({"keywords": ["x"]}).encode()
        handler = _make_handler(body)
        from assistant_os.handlers.work import handle_work_delete
        handle_work_delete(handler, _REMOTE)

        resp = _captured_response(handler)
        self.assertIn("execution_id", resp)
        self.assertIsNotNone(resp["execution_id"])

    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_backward_compat_fields_present(self, mock_execute):
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_DELETE,
            domain="WORK",
            message="OK",
            data={"deleted_count": 3},
        )
        body = json.dumps({"keywords": ["x"]}).encode()
        handler = _make_handler(body)
        from assistant_os.handlers.work import handle_work_delete
        handle_work_delete(handler, _REMOTE)

        resp = _captured_response(handler)
        for field in ("ok", "deleted_count", "archived_count", "pages"):
            self.assertIn(field, resp)

    def test_missing_criteria_returns_400_without_calling_pipeline(self):
        handler = _make_handler(json.dumps({}).encode())
        with patch("assistant_os.pipelines.work_pipeline.execute") as mock_execute:
            from assistant_os.handlers.work import handle_work_delete
            handle_work_delete(handler, _REMOTE)
            mock_execute.assert_not_called()
        status_code, _ = handler._send_json_response.call_args[0]
        self.assertEqual(status_code, 400)


# ---------------------------------------------------------------------------
# 4. /fin/expense → fin_pipeline.execute()
# ---------------------------------------------------------------------------

class TestFinExpenseCanonicalPath(unittest.TestCase):

    def _make_fin_handler(self, text: str = "Gasté $50 en taxi", session_id: str = "") -> MagicMock:
        body = json.dumps({"text": text, "session_id": session_id}).encode()
        handler = MagicMock(spec=WebhookHandler)
        handler._check_auth.return_value = None
        handler._read_body.return_value = (body, None)
        handler.headers = {"Content-Type": "application/json"}
        return handler

    @patch("assistant_os.webhook_server.check_sheets_available", return_value=False)
    @patch("assistant_os.pipelines.fin_pipeline.execute")
    def test_routes_through_pipeline(self, mock_execute, mock_sheets):
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_FIN_EXPENSE,
            domain="FIN",
            message="Gasto detectado",
            data={
                "type": "expense_parsed",
                "expense": {"monto": 50.0, "moneda": "USD", "categoria": "taxi",
                            "responsable": "Jorge", "fecha": "2026-04-07",
                            "descripcion": "taxi", "itbms": False},
                "missing_fields": [],
                "needs_confirmation": False,
                "ambiguous_responsables": [],
            },
        )
        handler = self._make_fin_handler()
        WebhookHandler._handle_fin_expense(handler, _REMOTE)

        mock_execute.assert_called_once()
        plan_arg, ctx_arg = mock_execute.call_args[0]
        self.assertEqual(plan_arg.get("action"), "FIN_EXPENSE")
        self.assertEqual(plan_arg.get("raw_text"), "Gasté $50 en taxi")

    @patch("assistant_os.webhook_server.check_sheets_available", return_value=False)
    @patch("assistant_os.pipelines.fin_pipeline.execute")
    def test_response_contains_execution_id(self, mock_execute, mock_sheets):
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_FIN_EXPENSE,
            domain="FIN",
            message="Gasto detectado",
            data={
                "type": "expense_parsed",
                "expense": {"monto": 50.0, "moneda": "USD", "categoria": "taxi",
                            "responsable": "Jorge", "fecha": "2026-04-07",
                            "descripcion": "taxi", "itbms": False},
                "missing_fields": [],
                "needs_confirmation": False,
                "ambiguous_responsables": [],
            },
            plan_id="plan-fe-1",
        )
        handler = self._make_fin_handler()
        WebhookHandler._handle_fin_expense(handler, _REMOTE)

        _, resp = handler._send_json_response.call_args[0]
        self.assertIn("execution_id", resp)
        self.assertIsNotNone(resp["execution_id"])

    @patch("assistant_os.webhook_server.check_sheets_available", return_value=False)
    @patch("assistant_os.pipelines.fin_pipeline.execute")
    def test_parse_failure_returns_execution_id(self, mock_execute, mock_sheets):
        mock_execute.return_value = make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_FIN_EXPENSE,
            domain="FIN",
            message="No se pudo parsear el gasto",
            data={"missing_fields": ["monto"], "needs_confirmation": False},
            error={"type": "ExpenseParseError", "message": "No se pudo parsear el gasto"},
        )
        handler = self._make_fin_handler("texto sin monto")
        WebhookHandler._handle_fin_expense(handler, _REMOTE)

        _, resp = handler._send_json_response.call_args[0]
        self.assertIn("execution_id", resp)


# ---------------------------------------------------------------------------
# 5. fin_pipeline bug fix: parse_expense receives ExpenseRequest, not string
# ---------------------------------------------------------------------------

class TestFinPipelineBugFix(unittest.TestCase):

    @patch("assistant_os.fin_expense.parse_expense")
    def test_parse_expense_called_with_dict(self, mock_parse):
        """_fin_expense_execute must call parse_expense with a dict, not a raw string."""
        mock_parse.return_value = {
            "ok": True,
            "expense": {"monto": 10.0, "moneda": "USD", "categoria": "food",
                        "responsable": "Jorge", "fecha": "2026-04-07",
                        "descripcion": "food", "itbms": False},
            "message": "OK",
            "missing_fields": [],
            "needs_confirmation": False,
            "ambiguous_responsables": [],
        }
        from assistant_os.pipelines.fin_pipeline import _fin_expense_execute

        plan = {
            "action": "FIN_EXPENSE",
            "raw_text": "Gasté $10 en comida",
            "filters": {"override": {}, "session_id": "sess-1"},
        }
        _fin_expense_execute(plan)

        mock_parse.assert_called_once()
        arg = mock_parse.call_args[0][0]
        self.assertIsInstance(arg, dict, "parse_expense must be called with a dict")
        self.assertIn("text", arg)
        self.assertEqual(arg["text"], "Gasté $10 en comida")
        self.assertIn("session_id", arg)
        self.assertEqual(arg["session_id"], "sess-1")


# ---------------------------------------------------------------------------
# 6. Policy layer is invoked for WORK handlers
# ---------------------------------------------------------------------------

class TestPolicyLayerInvoked(unittest.TestCase):

    @patch("assistant_os.core.policy.build_policy_decision")
    @patch("assistant_os.pipelines.work_pipeline.execute")
    def test_build_policy_called_for_work_query(self, mock_execute, mock_bpd):
        from assistant_os.contracts import build_policy_decision as real_bpd
        # Let build_policy_decision run normally but spy it
        mock_bpd.side_effect = real_bpd
        mock_execute.return_value = make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_QUERY,
            domain="WORK",
            message="OK",
            data={"items": [], "total": 0, "formatted": "", "filters": {}},
        )
        handler = _make_handler(b"{}")
        from assistant_os.handlers.work import handle_work_query
        handle_work_query(handler, _REMOTE)

        # build_policy_decision is called via build_policy → should have been invoked
        mock_bpd.assert_called_once()


if __name__ == "__main__":
    unittest.main()
