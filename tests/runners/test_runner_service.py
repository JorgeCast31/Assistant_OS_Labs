"""Tests for RunnerService — Slice 1 / pre-Slice-4 hardening."""

import json
import sys
from pathlib import Path

import pytest

from assistant_os.runners.runner_models import RunnerExecutionRequest, RunnerExecutionStatus
from assistant_os.runners.runner_service import RunnerService
from tests.runners.conftest import make_authorized_plan

_PYTHON = sys.executable


@pytest.fixture
def service():
    return RunnerService()


@pytest.fixture
def sample_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1")
    return repo


def test_run_happy_path(service, sample_repo):
    request = RunnerExecutionRequest(
        execution_id="svc-test-001",
        repo_path=str(sample_repo),
        authorized_plan=make_authorized_plan("svc-test-001"),
    )
    result = service.run(request)

    assert result.execution_id == "svc-test-001"
    assert result.status == RunnerExecutionStatus.WORKSPACE_READY
    assert result.error is None
    assert result.workspace_path is not None
    assert result.artifacts_path is not None
    assert result.started_at <= result.finished_at


def test_run_creates_workspace_files(service, sample_repo):
    request = RunnerExecutionRequest(
        execution_id="svc-test-002",
        repo_path=str(sample_repo),
        authorized_plan=make_authorized_plan("svc-test-002"),
    )
    result = service.run(request)

    artifacts = Path(result.artifacts_path)
    assert (artifacts / "metadata.json").exists()
    assert (artifacts / "runner.log").exists()
    assert (artifacts / "workspace").is_dir()


def test_run_writes_final_metadata(service, sample_repo):
    request = RunnerExecutionRequest(
        execution_id="svc-test-003",
        repo_path=str(sample_repo),
        authorized_plan=make_authorized_plan("svc-test-003"),
    )
    result = service.run(request)

    metadata_file = Path(result.artifacts_path) / "metadata.json"
    data = json.loads(metadata_file.read_text())

    assert data["status"] == RunnerExecutionStatus.WORKSPACE_READY.value
    assert data["finished_at"] is not None


def test_run_fails_on_nonexistent_repo(service):
    request = RunnerExecutionRequest(
        execution_id="svc-test-004",
        repo_path="/no/such/path/anywhere",
    )
    result = service.run(request)

    assert result.status == RunnerExecutionStatus.FAILED
    assert result.error is not None
    assert result.workspace_path is None


def test_run_fails_on_empty_execution_id(service, sample_repo):
    request = RunnerExecutionRequest(
        execution_id="",
        repo_path=str(sample_repo),
    )
    result = service.run(request)

    assert result.status == RunnerExecutionStatus.FAILED
    assert "execution_id" in result.error


def test_run_fails_on_empty_repo_path(service):
    request = RunnerExecutionRequest(
        execution_id="svc-test-006",
        repo_path="",
    )
    result = service.run(request)

    assert result.status == RunnerExecutionStatus.FAILED
    assert result.error is not None


def test_run_result_summary_present(service, sample_repo):
    request = RunnerExecutionRequest(
        execution_id="svc-test-007",
        repo_path=str(sample_repo),
    )
    result = service.run(request)
    assert result.summary != ""


# ---------------------------------------------------------------------------
# Fix 1: execution_id sanitization (pre-Slice-4 hardening)
# ---------------------------------------------------------------------------


def test_run_fails_on_execution_id_with_dotdot(service, sample_repo):
    request = RunnerExecutionRequest(
        execution_id="../escape",
        repo_path=str(sample_repo),
    )
    result = service.run(request)

    assert result.status == RunnerExecutionStatus.FAILED
    assert "execution_id" in result.error


def test_run_fails_on_execution_id_with_forward_slash(service, sample_repo):
    request = RunnerExecutionRequest(
        execution_id="a/b",
        repo_path=str(sample_repo),
    )
    result = service.run(request)

    assert result.status == RunnerExecutionStatus.FAILED
    assert "execution_id" in result.error


