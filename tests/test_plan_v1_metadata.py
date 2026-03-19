"""
Tests for ExecutionPlan v1 identity fields.

Covers:
- make_plan() always produces plan_id (UUID4 string, non-empty)
- make_plan() always produces schema_version = "1"
- make_plan() always produces origin = "canonical" by default
- make_plan() accepts origin = "legacy_adapter"
- plan_id is a valid UUID4 (36-char, 4 hyphens)
- plan_id is unique per call (not reused)
- trace_id is auto-generated when absent
- trace_id is preserved when provided
- ACTION_WORK_UPDATE_BULK constant exists and is distinct from ACTION_WORK_UPDATE
- Stored and loaded plan preserves v1 fields
- Old stored plan without v1 fields does not crash context_store
"""
import re
import tempfile
import unittest
import uuid
from pathlib import Path

import assistant_os.context_store as cs
from assistant_os.contracts import (
    make_plan,
    ACTION_WORK_CREATE,
    ACTION_WORK_UPDATE,
    ACTION_WORK_UPDATE_BULK,
    RISK_MEDIUM,
    RISK_LOW,
)


_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _is_uuid4(value: str) -> bool:
    return bool(_UUID4_RE.match(value.lower()))


# ---------------------------------------------------------------------------
# plan_id
# ---------------------------------------------------------------------------

