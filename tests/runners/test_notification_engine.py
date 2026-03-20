"""Tests for NotificationEngine — Slice 4."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from assistant_os.runners.notification_engine import NotificationEngine
from assistant_os.runners.runner_models import (
    NotificationResult,
    RunnerExecutionResult,
    RunnerExecutionStatus,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def artifacts_dir(tmp_path):
    d = tmp_path / "exec-notify-001"
    d.mkdir()
    return d


def _make_result(artifacts_path: str, final_status: str = "success") -> RunnerExecutionResult:
    now = datetime.now(timezone.utc)
    return RunnerExecutionResult(
        execution_id="ntf-test-001",
        status=RunnerExecutionStatus.TESTS_PASSED,
        started_at=now,
        finished_at=now,
        artifacts_path=artifacts_path,
        final_status=final_status,
        summary="Execution complete.",
    )


def _make_validation(final_status: str = "success") -> ValidationResult:
    return ValidationResult(
        final_status=final_status,
        reasons=[],
        validation_summary=f"Outcome: {final_status}.",
    )


@pytest.fixture
def engine():
    return NotificationEngine()


# ---------------------------------------------------------------------------
# File creation
# ---------------------------------------------------------------------------


def test_notify_creates_done_json(engine, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")

    notif = engine.notify(result, validation)

    assert Path(notif.notification_path).exists()
    assert notif.notification_path.endswith("done.json")


def test_notify_returns_notification_result(engine, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")

    notif = engine.notify(result, validation)

    assert isinstance(notif, NotificationResult)


# ---------------------------------------------------------------------------
# done.json content
# ---------------------------------------------------------------------------


def test_done_json_contains_execution_id(engine, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")
    engine.notify(result, validation)

    data = json.loads((artifacts_dir / "done.json").read_text())
    assert data["execution_id"] == "ntf-test-001"


def test_done_json_contains_final_status(engine, artifacts_dir):
    result = _make_result(str(artifacts_dir), final_status="failed")
    validation = _make_validation("failed")
    engine.notify(result, validation)

    data = json.loads((artifacts_dir / "done.json").read_text())
    assert data["final_status"] == "failed"


def test_done_json_contains_summary(engine, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")
    engine.notify(result, validation)

    data = json.loads((artifacts_dir / "done.json").read_text())
    assert "summary" in data and data["summary"]


def test_done_json_contains_timestamp(engine, artifacts_dir):
    result = _make_result(str(artifacts_dir))
    validation = _make_validation("success")
    engine.notify(result, validation)

    data = json.loads((artifacts_dir / "done.json").read_text())
    assert "timestamp" in data and data["timestamp"]


def test_done_json_for_needs_review(engine, artifacts_dir):
    result = _make_result(str(artifacts_dir), final_status="needs_review")
    validation = _make_validation("needs_review")
    engine.notify(result, validation)

    data = json.loads((artifacts_dir / "done.json").read_text())
    assert data["final_status"] == "needs_review"