def test_run_fails_on_execution_id_with_backslash(service, sample_repo):
    request = RunnerExecutionRequest(
        execution_id="a\\b",
        repo_path=str(sample_repo),
    )
    result = service.run(request)

    assert result.status == RunnerExecutionStatus.FAILED
    assert "execution_id" in result.error


# ---------------------------------------------------------------------------
# Fix 2: preflight failures leave a trace (pre-Slice-4 hardening)
# ---------------------------------------------------------------------------


def test_preflight_failure_writes_to_log(service, sample_repo, monkeypatch, tmp_path):
    failure_log = tmp_path / "preflight_failures.log"
    monkeypatch.setattr(
        "assistant_os.runners.workspace_manager._PREFLIGHT_FAILURES_LOG", failure_log
    )

    request = RunnerExecutionRequest(
        execution_id="svc-pf-001",
        repo_path="/no/such/path/anywhere",
    )
    result = service.run(request)

    assert result.status == RunnerExecutionStatus.FAILED
    assert failure_log.exists()
    content = failure_log.read_text()
    assert "svc-pf-001" in content


def test_preflight_log_contains_required_fields(service, sample_repo, monkeypatch, tmp_path):
    failure_log = tmp_path / "preflight_failures.log"
    monkeypatch.setattr(
        "assistant_os.runners.workspace_manager._PREFLIGHT_FAILURES_LOG", failure_log
    )

    request = RunnerExecutionRequest(
        execution_id="svc-pf-002",
        repo_path="/nonexistent",
    )
    service.run(request)

    import json as _json
    record = _json.loads(failure_log.read_text().strip())
    assert record["execution_id"] == "svc-pf-002"
    assert record["phase"] == "preflight"
    assert "error" in record
    assert "timestamp" in record


def test_successful_run_does_not_write_preflight_log(service, sample_repo, monkeypatch, tmp_path):
    failure_log = tmp_path / "preflight_failures.log"
    monkeypatch.setattr(
        "assistant_os.runners.workspace_manager._PREFLIGHT_FAILURES_LOG", failure_log
    )

    request = RunnerExecutionRequest(
        execution_id="svc-pf-003",
        repo_path=str(sample_repo),
        authorized_plan=make_authorized_plan("svc-pf-003"),
    )
    service.run(request)

    assert not failure_log.exists()


# ---------------------------------------------------------------------------
# Fix 3: TEST_START appears exactly once per test execution
# ---------------------------------------------------------------------------


