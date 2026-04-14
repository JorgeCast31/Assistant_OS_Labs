import unittest
from unittest.mock import patch


class TestAdvisoryEngine(unittest.TestCase):
    @patch("assistant_os.mso.advisory_engine.consult_advisory")
    def test_disabled_mode_returns_non_fatal_bundle(self, mock_consult):
        from assistant_os.mso.advisory_engine import consult_orchestrator_advisory

        mock_consult.return_value = {
            "status": "disabled",
            "provider": "ollama",
            "model": "llama3.2:3b-instruct",
            "advisory": {},
            "latency_ms": 0,
            "error": "disabled",
        }

        result = consult_orchestrator_advisory(
            text="listar tareas",
            intent={"operation": "WORK_QUERY", "domain": "WORK"},
            plan={"action": "WORK_QUERY", "preview": "Consultar tareas"},
        )

        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["consulted_roles"], [])

    @patch("assistant_os.mso.advisory_engine.consult_advisory")
    def test_successful_bundle_normalizes_reasoning_routing_and_code_packaging(self, mock_consult):
        from assistant_os.mso.advisory_engine import consult_orchestrator_advisory

        mock_consult.return_value = {
            "status": "ok",
            "provider": "ollama",
            "model": "llama3.2:3b-instruct",
            "latency_ms": 44,
            "error": None,
            "advisory": {
                "reasoning_summary": "User wants a targeted code fix.",
                "routing_hint": "Stay in CODE_FIX.",
                "suggested_domain": "CODE",
                "suggested_action": "CODE_FIX",
                "execution_posture_hint": "confirm",
                "confidence_note": "high",
                "code_task_summary": "Fix the crash in src/main.py.",
                "repo_context": "Single-file bugfix in app startup path.",
                "constraints": ["Do not redesign startup flow."],
                "expected_artifact": "A minimal bugfix patch.",
                "risk_notes": ["Avoid widening write scope."],
            },
        }

        result = consult_orchestrator_advisory(
            text="fix the crash in src/main.py",
            intent={"operation": "CODE_FIX", "domain": "CODE"},
            plan={"action": "CODE_FIX", "preview": "Corregir codigo"},
        )

        self.assertEqual(result["status"], "ok")
        self.assertIn("reasoning_summary", result["consulted_roles"])
        self.assertIn("routing_hint", result["consulted_roles"])
        self.assertIn("code_packaging", result["consulted_roles"])
        self.assertEqual(result["routing_hint"]["suggested_action"], "CODE_FIX")
        self.assertEqual(result["code_package"]["expected_artifact"], "A minimal bugfix patch.")

    @patch("assistant_os.mso.advisory_engine.consult_advisory")
    def test_malformed_but_json_output_is_ignored_safely(self, mock_consult):
        from assistant_os.mso.advisory_engine import consult_orchestrator_advisory

        mock_consult.return_value = {
            "status": "ok",
            "provider": "ollama",
            "model": "llama3.2:3b-instruct",
            "latency_ms": 30,
            "error": None,
            "advisory": {"unexpected": "shape"},
        }

        result = consult_orchestrator_advisory(
            text="listar tareas",
            intent={"operation": "WORK_QUERY", "domain": "WORK"},
            plan={"action": "WORK_QUERY", "preview": "Consultar tareas"},
        )

        self.assertEqual(result["status"], "ignored")
        self.assertEqual(result["consulted_roles"], [])
        self.assertIn("usable structured fields", result["error"])

    def test_build_advisory_trace_preserves_final_deterministic_decision(self):
        from assistant_os.mso.advisory_engine import build_advisory_trace

        trace = build_advisory_trace(
            {
                "consulted_roles": ["routing_hint"],
                "status": "ok",
                "provider": "ollama",
                "model": "llama3.2:3b-instruct",
                "latency_ms": 12,
                "routing_hint": {"suggested_domain": "CODE", "suggested_action": "CODE_FIX"},
                "summary": {"text": "Needs a code fix."},
                "code_package": {"task_summary": "Fix bug."},
            },
            final_domain="WORK",
            final_action="WORK_QUERY",
            final_execution_mode="auto",
        )

        self.assertEqual(trace["routing_hint_action"], "CODE_FIX")
        self.assertEqual(trace["final_action"], "WORK_QUERY")
        self.assertTrue(trace["code_packaged"])
