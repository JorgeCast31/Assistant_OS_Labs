"""Tests for ReportBuilder — Slice 4."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from assistant_os.runners.report_builder import ReportBuilder
from assistant_os.runners.runner_models import (
    ReportArtifacts,
    RunnerExecutionResult,
    RunnerExecutionStatus,
    TestExecutionResult,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def artifacts_dir(tmp_path):
    d = tmp_path / "exec-001"
    d.mkdir()
    return d


def _make_result(
    artifacts_path: str,
    status=RunnerExecutionStatus.TESTS_PASSED,
    final_status="success",
    modified_files=None,
    test_result=None,
    error=None,
) -> RunnerExecutionResult:
    now = datetime.now(timezone.utc)
    return RunnerExecutionResult(
        execution_id="rpt-test-001",
        status=status,
        started_at=now,
        finished_at=now,
        artifacts_path=artifacts_path,
        modified_files=modified_files or [],
        test_result=test_result,
        final_status=final_status,
        error=error,
        summary="Test summary.",
    )


def _make_validation(final_status="success") -> ValidationResult:
    return ValidationResult(
        final_status=final_status,
        reasons=[f"Outcome: {final_status}."],
        validation_summary=f"Outcome: {final_status}.",
    )


@pytest.fixture
def builder():
    return ReportBuilder()


# ---------------------------------------------------------------------------
# File creation
# ---------------------------------------------------------------------------


def test_build_creates_report_json(builder, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")

    artifacts = builder.build(result, validation)

    assert Path(artifacts.json_path).exists()


def test_build_creates_report_md(builder, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")

    artifacts = builder.build(result, validation)

    assert Path(artifacts.md_path).exists()


def test_build_returns_report_artifacts(builder, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")

    artifacts = builder.build(result, validation)

    assert isinstance(artifacts, ReportArtifacts)
    assert artifacts.json_path.endswith("report.json")
    assert artifacts.md_path.endswith("report.md")


# ---------------------------------------------------------------------------
# report.json content
# ---------------------------------------------------------------------------


def test_report_json_contains_execution_id(builder, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")
    builder.build(result, validation)

    data = json.loads((artifacts_dir / "report.json").read_text())
    assert data["execution_id"] == "rpt-test-001"


def test_report_json_contains_final_status(builder, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")
    builder.build(result, validation)

    data = json.loads((artifacts_dir / "report.json").read_text())
    assert data["final_status"] == "success"


def test_report_json_contains_modified_files(builder, artifacts_dir):
    result = _make_result(str(artifacts_dir), modified_files=["src/foo.py", "src/bar.py"])
    validation = _make_validation("success")
    builder.build(result, validation)

    data = json.loads((artifacts_dir / "report.json").read_text())
    assert "src/foo.py" in data["modified_files"]


def test_report_json_contains_validation_result(builder, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("needs_review")
    builder.build(result, validation)

    data = json.loads((artifacts_dir / "report.json").read_text())
    assert data["validation_result"]["final_status"] == "needs_review"


def test_report_json_contains_test_result(builder, artifacts_dir):
    tr = TestExecutionResult(status="passed", command=["pytest"], exit_code=0, duration_ms=200)
    result = _make_result(str(artifacts_dir), test_result=tr)
    validation = _make_validation("success")
    builder.build(result, validation)

    data = json.loads((artifacts_dir / "report.json").read_text())
    assert data["test_result"]["status"] == "passed"


def test_report_json_for_failed_result(builder, artifacts_dir):
    result = _make_result(
        str(artifacts_dir),
        status=RunnerExecutionStatus.FAILED,
        final_status="failed",
        error="Apply failed: path traversal.",
    )
    validation = _make_validation("failed")
    builder.build(result, validation)

    data = json.loads((artifacts_dir / "report.json").read_text())
    assert data["final_status"] == "failed"
    assert data["error"] is not None


# ---------------------------------------------------------------------------
# report.md content
# ---------------------------------------------------------------------------


def test_report_md_contains_execution_id(builder, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")
    builder.build(result, validation)

    content = (artifacts_dir / "report.md").read_text()
    assert "rpt-test-001" in content


def test_report_md_contains_final_status(builder, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")
    builder.build(result, validation)

    content = (artifacts_dir / "report.md").read_text()
    assert "SUCCESS" in content


def test_report_md_mentions_no_files_when_empty(builder, artifacts_dir):
    result = _make_result(str(artifacts_dir), modified_files=[])
    validation = _make_validation("needs_review")
    builder.build(result, validation)

    content = (artifacts_dir / "report.md").read_text()
    assert "none" in content.lower()