def test_test_start_logged_exactly_once(sample_repo):
    (sample_repo / "test_ok.py").write_text("def test_pass():\n    assert True\n")
    request = RunnerExecutionRequest(
        execution_id="svc-log-001",
        repo_path=str(sample_repo),
        test_spec={"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30},
        authorized_plan=make_authorized_plan("svc-log-001"),
    )
    result = RunnerService().run(request)

    log_content = Path(result.artifacts_path, "runner.log").read_text()
    assert log_content.count("phase: TEST_START") == 1


# ---------------------------------------------------------------------------
# Slice 4: full loop integration
# ---------------------------------------------------------------------------


def test_full_loop_changes_and_tests_passing_yields_success(sample_repo):
    """apply + tests pass → final_status='success', all artefacts present."""
    (sample_repo / "test_gen.py").write_text("")  # placeholder so repo isn't empty
    request = RunnerExecutionRequest(
        execution_id="s4-full-001",
        repo_path=str(sample_repo),
        changes=[
            {"op": "file_replace", "path": "test_gen.py", "content": "def test_ok():\n    assert True\n"},
        ],
        test_spec={"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30},
        authorized_plan=make_authorized_plan("s4-full-001"),
    )
    result = RunnerService().run(request)

    assert result.final_status == "success"
    assert result.validation_result is not None
    assert result.validation_result.final_status == "success"
    assert result.report_json_path is not None and Path(result.report_json_path).exists()
    assert result.report_md_path is not None and Path(result.report_md_path).exists()
    assert result.notification_path is not None and Path(result.notification_path).exists()


def test_full_loop_failing_tests_yields_failed(sample_repo):
    """failing tests → final_status='failed'."""
    request = RunnerExecutionRequest(
        execution_id="s4-fail-001",
        repo_path=str(sample_repo),
        changes=[
            {"op": "file_replace", "path": "test_bad.py", "content": "def test_fail():\n    assert False\n"},
        ],
        test_spec={"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30},
        authorized_plan=make_authorized_plan("s4-fail-001"),
    )
    result = RunnerService().run(request)

    assert result.final_status == "failed"
    assert result.report_json_path is not None
    assert result.notification_path is not None


def test_full_loop_needs_review_when_allow_review(sample_repo):
    """apply without tests + allow_needs_review=True → final_status='needs_review'."""
    request = RunnerExecutionRequest(
        execution_id="s4-review-001",
        repo_path=str(sample_repo),
        changes=[
            {"op": "file_replace", "path": "new_feature.py", "content": "x = 1\n"},
        ],
        test_spec=None,
        validation_spec={"require_tests": True, "allow_needs_review": True},
        authorized_plan=make_authorized_plan("s4-review-001"),
    )
    result = RunnerService().run(request)

    assert result.final_status == "needs_review"
    assert result.report_json_path is not None
    assert result.notification_path is not None


def test_full_loop_report_json_has_required_fields(sample_repo):
    request = RunnerExecutionRequest(
        execution_id="s4-rpt-001",
        repo_path=str(sample_repo),
        authorized_plan=make_authorized_plan("s4-rpt-001"),
    )
    result = RunnerService().run(request)

    assert result.report_json_path is not None
    data = json.loads(Path(result.report_json_path).read_text())
    assert "execution_id" in data
    assert "final_status" in data
    assert "validation_result" in data


def test_full_loop_done_json_has_required_fields(sample_repo):
    request = RunnerExecutionRequest(
        execution_id="s4-ntf-001",
        repo_path=str(sample_repo),
        authorized_plan=make_authorized_plan("s4-ntf-001"),
    )
    result = RunnerService().run(request)

    assert result.notification_path is not None
    data = json.loads(Path(result.notification_path).read_text())
    assert data["execution_id"] == "s4-ntf-001"
    assert "final_status" in data
    assert "timestamp" in data


def test_full_loop_phases_logged(sample_repo):
    """runner.log must contain all Slice 4 phase markers."""
    request = RunnerExecutionRequest(
        execution_id="s4-log-001",
        repo_path=str(sample_repo),
        authorized_plan=make_authorized_plan("s4-log-001"),
    )
    result = RunnerService().run(request)

    log = Path(result.artifacts_path, "runner.log").read_text()
    for phase in ("VALIDATION_START", "VALIDATION_DONE", "REPORT_START", "REPORT_DONE",
                  "NOTIFY_START", "NOTIFY_DONE"):
        assert f"phase: {phase}" in log, f"Missing phase marker: {phase}"


def test_full_loop_apply_error_still_produces_report(sample_repo):
    """Apply failure should not prevent report + notification from being written."""
    request = RunnerExecutionRequest(
        execution_id="s4-apperr-001",
        repo_path=str(sample_repo),
        changes=[{"op": "file_replace", "path": "../../escape.py", "content": "evil"}],
        authorized_plan=make_authorized_plan("s4-apperr-001"),
    )
    result = RunnerService().run(request)

    assert result.status == RunnerExecutionStatus.FAILED
    assert result.final_status == "failed"
    assert result.report_json_path is not None and Path(result.report_json_path).exists()
    assert result.notification_path is not None and Path(result.notification_path).exists()


def test_full_loop_metadata_includes_final_status(sample_repo):
    request = RunnerExecutionRequest(
        execution_id="s4-meta-001",
        repo_path=str(sample_repo),
        authorized_plan=make_authorized_plan("s4-meta-001"),
    )
    result = RunnerService().run(request)

    data = json.loads(Path(result.artifacts_path, "metadata.json").read_text())
    assert "final_status" in data
    assert data["final_status"] is not None
