"""Tests for workspace_manager — Slice 1 / pre-Slice-4 hardening."""

import json
from pathlib import Path

import pytest

from assistant_os.runners.errors import PolicyViolationError, WorkspacePreparationError
from assistant_os.runners.runner_models import RunnerExecutionRequest
from assistant_os.runners.workspace_manager import (
    PreparedWorkspace,
    cleanup_execution,
    prepare_workspace,
    _RUNNER_BASE,
)


@pytest.fixture
def sample_repo(tmp_path):
    """Create a minimal fake repo directory including a .git folder."""
    repo = tmp_path / "my_repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')")
    (repo / "README.md").write_text("# Test repo")
    # Simulate a real git repo — .git must NOT be copied to workspace
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    return repo


@pytest.fixture
def basic_request(sample_repo):
    return RunnerExecutionRequest(
        execution_id="test-exec-001",
        repo_path=str(sample_repo),
    )


def test_prepare_workspace_creates_directories(basic_request):
    result = prepare_workspace(basic_request)

    workspace = Path(result.workspace_path)
    artifacts = Path(result.artifacts_path)

    assert workspace.exists()
    assert workspace.is_dir()
    assert artifacts.exists()
    assert artifacts.is_dir()


def test_prepare_workspace_copies_repo(basic_request):
    result = prepare_workspace(basic_request)
    workspace = Path(result.workspace_path)

    assert (workspace / "main.py").exists()
    assert (workspace / "README.md").exists()


def test_prepare_workspace_creates_metadata_json(basic_request):
    result = prepare_workspace(basic_request)
    metadata_file = Path(result.artifacts_path) / "metadata.json"

    assert metadata_file.exists()
    data = json.loads(metadata_file.read_text())
    assert data["execution_id"] == basic_request.execution_id
    assert data["status"] == "RUNNING"
    assert data["started_at"] is not None


def test_prepare_workspace_creates_runner_log(basic_request):
    result = prepare_workspace(basic_request)
    log_file = Path(result.artifacts_path) / "runner.log"

    assert log_file.exists()
    content = log_file.read_text()
    assert "workspace" in content


def test_prepare_workspace_returns_prepared_workspace(basic_request):
    result = prepare_workspace(basic_request)
    assert isinstance(result, PreparedWorkspace)
    assert result.workspace_path.endswith("workspace")
    assert "test-exec-001" in result.artifacts_path


def test_prepare_workspace_nonexistent_repo():
    req = RunnerExecutionRequest(
        execution_id="test-exec-002",
        repo_path="/this/path/definitely/does/not/exist",
    )
    with pytest.raises(PolicyViolationError, match="does not exist"):
        prepare_workspace(req)


def test_prepare_workspace_excludes_git(basic_request):
    """The .git directory from the source repo must not appear in workspace/."""
    result = prepare_workspace(basic_request)
    workspace = Path(result.workspace_path)

    assert not (workspace / ".git").exists(), ".git must be excluded from workspace"


def test_prepare_workspace_log_has_multiple_entries(basic_request):
    """runner.log must contain more than one event after workspace preparation."""
    result = prepare_workspace(basic_request)
    log_file = Path(result.artifacts_path) / "runner.log"

    content = log_file.read_text()
    lines = [l for l in content.splitlines() if l.strip()]
    assert len(lines) >= 2, "runner.log should have at least 2 logged events"


