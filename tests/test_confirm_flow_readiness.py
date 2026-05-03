"""Tests for assistant_os.confirm_flow.readiness.

Verifies the CONFIRM FLOW observability producer:
1. get_confirm_flow_summary() returns a structured summary dict.
2. list_pending_summary() exposes only metadata (NEVER plan, NEVER raw_text).
3. The producer is fail-soft: never raises, even if context_store is broken.
4. Counts (pending_count, expired_pending_count) are derived from the store.
5. The compact list is limited (default 10) and sorted oldest-first.
6. age_seconds and time_to_expire_seconds are computed from now, not stored.
7. Producer is read-only — never mutates the store, never executes a plan.
8. Producer never claims authority — no execution_mode, no GovernanceVerdict,
   no "ready_to_confirm", no "authorized".
9. Output is JSON-serializable.
10. Empty store yields a valid zero-summary.

INVARIANTS this module enforces (architectural):
  - Confirm flow producer is a passive observer of context_store.
  - It never imports kernel, router, pipelines, runner, or governance engines.
  - It never reads/exposes the `plan` field (which may carry user payload).
  - It never reads/exposes the `raw_text` field (original user input).
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_stored(operation: str, *, age_seconds: int = 0,
                 ttl_seconds: int = 15 * 60) -> dict:
    """Build a StoredContext-shape dict relative to now."""
    now = datetime.now(timezone.utc)
    created = now - timedelta(seconds=age_seconds)
    expires = created + timedelta(seconds=ttl_seconds)
    return {
        "plan":       {"action": "secret_action", "data": {"sensitive": "payload"}},
        "operation":  operation,
        "raw_text":   "user typed something private here",
        "created_at": _iso(created),
        "expires_at": _iso(expires),
    }


class _FakeStore(dict):
    """Drop-in replacement for context_store internal _store dict."""


# ---------------------------------------------------------------------------
# Shape / contract tests
# ---------------------------------------------------------------------------

class TestGetConfirmFlowSummaryShape(unittest.TestCase):
    """get_confirm_flow_summary() returns a dict with the documented schema."""

    def test_returns_dict(self) -> None:
        from assistant_os.confirm_flow.readiness import get_confirm_flow_summary
        result = get_confirm_flow_summary()
        self.assertIsInstance(result, dict)

    def test_identity_fields(self) -> None:
        from assistant_os.confirm_flow.readiness import get_confirm_flow_summary
        result = get_confirm_flow_summary()
        self.assertEqual(result["source"], "confirm_flow")
        self.assertIs(result["feature_enabled"], True)
        self.assertIsInstance(result["last_health_check"], str)
        self.assertGreater(len(result["last_health_check"]), 0)
        self.assertIsInstance(result["note"], str)
        self.assertIn("authority", result["note"].lower())

    def test_count_fields(self) -> None:
        from assistant_os.confirm_flow.readiness import get_confirm_flow_summary
        result = get_confirm_flow_summary()
        for k in ("pending_count", "expired_pending_count"):
            self.assertIn(k, result)
            self.assertIsInstance(result[k], int)
            self.assertGreaterEqual(result[k], 0)

    def test_expiry_fields_typed(self) -> None:
        from assistant_os.confirm_flow.readiness import get_confirm_flow_summary
        result = get_confirm_flow_summary()
        # nullable when empty
        self.assertIn("oldest_age_seconds", result)
        self.assertIn(type(result["oldest_age_seconds"]).__name__, ("int", "NoneType"))
        self.assertIn("nearest_expiry_seconds", result)
        self.assertIn(type(result["nearest_expiry_seconds"]).__name__, ("int", "NoneType"))

    def test_pending_list_present(self) -> None:
        from assistant_os.confirm_flow.readiness import get_confirm_flow_summary
        result = get_confirm_flow_summary()
        self.assertIn("pending", result)
        self.assertIsInstance(result["pending"], list)

    def test_output_is_json_serializable(self) -> None:
        from assistant_os.confirm_flow.readiness import get_confirm_flow_summary
        result = get_confirm_flow_summary()
        encoded = json.dumps(result)
        self.assertIsInstance(encoded, str)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["source"], "confirm_flow")


# ---------------------------------------------------------------------------
# Empty store
# ---------------------------------------------------------------------------

class TestEmptyStore(unittest.TestCase):
    """An empty context_store yields a valid zero-summary."""

    def test_empty_store_zero_summary(self) -> None:
        from assistant_os.confirm_flow import readiness
        with patch.object(readiness, "_read_store_snapshot", return_value=({}, None)):
            result = readiness.get_confirm_flow_summary()
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(result["expired_pending_count"], 0)
        self.assertIsNone(result["oldest_age_seconds"])
        self.assertIsNone(result["nearest_expiry_seconds"])
        self.assertEqual(result["pending"], [])


# ---------------------------------------------------------------------------
# Sensitive payload protection — the most important invariant.
# ---------------------------------------------------------------------------

class TestNoSensitivePayloadLeaks(unittest.TestCase):
    """The summary MUST NOT expose `plan` or `raw_text` in any form."""

    def test_pending_entries_have_no_plan(self) -> None:
        from assistant_os.confirm_flow import readiness
        store = {
            "ctx-1": _make_stored("WORK_CREATE", age_seconds=10),
            "ctx-2": _make_stored("FIN_BATCH",  age_seconds=20),
        }
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            result = readiness.get_confirm_flow_summary()
        for entry in result["pending"]:
            self.assertNotIn("plan", entry,
                             "Compact pending entry must NOT contain plan payload.")
            self.assertNotIn("raw_text", entry,
                             "Compact pending entry must NOT contain raw_text.")
            self.assertNotIn("payload", entry)
            self.assertNotIn("data", entry)

    def test_serialized_summary_does_not_contain_sensitive_strings(self) -> None:
        from assistant_os.confirm_flow import readiness
        sentinel = "SUPER_SENSITIVE_USER_INPUT_dont_leak_this"
        stored = _make_stored("WORK_CREATE", age_seconds=10)
        stored["raw_text"] = sentinel
        stored["plan"] = {"action": "x", "user_secret": sentinel}
        with patch.object(readiness, "_read_store_snapshot",
                          return_value=({"ctx-x": stored}, None)):
            result = readiness.get_confirm_flow_summary()
        encoded = json.dumps(result)
        self.assertNotIn(sentinel, encoded,
                         "Sensitive payload leaked through summary serialization.")


# ---------------------------------------------------------------------------
# Counts and aggregation
# ---------------------------------------------------------------------------

class TestCountsAndAggregation(unittest.TestCase):

    def test_pending_count_matches_store(self) -> None:
        from assistant_os.confirm_flow import readiness
        store = {
            "a": _make_stored("WORK_CREATE", age_seconds=5),
            "b": _make_stored("WORK_DELETE", age_seconds=10),
            "c": _make_stored("FIN_BATCH",   age_seconds=15),
        }
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            result = readiness.get_confirm_flow_summary()
        self.assertEqual(result["pending_count"], 3)

    def test_expired_pending_count_excludes_live(self) -> None:
        from assistant_os.confirm_flow import readiness
        # Build one already-expired entry by giving negative ttl.
        expired = _make_stored("WORK_DELETE", age_seconds=10_000, ttl_seconds=10)
        live = _make_stored("WORK_CREATE", age_seconds=5)
        store = {"e1": expired, "l1": live}
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            result = readiness.get_confirm_flow_summary()
        self.assertEqual(result["pending_count"], 2)
        self.assertEqual(result["expired_pending_count"], 1)

    def test_oldest_age_is_largest(self) -> None:
        from assistant_os.confirm_flow import readiness
        store = {
            "a": _make_stored("WORK_CREATE", age_seconds=5),
            "b": _make_stored("WORK_DELETE", age_seconds=120),
            "c": _make_stored("FIN_BATCH",   age_seconds=30),
        }
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            result = readiness.get_confirm_flow_summary()
        self.assertGreaterEqual(result["oldest_age_seconds"], 119)
        self.assertLessEqual(result["oldest_age_seconds"], 122)

    def test_nearest_expiry_picks_shortest_remaining(self) -> None:
        from assistant_os.confirm_flow import readiness
        # ttl=300, age=290 → expires in ~10s
        nearest = _make_stored("WORK_CREATE", age_seconds=290, ttl_seconds=300)
        # ttl=900, age=10 → expires in ~890s
        far = _make_stored("WORK_CREATE", age_seconds=10)
        store = {"n": nearest, "f": far}
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            result = readiness.get_confirm_flow_summary()
        self.assertGreaterEqual(result["nearest_expiry_seconds"], 8)
        self.assertLessEqual(result["nearest_expiry_seconds"], 12)


# ---------------------------------------------------------------------------
# Compact pending list — limit + sort
# ---------------------------------------------------------------------------

class TestPendingListShape(unittest.TestCase):

    def test_each_entry_has_required_metadata(self) -> None:
        from assistant_os.confirm_flow import readiness
        store = {"a": _make_stored("WORK_CREATE", age_seconds=10)}
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            result = readiness.get_confirm_flow_summary()
        self.assertEqual(len(result["pending"]), 1)
        entry = result["pending"][0]
        for k in ("context_id", "operation", "created_at", "expires_at",
                  "age_seconds", "time_to_expire_seconds", "expired"):
            self.assertIn(k, entry)
        self.assertEqual(entry["context_id"], "a")
        self.assertEqual(entry["operation"], "WORK_CREATE")
        self.assertIs(entry["expired"], False)

    def test_list_limited_to_10_by_default(self) -> None:
        from assistant_os.confirm_flow import readiness
        store = {f"ctx-{i:02d}": _make_stored("WORK_CREATE", age_seconds=i)
                 for i in range(25)}
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            result = readiness.get_confirm_flow_summary()
        self.assertEqual(result["pending_count"], 25)
        self.assertEqual(len(result["pending"]), 10,
                         "Compact list must be capped at 10 entries by default.")

    def test_list_sorted_oldest_first(self) -> None:
        from assistant_os.confirm_flow import readiness
        store = {
            "a": _make_stored("WORK_CREATE", age_seconds=10),
            "b": _make_stored("WORK_DELETE", age_seconds=300),
            "c": _make_stored("FIN_BATCH",   age_seconds=60),
        }
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            result = readiness.get_confirm_flow_summary()
        ages = [e["age_seconds"] for e in result["pending"]]
        self.assertEqual(ages, sorted(ages, reverse=True),
                         "Pending list must be sorted oldest-first (largest age first).")

    def test_expired_entries_marked(self) -> None:
        from assistant_os.confirm_flow import readiness
        live = _make_stored("WORK_CREATE", age_seconds=5)
        expired = _make_stored("WORK_DELETE", age_seconds=10_000, ttl_seconds=10)
        store = {"l": live, "e": expired}
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            result = readiness.get_confirm_flow_summary()
        # Find the expired entry by id and verify the marker.
        emap = {e["context_id"]: e for e in result["pending"]}
        self.assertTrue(emap["e"]["expired"])
        self.assertFalse(emap["l"]["expired"])


# ---------------------------------------------------------------------------
# Fail-soft contract
# ---------------------------------------------------------------------------

class TestFailSoft(unittest.TestCase):

    def test_summary_never_raises_on_store_read_error(self) -> None:
        from assistant_os.confirm_flow import readiness
        with patch.object(readiness, "_read_store_snapshot",
                          side_effect=RuntimeError("disk on fire")):
            result = readiness.get_confirm_flow_summary()
        self.assertIsInstance(result, dict)
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(result["pending"], [])
        self.assertIn("error", result)
        self.assertIn("disk on fire", result["error"])

    def test_summary_handles_malformed_entry_gracefully(self) -> None:
        from assistant_os.confirm_flow import readiness
        # Missing keys in stored entry shouldn't crash the producer.
        bad = {"plan": {}}  # no created_at, expires_at
        good = _make_stored("WORK_CREATE", age_seconds=5)
        store = {"bad": bad, "good": good}
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            result = readiness.get_confirm_flow_summary()
        self.assertEqual(result["pending_count"], 2)
        ids = [e["context_id"] for e in result["pending"]]
        self.assertIn("good", ids)


# ---------------------------------------------------------------------------
# list_pending_summary helper
# ---------------------------------------------------------------------------

class TestListPendingSummaryHelper(unittest.TestCase):

    def test_helper_respects_limit(self) -> None:
        from assistant_os.confirm_flow import readiness
        store = {f"c{i}": _make_stored("X", age_seconds=i) for i in range(20)}
        with patch.object(readiness, "_read_store_snapshot", return_value=(store, None)):
            entries = readiness.list_pending_summary(limit=5)
        self.assertEqual(len(entries), 5)
        for e in entries:
            self.assertNotIn("plan", e)
            self.assertNotIn("raw_text", e)


# ---------------------------------------------------------------------------
# Read-only invariants
# ---------------------------------------------------------------------------

class TestReadOnlyInvariants(unittest.TestCase):

    def test_does_not_call_remove_pending_plan(self) -> None:
        from assistant_os.confirm_flow import readiness
        from assistant_os import context_store
        with patch.object(context_store, "remove_pending_plan") as remove:
            readiness.get_confirm_flow_summary()
            remove.assert_not_called()

    def test_does_not_call_cleanup_expired(self) -> None:
        from assistant_os.confirm_flow import readiness
        from assistant_os import context_store
        with patch.object(context_store, "cleanup_expired") as cleanup:
            readiness.get_confirm_flow_summary()
            cleanup.assert_not_called()

    def test_does_not_call_store_pending_plan(self) -> None:
        from assistant_os.confirm_flow import readiness
        from assistant_os import context_store
        with patch.object(context_store, "store_pending_plan") as store:
            readiness.get_confirm_flow_summary()
            store.assert_not_called()

    def test_does_not_produce_authority_fields(self) -> None:
        from assistant_os.confirm_flow.readiness import get_confirm_flow_summary
        result = get_confirm_flow_summary()
        for forbidden in (
            "execution_mode",
            "effective_execution_mode",
            "governance_verdict",
            "policy_decision",
            "authorized",
            "approved",
            "ready_to_confirm",
            "safe_to_apply",
        ):
            self.assertNotIn(forbidden, result,
                             f"Confirm flow summary leaked authority field: {forbidden}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
