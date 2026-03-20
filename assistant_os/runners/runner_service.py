"""
RunnerService — Slice 4.

Orchestrates the full Runner pipeline:
    preflight → workspace → apply → test → validate → report → notify → result

Design notes:
  - Only pre-workspace failures return early (no artifacts dir to write to).
  - Apply and test errors do NOT return early — they accumulate state and the
    loop always closes through validation → report → notify.
  - All phases after workspace are wrapped individually so a failure in
    (e.g.) report cannot destroy the test result already captured.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .apply_engine import ApplyEngine
from .errors import (
    ApplyError,
    PolicyViolationError,
    PreflightError,
    TestExecutionError,
    WorkspacePreparationError,
)
from .notification_engine import NotificationEngine
from .report_builder import ReportBuilder
from .runner_models import (
    RunnerExecutionRequest,
    RunnerExecutionResult,
    RunnerExecutionStatus,
    TestExecutionResult,
    ValidationResult,
)
from .test_engine import TestEngine
from .validation_engine import ValidationEngine
from .workspace_manager import PreparedWorkspace, _append_log, log_preflight_failure, prepare_workspace

logger = logging.getLogger(__name__)


class RunnerService:
    """Orchestrator for the full Runner pipeline (Slice 4)."""

    def run(self, request: RunnerExecutionRequest) -> RunnerExecutionResult:
        """Execute the complete Slice 4 pipeline for *request*.

        Flow:
            1. Preflight validation.
            2. Workspace preparation.
            3. Apply changes (if request.changes).
            4. Run tests (if request.test_spec and apply succeeded).
            5. Validate final state.
            6. Build report.
            7. Notify.
            8. Return complete result.
        """
        started_at = datetime.now(timezone.utc)

        # ------------------------------------------------------------------
        # Phase 1: workspace (only early-return path — no artifacts dir yet)
        # ------------------------------------------------------------------
        try:
            self._preflight(request)
            workspace: PreparedWorkspace = prepare_workspace(request)
        except (PreflightError, PolicyViolationError, WorkspacePreparationError) as exc:
            return self._fail(request, started_at, str(exc))
        except Exception as exc:
            logger.exception("Unexpected error during workspace preparation")
            return self._fail(request, started_at, f"Internal error: {exc}")

        log_file = Path(workspace.artifacts_path) / "runner.log"
        workspace_path = Path(workspace.workspace_path)

        # ------------------------------------------------------------------
        # Phase 2: apply
        # ------------------------------------------------------------------
        modified_files: List[str] = []
        apply_error: Optional[str] = None

        if request.changes:
            _append_log(log_file, "phase: APPLY_START")
            try:
                modified_files = ApplyEngine().apply_changes(
                    workspace_path=workspace_path,
                    changes=request.changes,
                    log_file=log_file,
                )
                _append_log(log_file, "phase: APPLY_DONE")
            except (ApplyError, PolicyViolationError) as exc:
                apply_error = str(exc)
                _append_log(log_file, f"phase: APPLY_FAILED → {exc}")
            except Exception as exc:
                apply_error = f"Internal error: {exc}"
                _append_log(log_file, f"phase: APPLY_FAILED → internal error: {exc}")
                logger.exception("Unexpected error during apply phase")

        # ------------------------------------------------------------------
        # Phase 3: test (skipped if apply failed)
        # ------------------------------------------------------------------
        test_result: Optional[TestExecutionResult] = None
        test_error: Optional[str] = None

        if apply_error is None and request.test_spec:
            try:
                test_result = TestEngine().run_tests(
                    workspace_path=workspace_path,
                    test_spec=request.test_spec,
                    log_file=log_file,
                )
                # TEST_DONE is logged by TestEngine itself.
            except (TestExecutionError, PolicyViolationError) as exc:
                test_error = str(exc)
                _append_log(log_file, f"phase: TEST_DONE (error: {exc})")
            except Exception as exc:
                test_error = f"Internal error: {exc}"
                _append_log(log_file, f"phase: TEST_DONE (internal error: {exc})")
                logger.exception("Unexpected error during test phase")

        # ------------------------------------------------------------------
        # Build intermediate result (passed through to V/R/N)
        # ------------------------------------------------------------------
        error_message = apply_error or test_error
        intermediate_status = (
            RunnerExecutionStatus.FAILED
            if error_message
            else self._determine_status(modified_files, test_result)
        )
        summary = self._build_summary(intermediate_status, modified_files, test_result)

        finished_at = datetime.now(timezone.utc)
        result = RunnerExecutionResult(
            execution_id=request.execution_id,
            status=intermediate_status,
            started_at=started_at,
            finished_at=finished_at,
            workspace_path=workspace.workspace_path,
            artifacts_path=workspace.artifacts_path,
            modified_files=modified_files,
            test_result=test_result,
            error=error_message,
            summary=summary,
        )

        # ------------------------------------------------------------------
        # Phase 4: validation (always runs when a workspace exists)
        # ------------------------------------------------------------------
        _append_log(log_file, "phase: VALIDATION_START")
        validation: Optional[ValidationResult] = None
        try:
            validation = ValidationEngine().validate(result, request.validation_spec)
            result.validation_result = validation
            result.final_status = validation.final_status
            _append_log(log_file, f"phase: VALIDATION_DONE → {validation.final_status}")
        except Exception as exc:
            _append_log(log_file, f"validation: error → {exc}")
            logger.exception("Unexpected error during validation phase")
            result.final_status = result.final_status or "failed"

        # Fallback validation for report/notify if validation itself failed.
        if validation is None:
            validation = ValidationResult(
                final_status=result.final_status or "failed",
                reasons=["Validation phase failed due to an internal error."],
                validation_summary="Validation unavailable.",
            )

        # ------------------------------------------------------------------
        # Phase 5: report
        # ------------------------------------------------------------------
        _append_log(log_file, "phase: REPORT_START")
        try:
            report = ReportBuilder().build(result, validation)
            result.report_json_path = report.json_path
            result.report_md_path = report.md_path
            _append_log(log_file, "phase: REPORT_DONE")
        except Exception as exc:
            _append_log(log_file, f"report: error → {exc}")
            logger.exception("Unexpected error during report phase")

        # ------------------------------------------------------------------
        # Phase 6: notify
        # ------------------------------------------------------------------
        _append_log(log_file, "phase: NOTIFY_START")
        try:
            notif = NotificationEngine().notify(result, validation)
            result.notification_path = notif.notification_path
            _append_log(log_file, "phase: NOTIFY_DONE")
        except Exception as exc:
            _append_log(log_file, f"notify: error → {exc}")
            logger.warning("Notification error (non-fatal): %s", exc)

        # ------------------------------------------------------------------
        # Persist final metadata and return
        # ------------------------------------------------------------------
        self._write_final_metadata(workspace.artifacts_path, result)
        _append_log(
            log_file,
            f"status: {intermediate_status.value} | final: {result.final_status}",
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _preflight(self, request: RunnerExecutionRequest) -> None:
        if not request.execution_id or not request.execution_id.strip():
            raise PreflightError("execution_id must not be empty.")
        # Prevent path traversal: execution_id becomes a directory name under
        # var/runner/executions/. Reject any value that could escape that base.
        if (
            ".." in request.execution_id
            or "/" in request.execution_id
            or "\\" in request.execution_id
        ):
            raise PreflightError(
                f"execution_id contains invalid characters (path separators or '..' not allowed): "
                f"{request.execution_id!r}"
            )
        if not request.repo_path or not request.repo_path.strip():
            raise PreflightError("repo_path must not be empty.")

    def _determine_status(
        self,
        modified_files: List[str],
        test_result: Optional[TestExecutionResult],
    ) -> RunnerExecutionStatus:
        if test_result is not None:
            if test_result.status == "passed":
                return RunnerExecutionStatus.TESTS_PASSED
            elif test_result.status == "timed_out":
                return RunnerExecutionStatus.FAILED
            else:
                return RunnerExecutionStatus.TESTS_FAILED
        if modified_files:
            return RunnerExecutionStatus.CHANGES_APPLIED
        return RunnerExecutionStatus.WORKSPACE_READY

    def _build_summary(
        self,
        status: RunnerExecutionStatus,
        modified_files: List[str],
        test_result: Optional[TestExecutionResult],
    ) -> str:
        if test_result is not None:
            duration = f"{test_result.duration_ms}ms" if test_result.duration_ms is not None else "N/A"
            return (
                f"Tests {test_result.status}. "
                f"{len(modified_files)} file(s) modified. "
                f"Duration: {duration}."
            )
        if modified_files:
            return f"Applied {len(modified_files)} file(s): {modified_files}."
        return "Workspace prepared. No changes applied."

    def _fail(
        self,
        request: RunnerExecutionRequest,
        started_at: datetime,
        error_message: str,
    ) -> RunnerExecutionResult:
        """Return a FAILED result for pre-workspace failures (no artifacts dir)."""
        finished_at = datetime.now(timezone.utc)
        logger.error("Runner execution %s FAILED: %s", request.execution_id, error_message)
        log_preflight_failure(
            execution_id=request.execution_id,
            repo_path=request.repo_path,
            error=error_message,
        )
        return RunnerExecutionResult(
            execution_id=request.execution_id,
            status=RunnerExecutionStatus.FAILED,
            final_status="failed",
            started_at=started_at,
            finished_at=finished_at,
            error=error_message,
            summary=f"Execution failed: {error_message}",
        )

    def _write_final_metadata(self, artifacts_path: str, result: RunnerExecutionResult) -> None:
        metadata_file = Path(artifacts_path) / "metadata.json"
        if not metadata_file.exists():
            return

        try:
            data = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}

        data.update(
            {
                "execution_id": result.execution_id,
                "status": result.status.value,
                "final_status": result.final_status,
                "started_at": result.started_at.isoformat(),
                "finished_at": result.finished_at.isoformat(),
                "error": result.error,
                "summary": result.summary,
                "modified_files": result.modified_files,
                "test_result": (
                    dataclasses.asdict(result.test_result)
                    if result.test_result is not None
                    else None
                ),
                "validation_result": (
                    dataclasses.asdict(result.validation_result)
                    if result.validation_result is not None
                    else None
                ),
                "report_json_path": result.report_json_path,
                "report_md_path": result.report_md_path,
                "notification_path": result.notification_path,
            }
        )

        try:
            metadata_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not update metadata.json: %s", exc)