def test_prepare_workspace_denied_repo(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    req = RunnerExecutionRequest(
        execution_id="test-exec-003",
        repo_path=str(git_dir),
    )
    with pytest.raises(PolicyViolationError, match="denied by policy"):
        prepare_workspace(req)


# ---------------------------------------------------------------------------
# Fix 5: cleanup_execution (pre-Slice-4 hardening)
# ---------------------------------------------------------------------------


def test_cleanup_execution_removes_existing_directory(basic_request):
    """cleanup_execution removes the execution directory after it is created."""
    result = prepare_workspace(basic_request)
    execution_dir = Path(result.artifacts_path)

    assert execution_dir.exists()
    cleanup_execution(basic_request.execution_id)
    assert not execution_dir.exists()


def test_cleanup_execution_noop_when_not_exists():
    """cleanup_execution does not raise if the directory never existed."""
    cleanup_execution("nonexistent-exec-does-not-exist-xyz")


def test_cleanup_execution_rejects_dotdot():
    with pytest.raises(ValueError, match="invalid characters"):
        cleanup_execution("../escape")


def test_cleanup_execution_rejects_forward_slash():
    with pytest.raises(ValueError, match="invalid characters"):
        cleanup_execution("some/nested/id")


def test_cleanup_execution_rejects_backslash():
    with pytest.raises(ValueError, match="invalid characters"):
        cleanup_execution("some\\nested")


def test_cleanup_execution_rejects_empty():
    with pytest.raises(ValueError, match="must not be empty"):
        cleanup_execution("")


def test_cleanup_execution_rejects_whitespace_only():
    with pytest.raises(ValueError, match="must not be empty"):
        cleanup_execution("   ")


# ---------------------------------------------------------------------------
# Workspace exclusion tests — heavy / recursive artifact directories
# ---------------------------------------------------------------------------


def _make_repo_with_dirs(tmp_path: Path, *dirs: str) -> Path:
    """Create a minimal fake repo with the given subdirectory names."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1")
    for d in dirs:
        parts = d.split("/")
        target = repo
        for part in parts:
            target = target / part
        target.mkdir(parents=True, exist_ok=True)
        (target / "sentinel").write_text("should not be copied")
    return repo


def _workspace_has(result: PreparedWorkspace, relpath: str) -> bool:
    return (Path(result.workspace_path) / relpath).exists()


@pytest.fixture
def repo_with_artifacts(tmp_path):
    return _make_repo_with_dirs(
        tmp_path,
        ".venv",
        "ui/node_modules",
        "ui/.next",
        "assistant_os/__pycache__",
        ".pytest_cache",
        ".claude/worktrees",
        "logs",
        "tests_generated",
        "var/runner/executions",
    )


def _request_for(repo: Path, exec_id: str) -> "RunnerExecutionRequest":
    return RunnerExecutionRequest(execution_id=exec_id, repo_path=str(repo))


def test_excludes_venv(tmp_path):
    repo = _make_repo_with_dirs(tmp_path, ".venv")
    result = prepare_workspace(_request_for(repo, "excl-venv-001"))
    assert not _workspace_has(result, ".venv"), ".venv must be excluded"


def test_excludes_node_modules(tmp_path):
    repo = _make_repo_with_dirs(tmp_path, "ui/node_modules")
    result = prepare_workspace(_request_for(repo, "excl-nm-001"))
    assert not _workspace_has(result, "ui/node_modules"), "node_modules must be excluded"


def test_excludes_next(tmp_path):
    repo = _make_repo_with_dirs(tmp_path, "ui/.next")
    result = prepare_workspace(_request_for(repo, "excl-next-001"))
    assert not _workspace_has(result, "ui/.next"), ".next must be excluded"


def test_excludes_pycache(tmp_path):
    repo = _make_repo_with_dirs(tmp_path, "assistant_os/__pycache__")
    result = prepare_workspace(_request_for(repo, "excl-pyc-001"))
    assert not _workspace_has(result, "assistant_os/__pycache__"), "__pycache__ must be excluded"


def test_excludes_pytest_cache(tmp_path):
    repo = _make_repo_with_dirs(tmp_path, ".pytest_cache")
    result = prepare_workspace(_request_for(repo, "excl-ptc-001"))
    assert not _workspace_has(result, ".pytest_cache"), ".pytest_cache must be excluded"


def test_excludes_var_runner_executions(tmp_path):
    repo = _make_repo_with_dirs(tmp_path, "var/runner/executions")
    result = prepare_workspace(_request_for(repo, "excl-var-001"))
    assert not _workspace_has(result, "var"), "var/ must be excluded"


def test_excludes_claude_worktrees(tmp_path):
    repo = _make_repo_with_dirs(tmp_path, ".claude/worktrees")
    result = prepare_workspace(_request_for(repo, "excl-cld-001"))
    assert not _workspace_has(result, ".claude"), ".claude must be excluded"


def test_excludes_logs(tmp_path):
    repo = _make_repo_with_dirs(tmp_path, "logs")
    result = prepare_workspace(_request_for(repo, "excl-logs-001"))
    assert not _workspace_has(result, "logs"), "logs must be excluded"


def test_excludes_tests_generated(tmp_path):
    repo = _make_repo_with_dirs(tmp_path, "tests_generated")
    result = prepare_workspace(_request_for(repo, "excl-tgen-001"))
    assert not _workspace_has(result, "tests_generated"), "tests_generated must be excluded"


def test_excludes_all_artifacts_combined(repo_with_artifacts):
    """All heavy artifact directories are excluded in a single workspace copy."""
    result = prepare_workspace(_request_for(repo_with_artifacts, "excl-all-001"))
    assert not _workspace_has(result, ".venv")
    assert not _workspace_has(result, "ui/node_modules")
    assert not _workspace_has(result, "ui/.next")
    assert not _workspace_has(result, "assistant_os/__pycache__")
    assert not _workspace_has(result, ".pytest_cache")
    assert not _workspace_has(result, "var")
    assert not _workspace_has(result, ".claude")
    assert not _workspace_has(result, "logs")
    assert not _workspace_has(result, "tests_generated")
    # Source files must still be present
    assert _workspace_has(result, "main.py")
