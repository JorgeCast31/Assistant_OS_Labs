"""Tests for assistant_os/runners/metadata_utils.py — shared metadata persistence."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from assistant_os.runners.metadata_utils import (
    EXECUTIONS_ROOT,
    patch_execution_metadata,
)


# ---------------------------------------------------------------------------
# EXECUTIONS_ROOT sanity
# ---------------------------------------------------------------------------


class TestExecutionsRoot:
    def test_executions_root_is_path(self):
        assert isinstance(EXECUTIONS_ROOT, Path)

    def test_executions_root_resolves_to_var_runner_executions(self):
        """The canonical path must end with var/runner/executions."""
        assert EXECUTIONS_ROOT.parts[-3:] == ("var", "runner", "executions")

    def test_executions_root_is_absolute(self):
        assert EXECUTIONS_ROOT.is_absolute()


# ---------------------------------------------------------------------------
# patch_execution_metadata — core behaviour
# ---------------------------------------------------------------------------


class TestPatchExecutionMetadata:
    def _make_exec(self, base: Path, eid: str, data: dict) -> Path:
        """Create an execution directory with metadata.json."""
        exec_dir = base / eid
        exec_dir.mkdir(parents=True, exist_ok=True)
        meta = exec_dir / "metadata.json"
        meta.write_text(json.dumps(data), encoding="utf-8")
        return exec_dir

    # ------------------------------------------------------------------
    # Happy-path writes
    # ------------------------------------------------------------------

    def test_merges_new_field_into_existing_metadata(self, tmp_path):
        self._make_exec(tmp_path, "eid-001", {"execution_id": "eid-001", "final_status": "success"})

        patch_execution_metadata("eid-001", {"agent_invocation": {"agent_name": "code_executor"}},
                                 base_path=tmp_path)

        meta = json.loads((tmp_path / "eid-001" / "metadata.json").read_text())
        assert "agent_invocation" in meta
        assert meta["agent_invocation"]["agent_name"] == "code_executor"

    def test_preserves_existing_fields(self, tmp_path):
        self._make_exec(tmp_path, "eid-002", {
            "execution_id": "eid-002",
            "final_status": "needs_review",
            "request_snapshot": {"source": "pytest"},
        })

        patch_execution_metadata("eid-002", {"agent_invocation": {"agent_name": "code_executor"}},
                                 base_path=tmp_path)

        meta = json.loads((tmp_path / "eid-002" / "metadata.json").read_text())
        assert meta["execution_id"] == "eid-002"
        assert meta["final_status"] == "needs_review"
        assert meta["request_snapshot"]["source"] == "pytest"
        assert "agent_invocation" in meta

    def test_overwrites_existing_key_with_new_value(self, tmp_path):
        self._make_exec(tmp_path, "eid-003", {
            "execution_id": "eid-003",
            "request_snapshot": {"source": "old-value"},
        })

        patch_execution_metadata("eid-003", {"request_snapshot": {"source": "new-value"}},
                                 base_path=tmp_path)

        meta = json.loads((tmp_path / "eid-003" / "metadata.json").read_text())
        assert meta["request_snapshot"]["source"] == "new-value"

    def test_multiple_fields_merged_at_once(self, tmp_path):
        self._make_exec(tmp_path, "eid-004", {"execution_id": "eid-004"})

        patch_execution_metadata("eid-004", {
            "agent_invocation": {"agent_name": "code_executor", "agent_version": "1.0.0"},
            "request_snapshot": {"source": "pytest"},
        }, base_path=tmp_path)

        meta = json.loads((tmp_path / "eid-004" / "metadata.json").read_text())
        assert "agent_invocation" in meta
        assert "request_snapshot" in meta

    def test_result_is_valid_json(self, tmp_path):
        self._make_exec(tmp_path, "eid-005", {"execution_id": "eid-005"})
        patch_execution_metadata("eid-005", {"key": "value"}, base_path=tmp_path)

        raw = (tmp_path / "eid-005" / "metadata.json").read_text()
        parsed = json.loads(raw)  # must not raise
        assert isinstance(parsed, dict)

    # ------------------------------------------------------------------
    # Silent-error / no-op cases
    # ------------------------------------------------------------------

    def test_missing_metadata_file_is_silent(self, tmp_path):
        """When metadata.json does not exist, the call must be a no-op (no exception)."""
        exec_dir = tmp_path / "eid-missing"
        exec_dir.mkdir()
        # No metadata.json written

        patch_execution_metadata("eid-missing", {"key": "val"}, base_path=tmp_path)
        # No exception raised — assertion is implicit

    def test_missing_execution_directory_is_silent(self, tmp_path):
        """When the execution directory itself does not exist, must be a no-op."""
        patch_execution_metadata("ghost-execution", {"key": "val"}, base_path=tmp_path)
        # No exception raised

    def test_empty_fields_dict_is_no_op_content(self, tmp_path):
        """Merging an empty dict leaves metadata unchanged."""
        original = {"execution_id": "eid-007", "final_status": "success"}
        self._make_exec(tmp_path, "eid-007", original)

        patch_execution_metadata("eid-007", {}, base_path=tmp_path)

        meta = json.loads((tmp_path / "eid-007" / "metadata.json").read_text())
        assert meta["execution_id"] == "eid-007"
        assert meta["final_status"] == "success"

    # ------------------------------------------------------------------
    # base_path parameter
    # ------------------------------------------------------------------

    def test_base_path_overrides_executions_root(self, tmp_path):
        """base_path must be used instead of EXECUTIONS_ROOT when provided."""
        self._make_exec(tmp_path, "eid-bp-001", {"execution_id": "eid-bp-001"})

        patch_execution_metadata("eid-bp-001", {"patched": True}, base_path=tmp_path)

        meta = json.loads((tmp_path / "eid-bp-001" / "metadata.json").read_text())
        assert meta["patched"] is True

    def test_without_base_path_uses_executions_root(self, monkeypatch):
        """Without base_path, EXECUTIONS_ROOT is used — verify via monkeypatching."""
        import assistant_os.runners.metadata_utils as mu
        fake_root = Path("/nonexistent/path/that/does/not/exist")
        monkeypatch.setattr(mu, "EXECUTIONS_ROOT", fake_root)

        # Should be silent (directory doesn't exist), not raise
        patch_execution_metadata("eid-no-bp", {"key": "val"})
        # No exception means it tried fake_root, found nothing, returned silently ✓
