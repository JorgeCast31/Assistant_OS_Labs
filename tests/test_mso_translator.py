import unittest


class TestMsoTranslator(unittest.TestCase):
    def _intent(self, **overrides):
        from assistant_os.mso.contracts import SovereignIntent

        data = {
            "intent_id": "intent-1",
            "session_id": "session-1",
            "user_request_ref": "request:1",
            "interpreted_goal": "Summarize current system state.",
            "priority": "normal",
            "persistence_recommendation": "persist_trace_only",
            "risk_posture_hint": "normal",
            "delegation_recommendation": "none",
            "justification_summary": "Deterministic sovereign interpretation.",
            "timestamp": "2026-04-14T00:00:00+00:00",
        }
        data.update(overrides)
        return SovereignIntent(**data)

    def _delegation(self, **overrides):
        from assistant_os.mso.contracts import DelegationTask

        data = {
            "task_id": "task-1",
            "origin_intent_id": "intent-1",
            "task_type": "BASIC_COGNITIVE_EXECUTION",
            "task_goal": "Summarize current system state.",
            "allowed_operations": ["read_system_state", "summarize_context"],
            "input_refs": ["request:1", "state:current"],
            "scope": {"domain": "COGNITIVE", "max_items": 5},
            "requires_capability": "BASIC_COGNITIVE_EXECUTION",
            "expected_output_schema": {"required_artifact_keys": ["system_state", "summary"]},
            "expiry": "2099-01-01T00:00:00+00:00",
            "trace_id": "trace:task-1",
        }
        data.update(overrides)
        return DelegationTask(**data)

    def test_translate_rejects_unsupported_delegation_recommendation(self):
        from assistant_os.mso.translator import TranslatorValidationError, translate_intent_to_canonical_request

        with self.assertRaises(TranslatorValidationError) as ctx:
            translate_intent_to_canonical_request(
                self._intent(delegation_recommendation="invent_new_path"),
                original_text="please help",
            )

        self.assertEqual(ctx.exception.rejection.reason_code, "unsupported_delegation_recommendation")

    def test_translate_rejects_missing_delegation_task(self):
        from assistant_os.mso.translator import TranslatorValidationError, translate_intent_to_canonical_request

        with self.assertRaises(TranslatorValidationError) as ctx:
            translate_intent_to_canonical_request(
                self._intent(delegation_recommendation="delegate_basic_cognitive_execution"),
                original_text="state summary",
            )

        self.assertEqual(ctx.exception.rejection.reason_code, "missing_delegation_task")

    def test_translate_rejects_ambiguous_none_with_task(self):
        from assistant_os.mso.translator import TranslatorValidationError, translate_intent_to_canonical_request

        with self.assertRaises(TranslatorValidationError) as ctx:
            translate_intent_to_canonical_request(
                self._intent(delegation_recommendation="none"),
                original_text="state summary",
                delegation_task=self._delegation(),
            )

        self.assertEqual(ctx.exception.rejection.reason_code, "unexpected_delegation_task")

    def test_translate_accepts_explicit_delegate_mapping_only(self):
        from assistant_os.contracts import ACTION_BASIC_COGNITIVE_EXECUTION
        from assistant_os.mso.translator import translate_intent_to_canonical_request

        request = translate_intent_to_canonical_request(
            self._intent(delegation_recommendation="delegate_basic_cognitive_execution"),
            original_text="state summary",
            delegation_task=self._delegation(),
        )

        self.assertEqual(request["metadata"]["action"], ACTION_BASIC_COGNITIVE_EXECUTION)
        self.assertEqual(request["metadata"]["translation_rule"], "delegate_basic_cognitive_execution")


if __name__ == "__main__":
    unittest.main()
