import unittest
from unittest.mock import patch


class TestOrchestratorLocalLlmFallback(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_task_registry()
        reset_trace_aggregator()

    def _request(self, text: str) -> dict:
        from assistant_os.contracts import CanonicalRequest

        return CanonicalRequest(context_id="ctx-local-llm", text=text, filters={}, metadata={})

    @patch("assistant_os.core.orchestrator._consult_mso_advisory")
    def test_disabled_or_failed_advisory_does_not_change_result(self, mock_consult):
        from assistant_os.core.orchestrator import handle_request

        mock_consult.return_value = None
        req = self._request("tareas inbox")
        result = handle_request(req)

        self.assertEqual(result["result_type"], "work_query")
        mock_consult.assert_called_once()


class TestOrchestratorLocalLlmPassThrough(unittest.TestCase):
    def setUp(self):
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator

        reset_task_registry()
        reset_trace_aggregator()

    def _request(self, text: str) -> dict:
        from assistant_os.contracts import CanonicalRequest

        return CanonicalRequest(context_id="ctx-local-llm-ok", text=text, filters={}, metadata={})

    @patch("assistant_os.pipelines.work_pipeline.execute")
    @patch("assistant_os.core.orchestrator._consult_mso_advisory")
    def test_successful_advisory_is_attached_privately_to_execution_plan(self, mock_consult, mock_execute):
        from assistant_os.core.orchestrator import handle_request

        mock_consult.return_value = {
            "status": "ok",
            "provider": "ollama",
            "model": "llama3.2:3b-instruct",
            "latency_ms": 22,
            "consulted_roles": ["reasoning_summary", "routing_hint"],
            "summary": {"text": "Looks like a work query."},
            "routing_hint": {"suggested_action": "WORK_QUERY", "suggested_domain": "WORK"},
        }
        mock_execute.return_value = {
            "ok": True,
            "result_type": "work_query",
            "domain": "WORK",
            "message": "ok",
            "data": {"items": [], "total": 0},
            "error": None,
        }

        req = self._request("tareas inbox")
        result = handle_request(req)

        self.assertEqual(result["result_type"], "work_query")
        plan_arg = mock_execute.call_args[0][0]
        self.assertIn("_mso_advisory", plan_arg)
        self.assertEqual(plan_arg["_mso_advisory"]["provider"], "ollama")
        self.assertIn("_mso_trace", plan_arg)
        self.assertEqual(plan_arg["_mso_trace"]["final_action"], "WORK_QUERY")

    @patch("assistant_os.core.orchestrator._consult_mso_advisory")
    def test_confirmation_response_includes_advisory_trace_without_overriding_plan(self, mock_consult):
        from assistant_os.core.orchestrator import handle_request

        mock_consult.return_value = {
            "status": "ok",
            "provider": "ollama",
            "model": "llama3.2:3b-instruct",
            "latency_ms": 11,
            "consulted_roles": ["routing_hint"],
            "routing_hint": {"suggested_action": "WORK_CREATE", "suggested_domain": "WORK"},
        }

        req = self._request("Crea una tarea: Titulo: Test. Proyecto: X.")
        result = handle_request(req)

        self.assertEqual(result["result_type"], "plan_confirmation_required")
        self.assertIn("advisory_trace", result["data"])
        self.assertEqual(result["data"]["advisory_trace"]["final_execution_mode"], "confirm")
