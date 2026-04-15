import unittest


class TestMsoStore(unittest.TestCase):
    def setUp(self):
        from assistant_os.storage.mso_store import clear_mso_store

        clear_mso_store()

    def test_store_tracks_counts_and_query_by_trace(self):
        from assistant_os.mso.contracts import SovereignIntent
        from assistant_os.storage.mso_store import get_store_status, persist_intent, query_records

        persist_intent(
            SovereignIntent(
                intent_id="intent-a",
                session_id="session-a",
                user_request_ref="request:a",
                interpreted_goal="Summarize state.",
                priority="normal",
                persistence_recommendation="persist_trace_only",
                risk_posture_hint="normal",
                delegation_recommendation="none",
                justification_summary="Deterministic runtime.",
                timestamp="2026-04-14T00:00:00+00:00",
            )
        )

        records = query_records(kind="intents", trace_id="intent:intent-a")
        status = get_store_status()

        self.assertEqual(len(records), 1)
        self.assertEqual(status["counts"]["intents"], 1)

    def test_cleanup_expired_records_removes_old_artifacts(self):
        from assistant_os.mso.contracts import ExecutionCapability
        from assistant_os.storage.mso_store import cleanup_expired_records, get_store_status, persist_execution_capability

        persist_execution_capability(
            ExecutionCapability(
                capability_id="cap-old",
                task_id="task-old",
                execution_class="BASIC_COGNITIVE_EXECUTION",
                allowed_operations=["read_system_state"],
                scope={"domain": "COGNITIVE"},
                issued_at="2026-04-14T00:00:00+00:00",
                expires_at="2026-04-14T00:00:00+00:00",
                issued_by="kernel",
                trace_id="trace:old",
            )
        )

        deleted = cleanup_expired_records(now_ts="2026-04-15T00:00:00+00:00")
        status = get_store_status()

        self.assertEqual(deleted["capabilities"], 1)
        self.assertEqual(status["counts"]["capabilities"], 0)


if __name__ == "__main__":
    unittest.main()