class TestPlanId(unittest.TestCase):
    def test_plan_id_always_present(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertIn("plan_id", plan)

    def test_plan_id_is_non_empty_string(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertIsInstance(plan["plan_id"], str)
        self.assertTrue(plan["plan_id"])

    def test_plan_id_is_valid_uuid4(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertTrue(_is_uuid4(plan["plan_id"]),
                        f"plan_id {plan['plan_id']!r} is not a valid UUID4")

    def test_plan_id_unique_per_call(self):
        p1 = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        p2 = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertNotEqual(p1["plan_id"], p2["plan_id"])

    def test_plan_id_preserved_when_provided(self):
        fixed_id = str(uuid.uuid4())
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task", plan_id=fixed_id)
        self.assertEqual(plan["plan_id"], fixed_id)

    def test_plan_id_generated_when_none_provided(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task", plan_id=None)
        self.assertTrue(_is_uuid4(plan["plan_id"]))


# ---------------------------------------------------------------------------
# schema_version
# ---------------------------------------------------------------------------

class TestSchemaVersion(unittest.TestCase):
    def test_schema_version_always_present(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertIn("schema_version", plan)

    def test_schema_version_is_string_1(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertEqual(plan["schema_version"], "1")

    def test_schema_version_not_int(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertIsInstance(plan["schema_version"], str)

    def test_schema_version_same_for_all_actions(self):
        for action in (ACTION_WORK_CREATE, ACTION_WORK_UPDATE, ACTION_WORK_UPDATE_BULK):
            with self.subTest(action=action):
                plan = make_plan("WORK", action, "test")
                self.assertEqual(plan["schema_version"], "1")


# ---------------------------------------------------------------------------
# origin
# ---------------------------------------------------------------------------

class TestOrigin(unittest.TestCase):
    def test_origin_defaults_to_canonical(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertEqual(plan["origin"], "canonical")

    def test_origin_accepts_legacy_adapter(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task", origin="legacy_adapter")
        self.assertEqual(plan["origin"], "legacy_adapter")

    def test_origin_is_string(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertIsInstance(plan["origin"], str)

    def test_origin_canonical_for_fin(self):
        plan = make_plan("FIN", "FIN_EXPENSE", "test expense")
        self.assertEqual(plan["origin"], "canonical")


# ---------------------------------------------------------------------------
# trace_id
# ---------------------------------------------------------------------------

class TestTraceId(unittest.TestCase):
    def test_trace_id_auto_generated_when_absent(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertIn("trace_id", plan)
        self.assertTrue(plan["trace_id"])

    def test_trace_id_preserved_when_provided(self):
        custom_trace = "abc12345"
        plan = make_plan("WORK", ACTION_WORK_CREATE, "test task", trace_id=custom_trace)
        self.assertEqual(plan["trace_id"], custom_trace)

    def test_trace_id_unique_per_call_when_not_provided(self):
        p1 = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        p2 = make_plan("WORK", ACTION_WORK_CREATE, "test task")
        self.assertNotEqual(p1["trace_id"], p2["trace_id"])

    def test_trace_id_propagated_from_upstream(self):
        upstream_trace = "upstream-trace-001"
        plan = make_plan("WORK", ACTION_WORK_UPDATE, "task X", trace_id=upstream_trace)
        self.assertEqual(plan["trace_id"], upstream_trace)


# ---------------------------------------------------------------------------
# ACTION_WORK_UPDATE_BULK
# ---------------------------------------------------------------------------

class TestActionWorkUpdateBulk(unittest.TestCase):
    def test_constant_exists(self):
        self.assertEqual(ACTION_WORK_UPDATE_BULK, "WORK_UPDATE_BULK")

    def test_distinct_from_action_work_update(self):
        self.assertNotEqual(ACTION_WORK_UPDATE_BULK, ACTION_WORK_UPDATE)

    def test_make_plan_with_bulk_action(self):
        plan = make_plan("WORK", ACTION_WORK_UPDATE_BULK, "Multiple tasks")
        self.assertEqual(plan["action"], ACTION_WORK_UPDATE_BULK)
        self.assertEqual(plan["schema_version"], "1")
        self.assertTrue(plan["plan_id"])

    def test_bulk_plan_has_all_v1_fields(self):
        plan = make_plan("WORK", ACTION_WORK_UPDATE_BULK, "Multiple tasks")
        for field in ("plan_id", "schema_version", "origin", "trace_id"):
            with self.subTest(field=field):
                self.assertIn(field, plan)


# ---------------------------------------------------------------------------
# v1 fields survive context_store round-trip
# ---------------------------------------------------------------------------

class TestPlanV1PersistenceRoundTrip(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = Path(self.temp_dir) / "context_store.json"
        self._orig_file = cs.CONTEXT_STORE_FILE
        cs.CONTEXT_STORE_FILE = self.temp_file
        with cs._lock:
            cs._store.clear()

    def tearDown(self):
        cs.CONTEXT_STORE_FILE = self._orig_file
        with cs._lock:
            cs._store.clear()

    def test_v1_fields_survive_disk_round_trip(self):
        plan = make_plan("WORK", ACTION_WORK_CREATE, "round-trip task")
        original_plan_id = plan["plan_id"]
        original_trace_id = plan["trace_id"]
        ctx_id = "ctx-v1-roundtrip"

        cs.store_pending_plan(ctx_id, plan, "WORK_CREATE", raw_text="crear tarea round-trip")

        # Simulate restart: clear in-memory and reload
        with cs._lock:
            cs._store.clear()
        loaded = cs._load_store_from_disk()
        with cs._lock:
            cs._store.update(loaded)

        retrieved = cs.get_pending_plan(ctx_id)
        self.assertIsNotNone(retrieved)
        retrieved_plan = retrieved["plan"]

        self.assertEqual(retrieved_plan["plan_id"], original_plan_id)
        self.assertEqual(retrieved_plan["schema_version"], "1")
        self.assertEqual(retrieved_plan["origin"], "canonical")
        self.assertEqual(retrieved_plan["trace_id"], original_trace_id)

    def test_old_plan_without_v1_fields_does_not_crash_retrieval(self):
        """Backward compat: stored plans missing v1 fields must not crash get_pending_plan."""
        from assistant_os.contracts import now_iso
        from datetime import datetime, timezone, timedelta

        old_plan = {
            "domain": "WORK",
            "action": "WORK_CREATE",
            "target": "legacy task",
            "requires_confirmation": True,
            "risk_level": "medium",
            # No plan_id, schema_version, or origin
        }
        ctx_id = "ctx-legacy-plan"
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        with cs._lock:
            cs._store[ctx_id] = {
                "plan": old_plan,
                "operation": "WORK_CREATE",
                "raw_text": "old plan",
                "expires_at": expires,
                "created_at": now_iso(),
            }

        retrieved = cs.get_pending_plan(ctx_id)

        # Must not raise — the old plan is returned as-is
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["plan"]["action"], "WORK_CREATE")
        # v1 fields absent — callers must use .get()
        self.assertIsNone(retrieved["plan"].get("plan_id"))
        self.assertIsNone(retrieved["plan"].get("schema_version"))


if __name__ == "__main__":
    unittest.main()
