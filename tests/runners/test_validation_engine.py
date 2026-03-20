"""Tests for ValidationEngine — Slice 4."""

from datetime import datetime, timezone

import pytest

from assistant_os.runners.runner_models import (
    RunnerExecutionRequest,
    RunnerExecutionResult,
    RunnerExecutionStatus,
    TestExecutionResult,
    ValidationResult,
)
from assistant_os.runners.validation_engine import ValidationEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(
    status=RunnerExecutionStatus.WORKSPACE_READY,
    error=None,
    modified_files=None,
    test_result=None,
) -> RunnerExecutionResult:
    now = datetime.now(timezone.utc)
    return RunnerExecutionResult(
        execution_id="ve-test-001",
        status=status,
        started_at=now,
        finished_at=now,
        error=error,
        modified_files=modified_files or [],
        test_result=test_result,
    )


def _test_result(status: str, exit_code: int = 0) -> TestExecutionResult:
    return TestExecutionResult(status=status, command=["pytest"], exit_code=exit_code)


@pytest.fixture
def engine():
    return ValidationEngine()


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


def test_success_when_tests_passed(engine):
    result = _make_result(
        status=RunnerExecutionStatus.TESTS_PASSED,
        modified_files=["foo.py"],
        test_result=_test_result("passed"),
    )
    v = engine.validate(result, None)

    assert v.final_status == "success"
    assert any("passed" in r.lower() for r in v.reasons)


def test_success_when_tests_passed_no_changes(engine):
    result = _make_result(
        status=RunnerExecutionStatus.TESTS_PASSED,
        modified_files=[],
        test_result=_test_result("passed"),
    )
    v = engine.validate(result, None)

    assert v.final_status == "success"


def test_success_with_require_tests_met(engine):
    result = _make_result(
        status=RunnerExecutionStatus.TESTS_PASSED,
        modified_files=["bar.py"],
        test_result=_test_result("passed"),
    )
    v = engine.validate(result, {"require_tests": True})

    assert v.final_status == "success"


def test_success_with_require_changes_and_tests_passed(engine):
    result = _make_result(
        status=RunnerExecutionStatus.TESTS_PASSED,
        modified_files=["src/x.py"],
        test_result=_test_result("passed"),
    )
    v = engine.validate(result, {"require_tests": True, "require_changes": True})

    assert v.final_status == "success"


# ---------------------------------------------------------------------------
# Failed cases
# ---------------------------------------------------------------------------


def test_failed_when_error_set(engine):
    result = _make_result(
        status=RunnerExecutionStatus.FAILED,
        error="Apply failed: path traversal detected.",
    )
    v = engine.validate(result, None)

    assert v.final_status == "failed"
    assert any("error" in r.lower() for r in v.reasons)


def test_failed_when_intermediate_status_failed(engine):
    result = _make_result(status=RunnerExecutionStatus.FAILED)
    v = engine.validate(result, None)

    assert v.final_status == "failed"


def test_failed_when_test_explicitly_failed(engine):
    result = _make_result(
        status=RunnerExecutionStatus.TESTS_FAILED,
        test_result=_test_result("failed", exit_code=1),
    )
    v = engine.validate(result, None)

    assert v.final_status == "failed"
    assert any("failed" in r.lower() for r in v.reasons)


def test_failed_when_test_timed_out(engine):
    result = _make_result(
        status=RunnerExecutionStatus.FAILED,
        test_result=_test_result("timed_out"),
    )
    v = engine.validate(result, None)

    assert v.final_status == "failed"
    assert any("timed out" in r.lower() for r in v.reasons)


def test_failed_require_tests_not_met_strict(engine):
    """require_tests=True but no test_result, allow_needs_review=False → failed."""
    result = _make_result(
        status=RunnerExecutionStatus.CHANGES_APPLIED,
        modified_files=["x.py"],
    )
    v = engine.validate(result, {"require_tests": True, "allow_needs_review": False})

    assert v.final_status == "failed"


def test_failed_require_changes_not_met_strict(engine):
    """require_changes=True but no changes, allow_needs_review=False → failed."""
    result = _make_result(
        status=RunnerExecutionStatus.WORKSPACE_READY,
        modified_files=[],
    )
    v = engine.validate(result, {"require_changes": True, "allow_needs_review": False})

    assert v.final_status == "failed"


def test_failed_changes_applied_no_tests_strict(engine):
    """Changes applied but no tests, allow_needs_review=False → failed."""
    result = _make_result(
        status=RunnerExecutionStatus.CHANGES_APPLIED,
        modified_files=["a.py"],
    )
    v = engine.validate(result, {"allow_needs_review": False})

    assert v.final_status == "failed"


# ---------------------------------------------------------------------------
# Needs review cases
# ---------------------------------------------------------------------------


def test_needs_review_require_tests_not_met_with_review_allowed(engine):
    result = _make_result(
        status=RunnerExecutionStatus.CHANGES_APPLIED,
        modified_files=["x.py"],
    )
    v = engine.validate(result, {"require_tests": True, "allow_needs_review": True})

    assert v.final_status == "needs_review"
    assert any("require_tests" in r for r in v.reasons)


def test_needs_review_require_changes_not_met(engine):
    result = _make_result(status=RunnerExecutionStatus.WORKSPACE_READY, modified_files=[])
    v = engine.validate(result, {"require_changes": True, "allow_needs_review": True})

    assert v.final_status == "needs_review"


def test_needs_review_changes_applied_no_tests(engine):
    result = _make_result(
        status=RunnerExecutionStatus.CHANGES_APPLIED,
        modified_files=["b.py"],
    )
    v = engine.validate(result, None)  # allow_needs_review defaults to True

    assert v.final_status == "needs_review"


def test_needs_review_workspace_only(engine):
    result = _make_result(status=RunnerExecutionStatus.WORKSPACE_READY, modified_files=[])
    v = engine.validate(result, None)

    assert v.final_status == "needs_review"


# ---------------------------------------------------------------------------
# Structure of ValidationResult
# ---------------------------------------------------------------------------


def test_validation_result_has_required_fields(engine):
    result = _make_result(
        status=RunnerExecutionStatus.TESTS_PASSED,
        test_result=_test_result("passed"),
    )
    v = engine.validate(result, None)

    assert isinstance(v, ValidationResult)
    assert v.final_status in ("success", "failed", "needs_review")
    assert isinstance(v.reasons, list)
    assert isinstance(v.validation_summary, str) and v.validation_summary


def test_validation_summary_contains_status(engine):
    result = _make_result(
        status=RunnerExecutionStatus.TESTS_PASSED,
        test_result=_test_result("passed"),
    )
    v = engine.validate(result, None)

    assert "success" in v.validation_summary.lower()
