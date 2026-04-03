"""
M2D — Execution Hardening Tests

Validates all M2D hardening scenarios:
  1. Valid patch applied correctly
  2. Invalid patch format raises structured error
  3. Audit entry generated correctly (path, operation, before/after hash, diff)
  4. before_hash / after_hash correctness
  5. Multiple files in single apply
  6. Patch op — file must exist pre-gate
  7. Empty patch field rejected at preflight
  8. changes_detail surfaced in DomainResult.data
  9. Preflight rejects unknown op before workspace creation
"""

from __future__ import annotations

import hashlib

import pytest

from assistant_os.runners.apply_engine import (
    ApplyEngine,
    _apply_unified_diff,
    _compute_hash,
    _make_diff,
)
from assistant_os.runners.errors import ApplyError, PreflightError
from assistant_os.runners.runner_models import RunnerExecutionRequest
from assistant_os.runners.runner_service import RunnerService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "app.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
    (ws / "utils.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    return ws


@pytest.fixture
def log_file(tmp_path):
    lf = tmp_path / "runner.log"
    lf.write_text("")
    return lf


@pytest.fixture
def engine():
    return ApplyEngine()


@pytest.fixture
def sample_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
    (repo / "utils.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------
# Scenario 1: Valid patch applied correctly
# ---------------------------------------------------------------------------


class TestValidPatchApplied:
    """A well-formed unified diff is applied and the result is correct."""

    def test_single_line_replacement(self, engine, workspace, log_file):
        """Replace one line in a 3-line file."""
        patch = "@@ -2,1 +2,1 @@\n-y = 2\n+y = 99\n"
        changes = [{"op": "patch", "path": "app.py", "patch": patch}]
        modified = engine.apply_changes(workspace, changes, log_file)

        assert "app.py" in modified
        assert (workspace / "app.py").read_text(encoding="utf-8") == "x = 1\ny = 99\nz = 3\n"

    def test_multi_line_hunk(self, engine, workspace, log_file):
        """Replace two lines with context lines."""
        patch = "@@ -1,3 +1,3 @@\n x = 1\n-y = 2\n+y = 99\n z = 3\n"
        changes = [{"op": "patch", "path": "app.py", "patch": patch}]
        modified = engine.apply_changes(workspace, changes, log_file)

        assert "app.py" in modified
        content = (workspace / "app.py").read_text(encoding="utf-8")
        assert "y = 99" in content
        assert "y = 2" not in content

    def test_add_lines_to_file(self, engine, workspace, log_file):
        """Append a new line using a patch."""
        patch = "@@ -3,1 +3,2 @@\n z = 3\n+w = 4\n"
        changes = [{"op": "patch", "path": "app.py", "patch": patch}]
        modified = engine.apply_changes(workspace, changes, log_file)

        assert "app.py" in modified
        content = (workspace / "app.py").read_text(encoding="utf-8")
        assert "w = 4" in content

    def test_patch_returns_file_in_modified_list(self, engine, workspace, log_file):
        """Patched file appears in the returned modified list."""
        patch = "@@ -1,1 +1,1 @@\n-x = 1\n+x = 0\n"
        changes = [{"op": "patch", "path": "app.py", "patch": patch}]
        modified = engine.apply_changes(workspace, changes, log_file)
        assert modified == ["app.py"]


# ---------------------------------------------------------------------------
# Scenario 2: Invalid patch format raises structured error
# ---------------------------------------------------------------------------


class TestInvalidPatchRaisesError:
    """Malformed or inapplicable patches raise ApplyError — no silent skip."""

    def test_no_hunk_headers_raises(self, engine, workspace, log_file):
        """Patch text with no @@ headers is rejected with a clear error."""
        changes = [{"op": "patch", "path": "app.py", "patch": "not a diff at all"}]
        with pytest.raises(ApplyError, match="no valid hunks"):
            engine.apply_changes(workspace, changes, log_file)

    def test_empty_patch_raises(self, engine, workspace, log_file):
        """Empty 'patch' field raises ApplyError before any I/O."""
        changes = [{"op": "patch", "path": "app.py", "patch": ""}]
        with pytest.raises(ApplyError):
            engine.apply_changes(workspace, changes, log_file)

    def test_hunk_out_of_bounds_raises(self, engine, workspace, log_file):
        """A hunk that references a line beyond the file length is rejected."""
        # app.py has 3 lines; this patch tries to start at line 100
        patch = "@@ -100,1 +100,1 @@\n-nonexistent line\n+replacement\n"
        changes = [{"op": "patch", "path": "app.py", "patch": patch}]
        with pytest.raises(ApplyError, match="cannot be applied"):
            engine.apply_changes(workspace, changes, log_file)

    def test_file_not_found_raises(self, engine, workspace, log_file):
        """Patching a nonexistent file raises ApplyError before calling _apply_unified_diff."""
        patch = "@@ -1,1 +1,1 @@\n-x\n+y\n"
        changes = [{"op": "patch", "path": "missing.py", "patch": patch}]
        with pytest.raises(ApplyError, match="does not exist"):
            engine.apply_changes(workspace, changes, log_file)

    def test_whitespace_only_patch_raises(self, engine, workspace, log_file):
        """A patch of only whitespace is treated as empty and rejected."""
        changes = [{"op": "patch", "path": "app.py", "patch": "   \n  \n"}]
        with pytest.raises(ApplyError):
            engine.apply_changes(workspace, changes, log_file)


# ---------------------------------------------------------------------------
# Scenario 3: Audit entry generated correctly
# ---------------------------------------------------------------------------


class TestAuditGenerated:
    """apply_changes_with_audit returns correct audit entries."""

    def test_audit_entry_present_for_file_replace(self, engine, workspace, log_file):
        """file_replace op produces an audit entry with required keys."""
        changes = [{"op": "file_replace", "path": "app.py", "content": "x = 99\n"}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        assert len(audit) == 1
        entry = audit[0]
        for key in ("path", "operation", "before_hash", "after_hash", "diff"):
            assert key in entry, f"audit entry missing key {key!r}"

    def test_audit_entry_present_for_patch(self, engine, workspace, log_file):
        """patch op also produces an audit entry with required keys."""
        patch = "@@ -1,1 +1,1 @@\n-x = 1\n+x = 99\n"
        changes = [{"op": "patch", "path": "app.py", "patch": patch}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        assert len(audit) == 1
        entry = audit[0]
        assert entry["operation"] == "patch"
        for key in ("path", "operation", "before_hash", "after_hash", "diff"):
            assert key in entry

    def test_audit_path_is_normalized(self, engine, workspace, log_file):
        """Audit path matches the normalized relative posix path."""
        changes = [{"op": "file_replace", "path": "app.py", "content": "x = 0\n"}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)
        assert audit[0]["path"] == "app.py"

    def test_audit_diff_is_non_empty_when_content_changes(self, engine, workspace, log_file):
        """Audit diff is non-empty when before != after."""
        changes = [{"op": "file_replace", "path": "app.py", "content": "x = 999\n"}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)
        assert audit[0]["diff"] != "", "diff must be non-empty when content changes"

    def test_audit_diff_empty_when_content_unchanged(self, engine, workspace, log_file):
        """Audit diff is empty when before == after (idempotent write)."""
        original = (workspace / "app.py").read_text(encoding="utf-8")
        changes = [{"op": "file_replace", "path": "app.py", "content": original}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)
        assert audit[0]["diff"] == "", "diff must be empty when content is identical"


# ---------------------------------------------------------------------------
# Scenario 4: before_hash / after_hash correctness
# ---------------------------------------------------------------------------


class TestHashCorrectness:
    """before_hash and after_hash are SHA-256 of the respective content."""

    def test_before_hash_matches_original_content(self, engine, workspace, log_file):
        """before_hash == SHA-256 of original file content."""
        original = (workspace / "app.py").read_text(encoding="utf-8")
        expected_before = hashlib.sha256(original.encode("utf-8")).hexdigest()

        changes = [{"op": "file_replace", "path": "app.py", "content": "x = 999\n"}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        assert audit[0]["before_hash"] == expected_before

    def test_after_hash_matches_new_content(self, engine, workspace, log_file):
        """after_hash == SHA-256 of new content."""
        new_content = "x = 999\n"
        expected_after = hashlib.sha256(new_content.encode("utf-8")).hexdigest()

        changes = [{"op": "file_replace", "path": "app.py", "content": new_content}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        assert audit[0]["after_hash"] == expected_after

    def test_before_hash_for_new_file_is_empty_string_hash(self, engine, workspace, log_file):
        """When file doesn't exist yet, before_hash is SHA-256 of empty string."""
        expected_before = hashlib.sha256(b"").hexdigest()
        changes = [{"op": "file_replace", "path": "new_file.py", "content": "print('hi')\n"}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        assert audit[0]["before_hash"] == expected_before

    def test_before_after_different_when_content_changes(self, engine, workspace, log_file):
        """before_hash != after_hash when content is modified."""
        changes = [{"op": "file_replace", "path": "app.py", "content": "completely different\n"}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        assert audit[0]["before_hash"] != audit[0]["after_hash"]

    def test_before_after_equal_when_idempotent(self, engine, workspace, log_file):
        """before_hash == after_hash when content is unchanged (idempotent write)."""
        original = (workspace / "app.py").read_text(encoding="utf-8")
        changes = [{"op": "file_replace", "path": "app.py", "content": original}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        assert audit[0]["before_hash"] == audit[0]["after_hash"]

    def test_patch_before_hash_matches_original(self, engine, workspace, log_file):
        """For patch op, before_hash matches the file content before patching."""
        original = (workspace / "app.py").read_text(encoding="utf-8")
        expected_before = hashlib.sha256(original.encode("utf-8")).hexdigest()

        patch = "@@ -1,1 +1,1 @@\n-x = 1\n+x = 99\n"
        changes = [{"op": "patch", "path": "app.py", "patch": patch}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        assert audit[0]["before_hash"] == expected_before

    def test_patch_after_hash_matches_patched_content(self, engine, workspace, log_file):
        """For patch op, after_hash matches the file content after patching."""
        patch = "@@ -1,1 +1,1 @@\n-x = 1\n+x = 99\n"
        changes = [{"op": "patch", "path": "app.py", "patch": patch}]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        patched_content = (workspace / "app.py").read_text(encoding="utf-8")
        expected_after = hashlib.sha256(patched_content.encode("utf-8")).hexdigest()
        assert audit[0]["after_hash"] == expected_after


# ---------------------------------------------------------------------------
# Scenario 5: Multiple files in a single apply
# ---------------------------------------------------------------------------


class TestMultipleFiles:
    """Multiple changes in one apply call produce one audit entry per file."""

    def test_two_file_replace_produces_two_audit_entries(self, engine, workspace, log_file):
        changes = [
            {"op": "file_replace", "path": "app.py", "content": "x = 1\n"},
            {"op": "file_replace", "path": "utils.py", "content": "# rewritten\n"},
        ]
        modified, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        assert len(modified) == 2
        assert len(audit) == 2
        paths = {e["path"] for e in audit}
        assert paths == {"app.py", "utils.py"}

    def test_mixed_ops_both_audited(self, engine, workspace, log_file):
        """file_replace + patch in the same apply both appear in audit."""
        patch = "@@ -1,1 +1,1 @@\n-x = 1\n+x = 0\n"
        changes = [
            {"op": "patch", "path": "app.py", "patch": patch},
            {"op": "file_replace", "path": "utils.py", "content": "# replaced\n"},
        ]
        modified, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        assert len(modified) == 2
        assert len(audit) == 2
        ops = {e["operation"] for e in audit}
        assert ops == {"patch", "file_replace"}

    def test_multiple_files_all_hashes_present(self, engine, workspace, log_file):
        """Every audit entry has before_hash and after_hash."""
        changes = [
            {"op": "file_replace", "path": "app.py", "content": "a\n"},
            {"op": "file_replace", "path": "utils.py", "content": "b\n"},
        ]
        _, audit = engine.apply_changes_with_audit(workspace, changes, log_file)

        for entry in audit:
            assert entry["before_hash"], f"missing before_hash for {entry['path']}"
            assert entry["after_hash"], f"missing after_hash for {entry['path']}"

    def test_failure_in_second_change_raises_apply_error(self, engine, workspace, log_file):
        """If the second change fails, ApplyError is raised (no partial success silenced)."""
        changes = [
            {"op": "file_replace", "path": "app.py", "content": "x = 0\n"},
            {"op": "patch", "path": "missing.py", "patch": "@@ -1,1 +1,1 @@\n-a\n+b\n"},
        ]
        with pytest.raises(ApplyError, match="does not exist"):
            engine.apply_changes_with_audit(workspace, changes, log_file)


# ---------------------------------------------------------------------------
# Scenario 6: Preflight validation (FASE 5 fast path)
# ---------------------------------------------------------------------------


class TestPreflightValidation:
    """RunnerService rejects invalid changes before workspace creation."""

    def test_unknown_op_fails_preflight(self, sample_repo):
        """An unknown op raises PreflightError — no workspace is created."""
        service = RunnerService()
        request = RunnerExecutionRequest(
            execution_id="m2d-preflight-001",
            repo_path=str(sample_repo),
            changes=[{"op": "delete", "path": "main.py"}],
        )
        result = service.run(request)
        # PreflightError → FAILED result, no workspace path
        assert result.final_status == "failed"
        assert result.workspace_path is None
        assert result.error is not None

    def test_empty_path_fails_preflight(self, sample_repo):
        """An empty path raises PreflightError."""
        service = RunnerService()
        request = RunnerExecutionRequest(
            execution_id="m2d-preflight-002",
            repo_path=str(sample_repo),
            changes=[{"op": "file_replace", "path": "", "content": "x"}],
        )
        result = service.run(request)
        assert result.final_status == "failed"
        assert result.workspace_path is None

    def test_absolute_path_fails_preflight(self, sample_repo):
        """An absolute path in changes raises PreflightError."""
        service = RunnerService()
        request = RunnerExecutionRequest(
            execution_id="m2d-preflight-003",
            repo_path=str(sample_repo),
            changes=[{"op": "file_replace", "path": "/etc/passwd", "content": "evil"}],
        )
        result = service.run(request)
        assert result.final_status == "failed"
        assert result.workspace_path is None

    def test_patch_with_empty_patch_field_fails_preflight(self, sample_repo):
        """A patch op with empty patch field fails preflight."""
        service = RunnerService()
        request = RunnerExecutionRequest(
            execution_id="m2d-preflight-004",
            repo_path=str(sample_repo),
            changes=[{"op": "patch", "path": "main.py", "patch": ""}],
        )
        result = service.run(request)
        assert result.final_status == "failed"
        assert result.workspace_path is None

    def test_valid_changes_pass_preflight(self, sample_repo):
        """Valid changes pass preflight and workspace is created."""
        service = RunnerService()
        request = RunnerExecutionRequest(
            execution_id="m2d-preflight-005",
            repo_path=str(sample_repo),
            changes=[{"op": "file_replace", "path": "out.py", "content": "x = 1\n"}],
        )
        result = service.run(request)
        # Workspace should have been created (workspace_path is set)
        assert result.workspace_path is not None


# ---------------------------------------------------------------------------
# Scenario 7: changes_detail in RunnerExecutionResult
# ---------------------------------------------------------------------------


class TestChangesDetailInResult:
    """RunnerService result contains changes_detail after apply."""

    def test_file_replace_changes_detail_present(self, sample_repo):
        """After a file_replace apply, changes_detail has one entry."""
        service = RunnerService()
        request = RunnerExecutionRequest(
            execution_id="m2d-detail-001",
            repo_path=str(sample_repo),
            changes=[{"op": "file_replace", "path": "main.py", "content": "x = 99\n"}],
        )
        result = service.run(request)

        assert result.changes_detail is not None
        assert len(result.changes_detail) == 1
        entry = result.changes_detail[0]
        assert entry["operation"] == "file_replace"
        assert "before_hash" in entry
        assert "after_hash" in entry

    def test_no_changes_detail_when_no_changes(self, sample_repo):
        """When no changes are applied, changes_detail is None."""
        service = RunnerService()
        request = RunnerExecutionRequest(
            execution_id="m2d-detail-002",
            repo_path=str(sample_repo),
            changes=None,
        )
        result = service.run(request)
        assert result.changes_detail is None

    def test_patch_changes_detail_present(self, sample_repo):
        """After a patch apply, changes_detail has one entry with operation='patch'."""
        service = RunnerService()
        # main.py has content "x = 1\ny = 2\nz = 3\n" from fixture
        patch_text = "@@ -1,1 +1,1 @@\n-x = 1\n+x = 42\n"
        request = RunnerExecutionRequest(
            execution_id="m2d-detail-003",
            repo_path=str(sample_repo),
            changes=[{"op": "patch", "path": "main.py", "patch": patch_text}],
        )
        result = service.run(request)

        assert result.changes_detail is not None
        assert result.changes_detail[0]["operation"] == "patch"


# ---------------------------------------------------------------------------
# Unit tests for module-level helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Unit tests for _compute_hash, _make_diff, _apply_unified_diff."""

    def test_compute_hash_empty_string(self):
        expected = hashlib.sha256(b"").hexdigest()
        assert _compute_hash("") == expected

    def test_compute_hash_consistent(self):
        content = "hello world\n"
        assert _compute_hash(content) == _compute_hash(content)

    def test_make_diff_empty_when_identical(self):
        content = "same\n"
        assert _make_diff(content, content, "file.py") == ""

    def test_make_diff_non_empty_when_different(self):
        assert _make_diff("a\n", "b\n", "file.py") != ""

    def test_apply_unified_diff_simple_replacement(self):
        original = "x = 1\ny = 2\nz = 3\n"
        patch = "@@ -2,1 +2,1 @@\n-y = 2\n+y = 99\n"
        result = _apply_unified_diff(original, patch)
        assert result == "x = 1\ny = 99\nz = 3\n"

    def test_apply_unified_diff_no_hunks_raises(self):
        with pytest.raises(ApplyError, match="no valid hunks"):
            _apply_unified_diff("content\n", "not a patch")

    def test_apply_unified_diff_out_of_bounds_raises(self):
        with pytest.raises(ApplyError, match="cannot be applied"):
            _apply_unified_diff("one line\n", "@@ -100,1 +100,1 @@\n-foo\n+bar\n")

    def test_apply_unified_diff_multiple_hunks(self):
        original = "a\nb\nc\nd\ne\n"
        patch = "@@ -1,1 +1,1 @@\n-a\n+A\n@@ -5,1 +5,1 @@\n-e\n+E\n"
        result = _apply_unified_diff(original, patch)
        assert result == "A\nb\nc\nd\nE\n"

    def test_apply_unified_diff_add_lines(self):
        original = "line1\nline2\n"
        patch = "@@ -2,1 +2,2 @@\n line2\n+line3\n"
        result = _apply_unified_diff(original, patch)
        assert result == "line1\nline2\nline3\n"
