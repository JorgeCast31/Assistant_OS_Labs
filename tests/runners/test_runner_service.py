"""Tests for RunnerService — Slice 1 / pre-Slice-4 hardening."""

import json
import sys
from pathlib import Path

import pytest

from assistant_os.runners.runner_models import RunnerExecutionRequest, RunnerExecutionStatus
from assistant_os.runners.runner_service import RunnerService

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
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
    )
    result = RunnerService().run(request)

    assert result.final_status == "needs_review"
    assert result.report_json_path is not None
    assert result.notification_path is not None


def test_full_loop_report_json_has_required_fields(sample_repo):
    request = RunnerExecutionRequest(
        execution_id="s4-rpt-001",
        repo_path=str(sample_repo),
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
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
        execution_mode="SAFE_EXECUTE",
    )
    result = RunnerService().run(request)

    data = json.loads(Path(result.artifacts_path, "metadata.json").read_text())
    assert "final_status" in data
    assert data["final_status"] is not None


# ---------------------------------------------------------------------------
# Policy enforcement: execution_mode governs apply and promote
# ---------------------------------------------------------------------------


def test_policy_dry_run_skips_apply(service, sample_repo):
    """DRY_RUN: apply_engine NOT called, promotion_status=skipped_policy, repo unchanged."""
    original_content = (sample_repo / "app.py").read_text()
    request = RunnerExecutionRequest(
        execution_id="policy-dry-001",
        repo_path=str(sample_repo),
        changes=[{"op": "file_replace", "path": "app.py", "content": "x = CHANGED\n"}],
        execution_mode="DRY_RUN",
    )
    result = service.run(request)

    assert result.modified_files == [], "DRY_RUN must not apply any changes"
    assert result.promotion_status == "skipped_policy"
    assert (sample_repo / "app.py").read_text() == original_content, "repo must be unchanged"


def test_policy_safe_execute_applies_without_promote(service, sample_repo):
    """SAFE_EXECUTE: apply_engine called, no promotion, repo unchanged."""
    original_content = (sample_repo / "app.py").read_text()
    request = RunnerExecutionRequest(
        execution_id="policy-safe-001",
        repo_path=str(sample_repo),
        changes=[{"op": "file_replace", "path": "app.py", "content": "x = CHANGED\n"}],
        execution_mode="SAFE_EXECUTE",
    )
    result = service.run(request)

    assert "app.py" in result.modified_files, "SAFE_EXECUTE must apply changes to workspace"
    assert result.promotion_status == "skipped_policy"
    assert (sample_repo / "app.py").read_text() == original_content, "repo must be unchanged"


def test_policy_full_execute_applies_and_promotes(service, sample_repo):
    """FULL_EXECUTE: apply_engine called, promote executed, repo changed."""
    request = RunnerExecutionRequest(
        execution_id="policy-full-001",
        repo_path=str(sample_repo),
        changes=[{"op": "file_replace", "path": "app.py", "content": "x = PROMOTED\n"}],
        execution_mode="FULL_EXECUTE",
    )
    result = service.run(request)

    assert "app.py" in result.modified_files, "FULL_EXECUTE must apply changes"
    assert result.promotion_status == "performed"
    assert (sample_repo / "app.py").read_text() == "x = PROMOTED\n", "repo must be updated"


# ---------------------------------------------------------------------------
# Rollback: backup + restore
# ---------------------------------------------------------------------------


def test_backup_existing_file_is_copied(service, sample_repo, tmp_path):
    """_backup_files copies an existing repo file and marks it 'existing'."""
    backup_dir = tmp_path / "_backup"
    backup_dir.mkdir()
    manifest = service._backup_files(
        repo_root=sample_repo,
        backup_dir=backup_dir,
        files=["app.py"],
    )

    assert manifest["app.py"] == "existing"
    assert (backup_dir / "app.py").exists()
    assert (backup_dir / "app.py").read_text() == (sample_repo / "app.py").read_text()


def test_backup_new_file_is_marked_not_copied(service, sample_repo, tmp_path):
    """_backup_files marks a non-existent file as 'new_file' and copies nothing."""
    backup_dir = tmp_path / "_backup"
    backup_dir.mkdir()
    manifest = service._backup_files(
        repo_root=sample_repo,
        backup_dir=backup_dir,
        files=["brand_new.py"],
    )

    assert manifest["brand_new.py"] == "new_file"
    assert not (backup_dir / "brand_new.py").exists()


def test_backup_writes_manifest_json(service, sample_repo, tmp_path):
    """_backup_files saves manifest.json inside backup_dir."""
    backup_dir = tmp_path / "_backup"
    backup_dir.mkdir()
    service._backup_files(
        repo_root=sample_repo,
        backup_dir=backup_dir,
        files=["app.py"],
    )

    manifest_file = backup_dir / "manifest.json"
    assert manifest_file.exists()
    data = json.loads(manifest_file.read_text())
    assert "files" in data
    assert data["files"]["app.py"] == "existing"


def test_restore_existing_restores_content(service, sample_repo, tmp_path):
    """_restore_files overwrites repo file with the backed-up version."""
    backup_dir = tmp_path / "_backup"
    backup_dir.mkdir()
    original = (sample_repo / "app.py").read_text()

    manifest = service._backup_files(
        repo_root=sample_repo,
        backup_dir=backup_dir,
        files=["app.py"],
    )
    # Mutate the repo file (simulating promote)
    (sample_repo / "app.py").write_text("x = MUTATED\n")

    restored = service._restore_files(
        repo_root=sample_repo,
        backup_dir=backup_dir,
        manifest=manifest,
    )

    assert "app.py" in restored
    assert (sample_repo / "app.py").read_text() == original


def test_restore_new_file_deletes_it(service, sample_repo, tmp_path):
    """_restore_files deletes a file that was created by promote (new_file)."""
    backup_dir = tmp_path / "_backup"
    backup_dir.mkdir()
    # Simulate a file that didn't exist before promote but was created by it
    manifest = {"created_by_promote.py": "new_file"}
    (backup_dir / "manifest.json").write_text(
        json.dumps({"files": manifest}), encoding="utf-8"
    )
    (sample_repo / "created_by_promote.py").write_text("x = 1\n")

    restored = service._restore_files(
        repo_root=sample_repo,
        backup_dir=backup_dir,
        manifest=manifest,
    )

    assert "created_by_promote.py" in restored
    assert not (sample_repo / "created_by_promote.py").exists()


def test_full_execute_backup_then_restore_returns_to_original(service, sample_repo):
    """End-to-end: repo original → FULL_EXECUTE → restore → repo original."""
    original_content = (sample_repo / "app.py").read_text()
    request = RunnerExecutionRequest(
        execution_id="rollback-e2e-001",
        repo_path=str(sample_repo),
        changes=[{"op": "file_replace", "path": "app.py", "content": "x = AFTER_PROMOTE\n"}],
        execution_mode="FULL_EXECUTE",
    )
    result = service.run(request)

    # Verify promote happened and backup was created
    assert result.promotion_status == "performed"
    assert result.backup_path is not None
    assert result.backup_manifest is not None
    assert (sample_repo / "app.py").read_text() == "x = AFTER_PROMOTE\n"

    # Restore using the backup recorded in the result
    restored = service._restore_files(
        repo_root=sample_repo,
        backup_dir=Path(result.backup_path),
        manifest=result.backup_manifest,
    )

    assert "app.py" in restored
    assert (sample_repo / "app.py").read_text() == original_content
