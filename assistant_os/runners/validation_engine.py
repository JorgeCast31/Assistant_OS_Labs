"""
ValidationEngine — Slice 4.

Evaluates the accumulated execution state and emits a final decision:
  success      — execution completed successfully with all requirements met
  failed       — a hard error, test failure, or unmet strict requirement
  needs_review — execution completed without fatal error but lacks sufficient
                 evidence to declare success automatically

Decision tree (in priority order):
  1. Test timed out or explicitly failed          → failed
  2. Runner reported an error or hard failure     → failed
  2.5 Sandbox execution completed (exit_code=0)  → success
  3. Spec requirement unmet + strict mode         → failed
  4. Spec requirement unmet + review allowed      → needs_review
  5. Tests passed                                 → success
  6. Changes applied but no tests run             → needs_review / failed
  7. Nothing done (workspace only)                → needs_review / failed

No external I/O. Pure function over the result + spec.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .runner_models import RunnerExecutionResult, RunnerExecutionStatus, ValidationResult

logger = logging.getLogger(__name__)


class ValidationEngine:
    """Classifies a RunnerExecutionResult into a final decision."""

    def validate(
        self,
        result: RunnerExecutionResult,
        validation_spec: Optional[object],
    ) -> ValidationResult:
        """Evaluate *result* against *validation_spec* and return a ValidationResult.

        Args:
            result:          The partially-built RunnerExecutionResult after all
                             execution phases have been attempted.
            validation_spec: Optional dict with keys:
                               require_tests (bool)   — tests must have run and passed
                               require_changes (bool) — at least one file must be modified
                               allow_needs_review (bool, default True) — whether the
                                 "needs_review" outcome is acceptable; if False, ambiguous
                                 cases are classified as "failed" instead

        Returns:
            ValidationResult with final_status, reasons, and validation_summary.
        """
        spec = validation_spec if isinstance(validation_spec, dict) else {}
        require_tests: bool = bool(spec.get("require_tests", False))
        require_changes: bool = bool(spec.get("require_changes", False))
        allow_needs_review: bool = bool(spec.get("allow_needs_review", True))

        reasons: List[str] = []

        # ------------------------------------------------------------------
        # 1. Explicit test failure or timeout (most specific signal)
        # ------------------------------------------------------------------
        if result.test_result is not None:
            if result.test_result.status == "timed_out":
                reasons.append("Tests timed out.")
                return self._result("failed", reasons)
            if result.test_result.status == "failed":
                reasons.append(f"Tests failed (exit code {result.test_result.exit_code}).")
                return self._result("failed", reasons)

        # ------------------------------------------------------------------
        # 2. Hard runner error or explicit FAILED intermediate status
        # ------------------------------------------------------------------
        if result.error:
            reasons.append(f"Runner error: {result.error}")
            return self._result("failed", reasons)

        if result.status == RunnerExecutionStatus.FAILED:
            reasons.append("Execution failed at an earlier phase.")
            return self._result("failed", reasons)

        # ------------------------------------------------------------------
        # 2.5. Sandbox execution completed successfully
        # ------------------------------------------------------------------
        if (
            result.sandbox_metadata is not None
            and result.sandbox_metadata.get("status") == "completed"
            and result.sandbox_metadata.get("exit_code") == 0
        ):
            reasons.append("Sandbox code execution completed successfully.")
            if result.modified_files:
                reasons.append(f"{len(result.modified_files)} file(s) modified.")
            return self._result("success", reasons)

        # ------------------------------------------------------------------
        # 3 & 4. Spec requirement violations
        # ------------------------------------------------------------------
        unmet: List[str] = []

        if require_tests and result.test_result is None:
            unmet.append("require_tests=True but no tests were run.")

        if require_changes and not result.modified_files:
            unmet.append("require_changes=True but no files were modified.")

        if unmet:
            reasons.extend(unmet)
            if allow_needs_review:
                return self._result("needs_review", reasons)
            else:
                return self._result("failed", reasons)

        # ------------------------------------------------------------------
        # 5. Clear positive signal — tests passed
        # ------------------------------------------------------------------
        if result.test_result is not None and result.test_result.status == "passed":
            reasons.append("Tests passed.")
            if result.modified_files:
                reasons.append(f"{len(result.modified_files)} file(s) modified.")
            return self._result("success", reasons)

        # ------------------------------------------------------------------
        # 6. Changes applied but no tests run
        # ------------------------------------------------------------------
        if result.modified_files and result.test_result is None:
            reasons.append(
                f"{len(result.modified_files)} file(s) modified but no tests run "
                "— cannot confirm success automatically."
            )
            if allow_needs_review:
                return self._result("needs_review", reasons)
            else:
                return self._result("failed", reasons)

        # ------------------------------------------------------------------
        # 7. Nothing meaningful happened
        # ------------------------------------------------------------------
        reasons.append("Execution completed with no changes and no tests run.")
        if allow_needs_review:
            return self._result("needs_review", reasons)
        else:
            return self._result("failed", reasons)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _result(final_status: str, reasons: List[str]) -> ValidationResult:
        summary = f"Outcome: {final_status}. " + " ".join(reasons)
        return ValidationResult(
            final_status=final_status,
            reasons=reasons,
            validation_summary=summary,
        )
