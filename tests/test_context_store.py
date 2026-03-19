"""
Tests for context_store.py — persistent pending-plan store.

Covers:
- Basic store / retrieve / remove cycle
- Missing context_id → None (no KeyError)
- Expired context_id → None + automatic cleanup
- Disk persistence across simulated server restart
- Corruption recovery (invalid JSON → empty store, no crash)
- cleanup_expired() removes only expired entries
- Store size tracking
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import assistant_os.context_store as cs
from assistant_os.contracts import make_plan, ACTION_WORK_CREATE, RISK_MEDIUM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan():
    return make_plan(
        domain="WORK",
        action=ACTION_WORK_CREATE,
        target="Test task",
        risk_level=RISK_MEDIUM,
    )


def _force_expire(ctx_id: str) -> None:
    """Set expires_at to 1 second in the past for ctx_id in the live store."""
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with cs._lock:
        cs._store[ctx_id]["expires_at"] = past


# ---------------------------------------------------------------------------
# Base class: redirects CONTEXT_STORE_FILE to a tmp dir and clears store
# ---------------------------------------------------------------------------

class ContextStoreTestBase(unittest.TestCase):
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
        for f in [self.temp_file, self.temp_file.with_suffix(".tmp")]:
            if f.exists():
                f.unlink()


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

class TestContextStoreBasic(ContextStoreTestBase):
    def test_store_and_retrieve(self):
        plan = _make_plan()
        ctx_id = "ctx-basic-001"
        cs.store_pending_plan(ctx_id, plan, "WORK_CREATE", "crear tarea X")

        stored = cs.get_pending_plan(ctx_id)

        self.assertIsNotNone(stored)
        self.assertEqual(stored["operation"], "WORK_CREATE")
        self.assertEqual(stored["raw_text"], "crear tarea X")
        self.assertIn("plan", stored)
        self.assertIn("expires_at", stored)
        self.assertIn("created_at", stored)

    def test_store_returns_context_id(self):
        plan = _make_plan()
        ctx_id = "ctx-return-001"
        returned = cs.store_pending_plan(ctx_id, plan, "WORK_CREATE")
        self.assertEqual(returned, ctx_id)

    def test_missing_context_returns_none(self):
        result = cs.get_pending_plan("nonexistent-ctx-xyz")
        self.assertIsNone(result)

    def test_remove_returns_true_when_found(self):
        plan = _make_plan()
        ctx_id = "ctx-remove-001"
        cs.store_pending_plan(ctx_id, plan, "WORK_CREATE")

        result = cs.remove_pending_plan(ctx_id)

        self.assertTrue(result)
        self.assertIsNone(cs.get_pending_plan(ctx_id))

    def test_remove_returns_false_when_not_found(self):
        result = cs.remove_pending_plan("nonexistent-remove-xyz")
        self.assertFalse(result)

    def test_get_store_size(self):
        self.assertEqual(cs.get_store_size(), 0)
        cs.store_pending_plan("ctx-size-001", _make_plan(), "WORK_CREATE")
        cs.store_pending_plan("ctx-size-002", _make_plan(), "WORK_CREATE")
        self.assertEqual(cs.get_store_size(), 2)

    def test_clear_store(self):
        cs.store_pending_plan("ctx-clear-001", _make_plan(), "WORK_CREATE")
        cs.store_pending_plan("ctx-clear-002", _make_plan(), "WORK_CREATE")
        count = cs.clear_store()
        self.assertEqual(count, 2)
        self.assertEqual(cs.get_store_size(), 0)


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

class TestContextStoreExpiry(ContextStoreTestBase):
    def test_expired_context_returns_none(self):
        plan = _make_plan()
        ctx_id = "ctx-expired-001"
        cs.store_pending_plan(ctx_id, plan, "WORK_CREATE")
        _force_expire(ctx_id)

        result = cs.get_pending_plan(ctx_id)

        self.assertIsNone(result)

    def test_expired_context_is_removed_from_store(self):
        plan = _make_plan()
        ctx_id = "ctx-expired-cleanup"
        cs.store_pending_plan(ctx_id, plan, "WORK_CREATE")
        _force_expire(ctx_id)

        cs.get_pending_plan(ctx_id)  # triggers cleanup

        with cs._lock:
            self.assertNotIn(ctx_id, cs._store)

    def test_cleanup_expired_removes_only_expired(self):
        plan = _make_plan()
        cs.store_pending_plan("ctx-live", plan, "WORK_CREATE")
        cs.store_pending_plan("ctx-dead", plan, "WORK_CREATE")
        _force_expire("ctx-dead")

        removed = cs.cleanup_expired()

        self.assertEqual(removed, 1)
        self.assertIsNotNone(cs.get_pending_plan("ctx-live"))
        with cs._lock:
            self.assertNotIn("ctx-dead", cs._store)

    def test_cleanup_expired_returns_zero_when_nothing_expired(self):
        cs.store_pending_plan("ctx-fresh", _make_plan(), "WORK_CREATE")
        removed = cs.cleanup_expired()
        self.assertEqual(removed, 0)


# ---------------------------------------------------------------------------
# Disk persistence
# ---------------------------------------------------------------------------

class TestContextStorePersistence(ContextStoreTestBase):
    def test_store_writes_to_disk(self):
        ctx_id = "ctx-disk-001"
        cs.store_pending_plan(ctx_id, _make_plan(), "WORK_CREATE", "tarea persistida")

        self.assertTrue(self.temp_file.exists())
        raw = json.loads(self.temp_file.read_text(encoding="utf-8"))
        self.assertIn(ctx_id, raw)
        self.assertEqual(raw[ctx_id]["raw_text"], "tarea persistida")

    def test_remove_updates_disk(self):
        ctx_id = "ctx-disk-remove"
        cs.store_pending_plan(ctx_id, _make_plan(), "WORK_CREATE")
        cs.remove_pending_plan(ctx_id)

        raw = json.loads(self.temp_file.read_text(encoding="utf-8"))
        self.assertNotIn(ctx_id, raw)

    def test_data_survives_simulated_restart(self):
        """Simulate restart: write to disk, clear in-memory, reload from disk."""
        ctx_id = "ctx-restart-001"
        cs.store_pending_plan(ctx_id, _make_plan(), "WORK_CREATE", "tarea persistida")

        # Simulate restart: wipe in-memory store
        with cs._lock:
            cs._store.clear()

        # Reload from disk (as the module initializer does on startup)
        reloaded = cs._load_store_from_disk()

        self.assertIn(ctx_id, reloaded)
        self.assertEqual(reloaded[ctx_id]["raw_text"], "tarea persistida")

    def test_missing_file_returns_empty_on_load(self):
        # Ensure file doesn't exist
        if self.temp_file.exists():
            self.temp_file.unlink()

        result = cs._load_store_from_disk()

        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# Corruption recovery
# ---------------------------------------------------------------------------

class TestContextStoreCorruptionRecovery(ContextStoreTestBase):
    def test_corrupted_json_returns_empty(self):
        self.temp_file.parent.mkdir(parents=True, exist_ok=True)
        self.temp_file.write_text("{ this is not valid JSON !!!", encoding="utf-8")

        result = cs._load_store_from_disk()

        self.assertEqual(result, {})

    def test_wrong_root_type_returns_empty(self):
        """JSON array at root instead of object → safe fallback."""
        self.temp_file.parent.mkdir(parents=True, exist_ok=True)
        self.temp_file.write_text('["item1", "item2"]', encoding="utf-8")

        result = cs._load_store_from_disk()

        self.assertEqual(result, {})

    def test_corrupted_json_logs_warning(self):
        self.temp_file.parent.mkdir(parents=True, exist_ok=True)
        self.temp_file.write_text("{ bad json", encoding="utf-8")

        with self.assertLogs("assistant_os.context_store", level="WARNING") as cm:
            cs._load_store_from_disk()

        self.assertTrue(any("could not be loaded" in msg for msg in cm.output))

    def test_server_continues_cleanly_after_corruption(self):
        """After corruption recovery, new plans can be stored normally."""
        self.temp_file.parent.mkdir(parents=True, exist_ok=True)
        self.temp_file.write_text("CORRUPT", encoding="utf-8")

        # Reload (simulates startup)
        with cs._lock:
            cs._store.clear()
        loaded = cs._load_store_from_disk()
        with cs._lock:
            cs._store.update(loaded)

        # Normal operation should work
        cs.store_pending_plan("ctx-after-corrupt", _make_plan(), "WORK_CREATE")
        stored = cs.get_pending_plan("ctx-after-corrupt")
        self.assertIsNotNone(stored)


if __name__ == "__main__":
    unittest.main()
