"""
Sprint 2 — Full Canonical Entry (FIN + Orchestrator Unification) Tests

Verifies that:
1. WORK handlers now call handle_request (not make_plan/build_policy/pipeline.execute directly)
2. All FIN LEGACY endpoints route through orchestrator.handle_request
3. Orchestrator structured path (req["metadata"]["action"]) bypasses NL classification
4. New FIN pipeline actions produce correct DomainResult shapes
5. execution_id always comes from DomainResult.plan_id (not manually set)

One test per migrated endpoint.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch, call

from assistant_os.contracts import (
    make_domain_result,
    RESULT_TYPE_WORK_QUERY,
    RESULT_TYPE_WORK_CREATE,
    RESULT_TYPE_WORK_DELETE,
    RESULT_TYPE_FIN_EXPENSE,
    RESULT_TYPE_FIN_PLAN,
    RESULT_TYPE_FIN_COMMIT,
    RESULT_TYPE_FIN_CONFIRM,
    RESULT_TYPE_FIN_CHAPERON,
    RESULT_TYPE_FIN_BATCH,
    ACTION_FIN_PLAN,
    ACTION_FIN_COMMIT,
    ACTION_FIN_CONFIRM,
    ACTION_FIN_CHAPERON,
    ACTION_FIN_BATCH,
)
from assistant_os.webhook_server import WebhookHandler

_REMOTE = "127.0.0.1:9999"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(body: bytes = b"{}") -> WebhookHandler:
    handler = MagicMock(spec=WebhookHandler)
    handler._check_auth.return_value = None
    handler._read_body.return_value = (body, None)
    # headers is an instance attribute set at request time, not in spec —
    # provide it explicitly so content-type checks work
    headers_mock = MagicMock()
    headers_mock.get = lambda key, default="": "application/json" if key == "Content-Type" else default
    handler.headers = headers_mock
    return handler


def _captured_response(handler: MagicMock) -> dict:
    assert handler._send_json_response.called, "_send_json_response was never called"
    _, response_dict = handler._send_json_response.call_args[0]
    return response_dict


def _captured_status(handler: MagicMock) -> int:
    assert handler._send_json_response.called
    status, _ = handler._send_json_response.call_args[0]
    return status


# ---------------------------------------------------------------------------
# Orchestrator structured path
# ---------------------------------------------------------------------------

class TestOrchestratorStructuredPath(unittest.TestCase):
    """When req["metadata"]["action"] is set, orchestrator skips NL classify."""

    @patch("assistant_os.core.policy.build_policy")
    @patch("assistant_os.pipelines.fin_pipeline.execute")
    def test_structured_path_skips_classify(self, mock_fin_execute, mock_policy):
        """Structured path must not call semantic.classify."""
        mock_policy.return_value = {"execution_mode": "auto"}
        mock_fin_execute.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_FIN_PLAN, domain="FIN",
            message="Plan ok", data={"items": []},
        )

        from assistant_os.contracts import normalize_request, ACTION_FIN_PLAN, RISK_LOW
        from assistant_os.core.orchestrator import handle_request

        req = normalize_request(
            text="compré 25 dólares en comida",
            filters={},
            metadata={"action": ACTION_FIN_PLAN, "domain": "FIN", "risk_level": RISK_LOW,
                      "requires_confirmation": False},
        )

        with patch("assistant_os.core.semantic.classify") as mock_classify:
            dr = handle_request(req)
            # classify must NOT be called in the structured path
            mock_classify.assert_not_called()

        self.assertTrue(dr["ok"])
        mock_fin_execute.assert_called_once()

    @patch("assistant_os.core.policy.build_policy")
    def test_structured_path_work_query(self, mock_policy):
        """Structured path must route WORK_QUERY correctly via routing registry."""
        mock_policy.return_value = {"execution_mode": "auto"}
        mock_work_execute = MagicMock(return_value=make_domain_result(
            ok=True, result_type=RESULT_TYPE_WORK_QUERY, domain="WORK",
            message="1 tarea", data={"items": [{"title": "Test"}], "total": 1, "formatted": "Test"},
            plan_id="plan-abc",
        ))

        from assistant_os.contracts import normalize_request, ACTION_WORK_QUERY, RISK_LOW
        from assistant_os.core.orchestrator import handle_request
        import assistant_os.core.routing as routing

        orig = routing.DOMAIN_PIPELINES.get("WORK")
        routing.DOMAIN_PIPELINES["WORK"] = mock_work_execute
        try:
            req = normalize_request(
                text="",
                filters={"status": ["NEXT"]},
                metadata={"action": ACTION_WORK_QUERY, "domain": "WORK", "risk_level": RISK_LOW,
                          "requires_confirmation": False},
            )
            dr = handle_request(req)
        finally:
            routing.DOMAIN_PIPELINES["WORK"] = orig

        self.assertTrue(dr["ok"])
        self.assertEqual(dr.get("plan_id"), "plan-abc")
        mock_work_execute.assert_called_once()


# ---------------------------------------------------------------------------
# WORK handlers — now use handle_request (not make_plan/build_policy directly)
# ---------------------------------------------------------------------------

class TestWorkHandlersUseOrchestrator(unittest.TestCase):

    @patch("assistant_os.handlers.work._handle_request")
    def test_work_query_calls_handle_request(self, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_WORK_QUERY, domain="WORK",
            message="ok", data={"items": [], "total": 0, "formatted": ""},
            plan_id="plan-wq-1",
        )
        body = json.dumps({"filters": {"status": ["NEXT"]}}).encode()
        handler = _make_handler(body)

        from assistant_os.handlers.work import handle_work_query
        handle_work_query(handler, _REMOTE)

        mock_handle.assert_called_once()
        req_arg = mock_handle.call_args[0][0]
        self.assertEqual(req_arg["metadata"]["action"], "WORK_QUERY")

        resp = _captured_response(handler)
        self.assertEqual(resp["execution_id"], "plan-wq-1")
        self.assertIn("result_type", resp)

    @patch("assistant_os.handlers.work._handle_request")
    def test_work_create_calls_handle_request(self, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_WORK_CREATE, domain="WORK",
            message="created", data={"page_id": "abc", "url": "http://x", "title": "Task"},
            plan_id="plan-wc-1",
        )
        body = json.dumps({"title": "My Task"}).encode()
        handler = _make_handler(body)

        from assistant_os.handlers.work import handle_work_create
        handle_work_create(handler, _REMOTE)

        mock_handle.assert_called_once()
        req_arg = mock_handle.call_args[0][0]
        self.assertEqual(req_arg["metadata"]["action"], "WORK_CREATE")
        self.assertEqual(req_arg["filters"]["title"], "My Task")

        resp = _captured_response(handler)
        self.assertEqual(resp["execution_id"], "plan-wc-1")

    @patch("assistant_os.handlers.work._handle_request")
    def test_work_delete_calls_handle_request(self, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_WORK_DELETE, domain="WORK",
            message="deleted", data={"deleted_count": 1, "archived_count": 1},
            plan_id="plan-wd-1",
        )
        body = json.dumps({"keywords": ["test"]}).encode()
        handler = _make_handler(body)

        from assistant_os.handlers.work import handle_work_delete
        handle_work_delete(handler, _REMOTE)

        mock_handle.assert_called_once()
        req_arg = mock_handle.call_args[0][0]
        self.assertEqual(req_arg["metadata"]["action"], "WORK_DELETE")

        resp = _captured_response(handler)
        self.assertEqual(resp["execution_id"], "plan-wd-1")


# ---------------------------------------------------------------------------
# FIN /fin/expense — uses handle_request
# ---------------------------------------------------------------------------

class TestFinExpenseCanonicalSprint2(unittest.TestCase):

    @patch("assistant_os.core.orchestrator.handle_request")
    def test_routes_through_orchestrator(self, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_FIN_EXPENSE, domain="FIN",
            message="Gasto detectado",
            data={
                "expense": {"monto": 25.0, "moneda": "USD", "fecha": "2026-04-07",
                            "descripcion": "comida", "responsable": "Jorge",
                            "categoria": "Comida", "itbms": False},
                "needs_confirmation": False,
                "missing_fields": [],
                "ambiguous_responsables": [],
            },
            plan_id="plan-fe-1",
        )
        # Sheets not needed: patch check_sheets_available to avoid side effects
        with patch("assistant_os.webhook_server.check_sheets_available", return_value=False):
            body = json.dumps({"text": "25$ en comida"}).encode()
            handler = _make_handler(body)
            WebhookHandler._handle_fin_expense(handler, _REMOTE)

        mock_handle.assert_called_once()
        req_arg = mock_handle.call_args[0][0]
        self.assertEqual(req_arg["metadata"]["action"], "FIN_EXPENSE")
        self.assertEqual(req_arg["text"], "25$ en comida")

    @patch("assistant_os.core.orchestrator.handle_request")
    def test_execution_id_from_domain_result(self, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_FIN_EXPENSE, domain="FIN",
            message="Gasto detectado",
            data={"expense": {"monto": 25.0}, "needs_confirmation": True,
                  "missing_fields": ["responsable"], "ambiguous_responsables": []},
            plan_id="plan-fe-2",
        )
        body = json.dumps({"text": "25$"}).encode()
        handler = _make_handler(body)
        WebhookHandler._handle_fin_expense(handler, _REMOTE)

        resp = _captured_response(handler)
        self.assertEqual(resp.get("execution_id"), "plan-fe-2")


# ---------------------------------------------------------------------------
# FIN /fin/plan — Sprint 2 migration
# ---------------------------------------------------------------------------

class TestFinPlanSprint2(unittest.TestCase):

    @patch("assistant_os.core.orchestrator.handle_request")
    def test_routes_through_orchestrator(self, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_FIN_PLAN, domain="FIN",
            message="Plan generado",
            data={
                "kind": "fin_plan", "mode": "single", "total_items": 1,
                "items": [{"id": "i1", "draft_expense": {}, "missing_fields": [],
                           "confidence": 0.9, "raw_segment": "25$ comida"}],
                "needs_clarification": False, "clarification_prompt": "",
                "session_context": {}, "message": "Plan generado",
            },
            plan_id="plan-fp-1",
        )
        body = json.dumps({"text": "25$ en comida"}).encode()
        handler = _make_handler(body)
        WebhookHandler._handle_fin_plan(handler, _REMOTE)

        mock_handle.assert_called_once()
        req_arg = mock_handle.call_args[0][0]
        self.assertEqual(req_arg["metadata"]["action"], ACTION_FIN_PLAN)

        resp = _captured_response(handler)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["total_items"], 1)
        self.assertEqual(resp["execution_id"], "plan-fp-1")

    @patch("assistant_os.core.orchestrator.handle_request")
    def test_missing_text_returns_400(self, mock_handle):
        body = json.dumps({}).encode()
        handler = _make_handler(body)
        WebhookHandler._handle_fin_plan(handler, _REMOTE)

        mock_handle.assert_not_called()
        self.assertEqual(_captured_status(handler), 400)


# ---------------------------------------------------------------------------
# FIN /fin/commit — Sprint 2 migration
# ---------------------------------------------------------------------------

class TestFinCommitSprint2(unittest.TestCase):

    @patch("assistant_os.core.orchestrator.handle_request")
    @patch("assistant_os.webhook_server.check_sheets_available", return_value=True)
    def test_routes_through_orchestrator(self, _, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_FIN_COMMIT, domain="FIN",
            message="Gasto guardado en Sheets (fila 5)",
            data={"stored": True, "row_number": 5, "expense": {}},
            plan_id="plan-fc-1",
        )
        expense = {"fecha": "2026-04-07", "monto": 25.0, "moneda": "USD",
                   "descripcion": "comida", "responsable": "Jorge",
                   "categoria": "Comida", "itbms": False}
        body = json.dumps({"expense": expense}).encode()
        handler = _make_handler(body)
        WebhookHandler._handle_fin_commit(handler, _REMOTE)

        mock_handle.assert_called_once()
        req_arg = mock_handle.call_args[0][0]
        self.assertEqual(req_arg["metadata"]["action"], ACTION_FIN_COMMIT)
        self.assertIn("expense", req_arg["filters"])

        resp = _captured_response(handler)
        self.assertTrue(resp["ok"])
        self.assertTrue(resp["stored"])
        self.assertEqual(resp["row_number"], 5)
        self.assertEqual(resp["execution_id"], "plan-fc-1")

    @patch("assistant_os.core.orchestrator.handle_request")
    @patch("assistant_os.webhook_server.check_sheets_available", return_value=True)
    def test_missing_expense_returns_400(self, _, mock_handle):
        body = json.dumps({}).encode()
        handler = _make_handler(body)
        WebhookHandler._handle_fin_commit(handler, _REMOTE)

        mock_handle.assert_not_called()
        self.assertEqual(_captured_status(handler), 400)


# ---------------------------------------------------------------------------
# FIN /fin/chaperon — Sprint 2 migration
# ---------------------------------------------------------------------------

class TestFinChaperonSprint2(unittest.TestCase):

    @patch("assistant_os.core.orchestrator.handle_request")
    def test_fin_domain_routes_through_orchestrator(self, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_FIN_CHAPERON, domain="FIN",
            message="Análisis completado",
            data={
                "action_plan": {"type": "single_fin", "items": [{"monto": 25.0}],
                                "requires_confirmation": False,
                                "clarification_questions": [],
                                "inherited_context": {}, "summary_text": ""},
                "should_execute": True,
                "confirmation_message": None,
                "raw_text": "25$", "detected_domain": "FIN",
            },
            plan_id="plan-chap-1",
        )
        body = json.dumps({"text": "25$ en comida", "domain": "FIN"}).encode()
        handler = _make_handler(body)
        WebhookHandler._handle_fin_chaperon(handler, _REMOTE)

        mock_handle.assert_called_once()
        req_arg = mock_handle.call_args[0][0]
        self.assertEqual(req_arg["metadata"]["action"], ACTION_FIN_CHAPERON)

        resp = _captured_response(handler)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["execution_id"], "plan-chap-1")

    @patch("assistant_os.core.orchestrator.handle_request")
    def test_work_domain_routes_to_work_query(self, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_WORK_QUERY, domain="WORK",
            message="1 tarea",
            data={"items": [{"title": "Test"}], "total": 1, "formatted": "Test"},
            plan_id="plan-chap-work-1",
        )
        with patch("assistant_os.webhook_server.parse_work_query_filters", return_value={}):
            body = json.dumps({"text": "mis tareas", "domain": "WORK"}).encode()
            handler = _make_handler(body)
            WebhookHandler._handle_fin_chaperon(handler, _REMOTE)

        mock_handle.assert_called_once()
        req_arg = mock_handle.call_args[0][0]
        self.assertEqual(req_arg["metadata"]["action"], "WORK_QUERY")

    def test_pending_flow_short_circuits(self):
        body = json.dumps({"text": "25$", "session_context": {"pending": True}}).encode()
        handler = _make_handler(body)
        with patch("assistant_os.webhook_server._handle_request") as mock_handle:
            WebhookHandler._handle_fin_chaperon(handler, _REMOTE)
            mock_handle.assert_not_called()

        resp = _captured_response(handler)
        self.assertEqual(resp["type"], "pending_flow")


# ---------------------------------------------------------------------------
# FIN /fin/expense/batch — Sprint 2 migration
# ---------------------------------------------------------------------------

class TestFinExpenseBatchSprint2(unittest.TestCase):

    @patch("assistant_os.core.orchestrator.handle_request")
    def test_routes_through_orchestrator(self, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_FIN_BATCH, domain="FIN",
            message="Lote procesado: 1/1 guardados",
            data={"total_items": 1, "stored_count": 1, "sheets_available": True,
                  "results": [{"index": 0, "ok": True, "stored": True}],
                  "message": "Lote procesado: 1/1 guardados"},
            plan_id="plan-batch-1",
        )
        body = json.dumps({"items": [{"raw_segment": "25$ comida"}]}).encode()
        handler = _make_handler(body)
        WebhookHandler._handle_fin_expense_batch(handler, _REMOTE)

        mock_handle.assert_called_once()
        req_arg = mock_handle.call_args[0][0]
        self.assertEqual(req_arg["metadata"]["action"], ACTION_FIN_BATCH)
        self.assertIn("items", req_arg["filters"])

        resp = _captured_response(handler)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["stored_count"], 1)
        self.assertEqual(resp["execution_id"], "plan-batch-1")

    @patch("assistant_os.core.orchestrator.handle_request")
    def test_empty_items_returns_400(self, mock_handle):
        body = json.dumps({"items": []}).encode()
        handler = _make_handler(body)
        WebhookHandler._handle_fin_expense_batch(handler, _REMOTE)

        mock_handle.assert_not_called()
        self.assertEqual(_captured_status(handler), 400)


# ---------------------------------------------------------------------------
# FIN /fin/expense/confirm — Sprint 2 migration
# ---------------------------------------------------------------------------

class TestFinExpenseConfirmSprint2(unittest.TestCase):

    @patch("assistant_os.core.orchestrator.handle_request")
    def test_routes_through_orchestrator(self, mock_handle):
        mock_handle.return_value = make_domain_result(
            ok=True, result_type=RESULT_TYPE_FIN_CONFIRM, domain="FIN",
            message="Guardado en Sheets (fila 3)",
            data={"stored": True, "row_number": 3,
                  "expense": {"monto": 25.0, "moneda": "USD"}},
            plan_id="plan-conf-1",
        )
        body = json.dumps({
            "fecha": "2026-04-07", "monto": 25.0, "moneda": "USD",
            "descripcion": "comida", "responsable": "Jorge",
        }).encode()
        handler = _make_handler(body)
        WebhookHandler._handle_fin_expense_confirm(handler, _REMOTE)

        mock_handle.assert_called_once()
        req_arg = mock_handle.call_args[0][0]
        self.assertEqual(req_arg["metadata"]["action"], ACTION_FIN_CONFIRM)
        self.assertEqual(req_arg["filters"]["monto"], 25.0)

        resp = _captured_response(handler)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["row_number"], 3)
        self.assertEqual(resp["execution_id"], "plan-conf-1")

    @patch("assistant_os.core.orchestrator.handle_request")
    def test_missing_required_field_returns_400(self, mock_handle):
        body = json.dumps({"fecha": "2026-04-07", "monto": 25.0}).encode()
        handler = _make_handler(body)
        WebhookHandler._handle_fin_expense_confirm(handler, _REMOTE)

        mock_handle.assert_not_called()
        self.assertEqual(_captured_status(handler), 400)


# ---------------------------------------------------------------------------
# FIN pipeline — new action handlers produce correct DomainResult
# ---------------------------------------------------------------------------

class TestFinPipelineNewActions(unittest.TestCase):

    def test_fin_plan_execute(self):
        from assistant_os.pipelines.fin_pipeline import _fin_plan_execute
        plan = {
            "action": "FIN_PLAN",
            "raw_text": "25$ en comida para Jorge",
            "filters": {},
            "plan_id": "p1",
            "trace_id": "t1",
        }
        with patch("assistant_os.pipelines.fin_pipeline._fin_plan_execute.__module__"):
            pass
        with patch("assistant_os.fin_plan.generate_fin_plan") as mock_gen:
            mock_gen.return_value = {
                "ok": True,
                "kind": "fin_plan",
                "mode": "single",
                "total_items": 1,
                "message": "Plan generado",
                "items": [{"id": "i1", "draft_expense": {}, "missing_fields": [],
                           "confidence": 0.9, "raw_segment": "25$ en comida para Jorge"}],
                "needs_clarification": False,
                "clarification_prompt": "",
                "session_context": {},
            }
            dr = _fin_plan_execute(plan)

        self.assertTrue(dr["ok"])
        self.assertEqual(dr["result_type"], RESULT_TYPE_FIN_PLAN)
        self.assertEqual(dr["domain"], "FIN")
        self.assertEqual(dr["data"]["total_items"], 1)
        self.assertEqual(dr.get("plan_id"), "p1")

    def test_fin_chaperon_execute(self):
        from assistant_os.pipelines.fin_pipeline import _fin_chaperon_execute
        plan = {
            "action": "FIN_CHAPERON",
            "raw_text": "25$ en comida",
            "filters": {"domain": "FIN", "session_context": None},
            "plan_id": "p2",
            "trace_id": "t2",
        }
        with patch("assistant_os.chaperon.run_chaperon") as mock_run:
            mock_run.return_value = {
                "action_plan": {"type": "single_fin", "items": [],
                                "requires_confirmation": False,
                                "clarification_questions": [],
                                "inherited_context": {}, "summary_text": ""},
                "should_execute": True,
                "confirmation_message": None,
                "raw_text": "25$ en comida",
                "detected_domain": "FIN",
            }
            dr = _fin_chaperon_execute(plan)

        self.assertTrue(dr["ok"])
        self.assertEqual(dr["result_type"], RESULT_TYPE_FIN_CHAPERON)
        self.assertEqual(dr["data"]["detected_domain"], "FIN")

    def test_fin_unknown_action_returns_error(self):
        from assistant_os.pipelines.fin_pipeline import execute
        plan = {"action": "FIN_BOGUS", "raw_text": "", "filters": {}}
        dr = execute(plan, "ctx-x")
        self.assertFalse(dr["ok"])
        self.assertEqual(dr["result_type"], "fin_unknown")


if __name__ == "__main__":
    unittest.main()
