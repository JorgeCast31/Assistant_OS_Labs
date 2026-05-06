"""
Workspace Manager — Slice 1 (hardened).

Creates a controlled, isolated workspace for each Runner execution.

Layout:
    var/runner/executions/<execution_id>/
        metadata.json
        runner.log
        workspace/          ← copy of repo (.git excluded)
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import WorkspacePreparationError
from .policies import validate_repo_path
from .runner_models import RunnerExecutionRequest, RunnerExecutionStatus

logger = logging.getLogger(__name__)

# Base directory for all Runner execution artefacts.
# Resolves to <project_root>/var/runner/executions/
_RUNNER_BASE: Path = Path(__file__).resolve().parent.parent.parent / "var" / "runner" / "executions"

# Append-only log for failures that occur before a workspace is created.
# Located one level up from executions/ so it always exists independently.
_PREFLIGHT_FAILURES_LOG: Path = _RUNNER_BASE.parent / "preflight_failures.log"

# Patterns always excluded when copying the repo into workspace.
# .git is excluded: it is large, contains sensitive history, and Slice 2
# operations work on files only — not git internals.
# The remaining patterns exclude heavy runtime artifacts that are irrelevant
# to test execution and would waste disk space or cause recursive copies.
_WORKSPACE_IGNORE_BASE = shutil.ignore_patterns(
    # VCS internals
    ".git",
    ".git/*",
    # Python runtime artifacts
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    # Node / frontend build artifacts
    "node_modules",
    ".next",
    "tsconfig.tsbuildinfo",
    # Runner execution artifacts — defence-in-depth alongside _make_copy_ignore
    "var",
    # Claude Code internals (worktrees, session state)
    ".claude",
    # Runtime output directories
    "logs",
    "tests_generated",
)


def _make_copy_ignore(repo_path: Path, execution_dir: Path):
    """Return a copytree ignore callable that excludes .git and prevents recursive
    self-copy when repo_path contains the runner execution base directory.

    Without this guard, using the project root as repo_path causes shutil.copytree
    to recurse into var/runner/executions/ and try to copy the destination into
    itself — either hanging or raising path-too-long errors on Windows.

    Strategy: if the execution_dir is inside repo_path, identify the first
    path component of execution_dir relative to repo_path and add it to the
    ignore patterns for that specific source directory only.
    """
    base_ignore = _WORKSPACE_IGNORE_BASE

    try:
        rel = execution_dir.resolve().relative_to(repo_path.resolve())
        # execution_dir is inside repo_path — get the top-level dir to ignore.
        top = rel.parts[0]
    except ValueError:
        # execution_dir is outside repo_path — no extra ignore needed.
        return base_ignore

    # Build a callable ignore that blocks the identified top-level directory
    # only when encountered directly under repo_path (src == repo_path).
    repo_resolved_str = str(repo_path.resolve())

    def _ignore(src: str, names: list) -> set:
        ignored = set(base_ignore(src, names))
        if Path(src).resolve() == Path(repo_resolved_str).resolve():
            if top in names:
                ignored.add(top)
        return ignored

    return _ignore


@dataclass
class PreparedWorkspace:
    """Paths produced by a successful workspace preparation."""

    workspace_path: str
    artifacts_path: str


def log_preflight_failure(execution_id: str, repo_path: str, error: str) -> None:
    """Append a one-line JSON record to the global preflight_failures.log.

    Called when a request fails before a per-execution workspace is created,
    so that pre-workspace failures leave at least a minimal trace on disk.
    Failure to write is non-fatal and only emits a warning.
    """
    ts = datetime.now(timezone.utc).isoformat()
    record = json.dumps(
        {
            "timestamp": ts,
            "execution_id": execution_id,
            "repo_path": repo_path,
            "phase": "preflight",
            "error": error,
        },
        ensure_ascii=False,
    )
    try:
        _RUNNER_BASE.parent.mkdir(parents=True, exist_ok=True)
        with _PREFLIGHT_FAILURES_LOG.open("a", encoding="utf-8") as fh:
            fh.write(record + "\n")
    except OSError as exc:
        logger.warning("Could not write preflight_failures.log: %s", exc)


def _append_log(log_file: Path, message: str) -> None:
    """Append a timestamped line to runner.log. Failure is non-fatal."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {message}\n")
    except OSError as exc:
        logger.warning("Could not write to runner.log: %s", exc)


