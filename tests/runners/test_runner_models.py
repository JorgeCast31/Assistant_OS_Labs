"""Tests for runner_models — Slice 1."""

from datetime import datetime, timezone

import pytest

from assistant_os.runners.runner_models import (
    RunnerExecutionRequest,
    RunnerExecutionResult,
    RunnerExecutionStatus,
)


def test_request_minimal():
    req = RunnerExecutionRequest(execution_id="exec-001", repo_path="/some/repo")
    assert req.execution_id == "exec-001"
    assert req.repo_path == "/some/repo"
    assert req.base_commit is None
    assert req.changes is None
    assert req.test_spec is None
    assert req.validation_spec is None
    assert req.workspace_spec is None
    assert req.metadata is None


def test_request_full():
    req = RunnerExecutionRequest(
        execution_id="exec-002",
        repo_path="/other/repo",
        base_commit="abc123",
        changes=[{"file": "foo.py"}],
        test_spec={"run": "pytest"},
        validation_spec={"require": "green"},
        workspace_spec={"isolate": True},
        metadata={"user": "jorge"},
    )
    assert req.base_commit == "abc123"
    assert req.changes == [{"file": "foo.py"}]
    assert req.metadata == {"user": "jorge"}


def test_result_creation():
    now = datetime.now(timezone.utc)
    result = RunnerExecutionResult(
        execution_id="exec-001",
        status=RunnerExecutionStatus.WORKSPACE_READY,
        started_at=now,
        finished_at=now,
        workspace_path="/var/runner/executions/exec-001/workspace",
        artifacts_path="/var/runner/executions/exec-001",
        summary="All good.",
    )
    assert result.status == RunnerExecutionStatus.WORKSPACE_READY
    assert result.error is None
    assert result.summary == "All good."


def test_result_failed():
    now = datetime.now(timezone.utc)
    result = RunnerExecutionResult(
        execution_id="exec-002",
        status=RunnerExecutionStatus.FAILED,
        started_at=now,
        finished_at=now,
        error="something went wrong",
        summary="Execution failed.",
    )
    assert result.status == RunnerExecutionStatus.FAILED
    assert result.workspace_path is None
    assert result.artifacts_path is None


def test_status_enum_values():
    assert RunnerExecutionStatus.PENDING == "PENDING"
    assert RunnerExecutionStatus.RUNNING == "RUNNING"
    assert RunnerExecutionStatus.FAILED == "FAILED"
    assert RunnerExecutionStatus.WORKSPACE_READY == "WORKSPACE_READY"
