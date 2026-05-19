"""Tests for ApplyEngine — Slice 2."""

import json
from pathlib import Path

import pytest

from assistant_os.runners.apply_engine import ApplyEngine
from assistant_os.runners.errors import ApplyError
from assistant_os.runners.runner_models import RunnerExecutionRequest, RunnerExecutionStatus
from assistant_os.runners.runner_service import RunnerService
from tests.runners.conftest import make_authorized_plan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    """Minimal workspace directory with a couple of existing files."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "app.py").write_text("x = 1\n")
    (ws / "README.md").write_text("# Hello\n")
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
    (repo / "main.py").write_text("pass\n")
    return repo


# ---------------------------------------------------------------------------
# file_replace — basic
# ---------------------------------------------------------------------------


def test_file_replace_creates_new_file(engine, workspace, log_file):
    changes = [{"op": "file_replace", "path": "new_module.py", "content": "print('hi')\n"}]
    modified = engine.apply_changes(workspace, changes, log_file)

    assert "new_module.py" in modified
    assert (workspace / "new_module.py").read_text() == "print('hi')\n"


def test_file_replace_overwrites_existing_file(engine, workspace, log_file):
    changes = [{"op": "file_replace", "path": "app.py", "content": "x = 99\n"}]
    modified = engine.apply_changes(workspace, changes, log_file)

    assert "app.py" in modified
    assert (workspace / "app.py").read_text() == "x = 99\n"


def test_file_replace_creates_intermediate_directories(engine, workspace, log_file):
    changes = [{"op": "file_replace", "path": "pkg/sub/util.py", "content": "# util\n"}]
    modified = engine.apply_changes(workspace, changes, log_file)

    assert "pkg/sub/util.py" in modified
    assert (workspace / "pkg" / "sub" / "util.py").read_text() == "# util\n"


def test_file_replace_empty_content(engine, workspace, log_file):
    """Empty string content is valid — creates an empty file."""
    changes = [{"op": "file_replace", "path": "empty.py", "content": ""}]
    modified = engine.apply_changes(workspace, changes, log_file)

    assert "empty.py" in modified
    assert (workspace / "empty.py").read_text() == ""


def test_multiple_changes_in_order(engine, workspace, log_file):
    changes = [
        {"op": "file_replace", "path": "a.py", "content": "a = 1\n"},
        {"op": "file_replace", "path": "b.py", "content": "b = 2\n"},
    ]
    modified = engine.apply_changes(workspace, changes, log_file)

    assert modified == ["a.py", "b.py"]
    assert (workspace / "a.py").read_text() == "a = 1\n"
    assert (workspace / "b.py").read_text() == "b = 2\n"


# ---------------------------------------------------------------------------
# patch — real implementation (M2D)
# ---------------------------------------------------------------------------


def test_patch_invalid_no_hunks_raises_apply_error(engine, workspace, log_file):
    """A patch string with no @@ headers is rejected with a structured error."""
    changes = [{"op": "patch", "path": "app.py", "patch": "this is not a valid diff"}]
    with pytest.raises(ApplyError, match="no valid hunks"):
        engine.apply_changes(workspace, changes, log_file)


def test_patch_file_not_found_raises_apply_error(engine, workspace, log_file):
    """Patching a file that does not exist raises ApplyError immediately."""
    valid_patch = "@@ -1,1 +1,1 @@\n-x = 1\n+x = 99\n"
    changes = [{"op": "patch", "path": "nonexistent.py", "patch": valid_patch}]
    with pytest.raises(ApplyError, match="does not exist"):
        engine.apply_changes(workspace, changes, log_file)


def test_patch_empty_patch_field_raises_apply_error(engine, workspace, log_file):
    """An empty 'patch' field is rejected with a structured error."""
    changes = [{"op": "patch", "path": "app.py", "patch": ""}]
    with pytest.raises(ApplyError):
        engine.apply_changes(workspace, changes, log_file)


def test_patch_applies_valid_unified_diff(engine, workspace, log_file):
    """A well-formed unified diff is applied and the file is updated."""
    # workspace fixture has app.py with content "x = 1\n"
    patch_text = "@@ -1,1 +1,1 @@\n-x = 1\n+x = 99\n"
    changes = [{"op": "patch", "path": "app.py", "patch": patch_text}]
    modified = engine.apply_changes(workspace, changes, log_file)

    assert "app.py" in modified
    assert (workspace / "app.py").read_text() == "x = 99\n"


def test_patch_logged_as_patch_event(engine, workspace, log_file):
    """Successful patch is logged with 'apply: patch' event."""
    patch_text = "@@ -1,1 +1,1 @@\n-x = 1\n+x = 42\n"
    changes = [{"op": "patch", "path": "app.py", "patch": patch_text}]
    engine.apply_changes(workspace, changes, log_file)

    content = log_file.read_text()
    assert "apply: patch" in content


# ---------------------------------------------------------------------------
# Security — path traversal
# ---------------------------------------------------------------------------


def test_path_traversal_blocked(engine, workspace, log_file):
    changes = [{"op": "file_replace", "path": "../../etc/passwd", "content": "evil"}]
    with pytest.raises(ApplyError, match="traversal"):
        engine.apply_changes(workspace, changes, log_file)


def test_path_traversal_blocked_nested(engine, workspace, log_file):
    changes = [{"op": "file_replace", "path": "sub/../../../outside.py", "content": "evil"}]
    with pytest.raises(ApplyError, match="traversal"):
        engine.apply_changes(workspace, changes, log_file)


def test_empty_path_rejected(engine, workspace, log_file):
    changes = [{"op": "file_replace", "path": "", "content": "x"}]
    with pytest.raises(ApplyError, match="must not be empty"):
        engine.apply_changes(workspace, changes, log_file)


def test_unknown_op_raises(engine, workspace, log_file):
    changes = [{"op": "delete", "path": "app.py"}]
    with pytest.raises(ApplyError, match="Unknown op"):
        engine.apply_changes(workspace, changes, log_file)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def test_log_contains_apply_start_and_done(engine, workspace, log_file):
    changes = [{"op": "file_replace", "path": "x.py", "content": ""}]
    engine.apply_changes(workspace, changes, log_file)

    content = log_file.read_text()
    assert "apply: start" in content
    assert "apply: done" in content


def test_log_contains_file_replace_event(engine, workspace, log_file):
    changes = [{"op": "file_replace", "path": "x.py", "content": ""}]
    engine.apply_changes(workspace, changes, log_file)

    content = log_file.read_text()
    assert "file_replace" in content


# ---------------------------------------------------------------------------
# RunnerService integration
# ---------------------------------------------------------------------------


def test_runner_service_applies_changes(sample_repo):
    service = RunnerService()
    request = RunnerExecutionRequest(
        execution_id="s2-apply-001",
        repo_path=str(sample_repo),
        changes=[
            {"op": "file_replace", "path": "generated.py", "content": "result = 42\n"},
        ],
        authorized_plan=make_authorized_plan("s2-apply-001"),
    )
    result = service.run(request)

    assert result.status == RunnerExecutionStatus.CHANGES_APPLIED
    assert "generated.py" in result.modified_files
    workspace = Path(result.workspace_path)
    assert (workspace / "generated.py").read_text() == "result = 42\n"


def test_runner_service_no_changes_stays_workspace_ready(sample_repo):
    service = RunnerService()
    request = RunnerExecutionRequest(
        execution_id="s2-noop-001",
        repo_path=str(sample_repo),
        changes=None,
        authorized_plan=make_authorized_plan("s2-noop-001"),
    )
    result = service.run(request)

    assert result.status == RunnerExecutionStatus.WORKSPACE_READY
    assert result.modified_files == []


def test_runner_service_apply_failure_returns_failed(sample_repo):
    service = RunnerService()
    request = RunnerExecutionRequest(
        execution_id="s2-fail-001",
        repo_path=str(sample_repo),
        changes=[
            {"op": "file_replace", "path": "../../escape.py", "content": "evil"},
        ],
    )
    result = service.run(request)

    assert result.status == RunnerExecutionStatus.FAILED
    assert result.error is not None


def test_runner_service_modified_files_in_metadata(sample_repo):
    service = RunnerService()
    request = RunnerExecutionRequest(
        execution_id="s2-meta-001",
        repo_path=str(sample_repo),
        changes=[{"op": "file_replace", "path": "out.py", "content": "x = 1\n"}],
        authorized_plan=make_authorized_plan("s2-meta-001"),
    )
    result = service.run(request)

    metadata = json.loads((Path(result.artifacts_path) / "metadata.json").read_text())
    assert "modified_files" in metadata
    assert "out.py" in metadata["modified_files"]


def test_runner_service_apply_phases_logged(sample_repo):
    service = RunnerService()
    request = RunnerExecutionRequest(
        execution_id="s2-log-001",
        repo_path=str(sample_repo),
        changes=[{"op": "file_replace", "path": "t.py", "content": ""}],
        authorized_plan=make_authorized_plan("s2-log-001"),
    )
    result = service.run(request)

    log = (Path(result.artifacts_path) / "runner.log").read_text()
    assert "phase: APPLY_START" in log
    assert "phase: APPLY_DONE" in log


# ---------------------------------------------------------------------------
# Fix 4: modified_files normalization (pre-Slice-4 hardening)
# ---------------------------------------------------------------------------


def test_modified_files_normalized_for_simple_path(engine, workspace, log_file):
    """A clean relative path is returned as-is (posix form)."""
    changes = [{"op": "file_replace", "path": "sub/utils.py", "content": "x = 1\n"}]
    modified = engine.apply_changes(workspace, changes, log_file)

    assert modified == ["sub/utils.py"]


def test_modified_files_normalized_redundant_traversal(engine, workspace, log_file):
    """foo/../bar.py input must be recorded as bar.py, not the raw input string."""
    changes = [{"op": "file_replace", "path": "subdir/../utils.py", "content": "x = 1\n"}]
    modified = engine.apply_changes(workspace, changes, log_file)

    assert "utils.py" in modified
    assert "subdir/../utils.py" not in modified
    assert (workspace / "utils.py").read_text() == "x = 1\n"


def test_modified_files_normalized_nested_traversal(engine, workspace, log_file):
    """a/b/../../c.py must normalize to c.py."""
    changes = [{"op": "file_replace", "path": "a/b/../../c.py", "content": ""}]
    modified = engine.apply_changes(workspace, changes, log_file)

    assert modified == ["c.py"]
    assert (workspace / "c.py").exists()