def prepare_workspace(request: RunnerExecutionRequest) -> PreparedWorkspace:
    """Create the execution workspace for *request*.

    Steps:
        1. Validate repo_path via policies.
        2. Create execution directory tree.
        3. Copy repo into workspace/ (excluding .git).
        4. Write initial metadata.json and runner.log.

    Returns:
        PreparedWorkspace with resolved paths.

    Raises:
        PolicyViolationError: if repo_path violates policy.
        WorkspacePreparationError: on any filesystem failure.
    """
    # Policy check — raises PolicyViolationError on violation.
    validate_repo_path(request.repo_path)

    execution_dir = _RUNNER_BASE / request.execution_id
    workspace_dir = execution_dir / "workspace"
    metadata_file = execution_dir / "metadata.json"
    log_file = execution_dir / "runner.log"

    try:
        execution_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkspacePreparationError(
            f"Cannot create execution directory {execution_dir}: {exc}"
        ) from exc

    # Initialise log file before any further work so events are captured.
    try:
        log_file.write_text("", encoding="utf-8")  # create empty file
    except OSError as exc:
        raise WorkspacePreparationError(f"Cannot create runner.log: {exc}") from exc

    _append_log(log_file, f"preflight passed for execution {request.execution_id!r}")
    _append_log(log_file, f"copying repo from {request.repo_path!r} (excluding .git)")

    # Copy repo into workspace/ — .git and runner artifacts are excluded.
    # _make_copy_ignore also prevents recursive self-copy when repo_path contains
    # the execution directory (e.g. using the project root as repo_path).
    copy_ignore = _make_copy_ignore(Path(request.repo_path), execution_dir)
    try:
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        shutil.copytree(request.repo_path, str(workspace_dir), ignore=copy_ignore)
    except (OSError, shutil.Error) as exc:
        _append_log(log_file, f"ERROR: repo copy failed: {exc}")
        raise WorkspacePreparationError(
            f"Cannot copy repo '{request.repo_path}' to workspace: {exc}"
        ) from exc

    _append_log(log_file, "workspace directory created successfully")

    # Write initial metadata.
    metadata = {
        "execution_id": request.execution_id,
        "status": RunnerExecutionStatus.RUNNING.value,
        "repo_path": request.repo_path,
        "base_commit": request.base_commit,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    try:
        metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    except OSError as exc:
        raise WorkspacePreparationError(f"Cannot write metadata.json: {exc}") from exc

    _append_log(log_file, "metadata.json written — status: RUNNING")
    logger.info("Workspace ready for execution %s at %s", request.execution_id, workspace_dir)

    return PreparedWorkspace(
        workspace_path=str(workspace_dir),
        artifacts_path=str(execution_dir),
    )


def cleanup_execution(execution_id: str) -> None:
    """Remove the execution directory for *execution_id*.

    Safe by design:
      - Rejects empty strings, path separators, and '..' sequences.
      - Verifies the resolved target stays inside _RUNNER_BASE before deleting.
      - No-ops silently if the directory does not exist.

    Args:
        execution_id: Identifier previously used with prepare_workspace().

    Raises:
        ValueError: if execution_id is invalid or would escape the runner base.
    """
    if not execution_id or not execution_id.strip():
        raise ValueError("cleanup_execution: execution_id must not be empty.")
    if ".." in execution_id or "/" in execution_id or "\\" in execution_id:
        raise ValueError(
            f"cleanup_execution: execution_id contains invalid characters: {execution_id!r}"
        )

    execution_dir = _RUNNER_BASE / execution_id

    # Defence-in-depth: confirm the resolved path is still inside _RUNNER_BASE.
    try:
        execution_dir.resolve().relative_to(_RUNNER_BASE.resolve())
    except ValueError:
        raise ValueError(
            f"cleanup_execution: resolved path escapes runner base for id {execution_id!r}"
        )

    if execution_dir.exists():
        shutil.rmtree(execution_dir)
        logger.info("Cleaned up execution directory: %s", execution_dir)
