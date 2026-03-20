"""
ReportBuilder — Slice 4.

Persists a structured execution report as two artefacts:
  report.json  — machine-readable, complete execution record
  report.md    — human-readable summary

Both files are written to the execution's artifacts directory.
Failure to write is surfaced as an exception so the caller can log it.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

from .runner_models import ReportArtifacts, RunnerExecutionResult, ValidationResult

logger = logging.getLogger(__name__)


class ReportBuilder:
    """Writes report.json and report.md for a completed execution."""

    def build(
        self,
        result: RunnerExecutionResult,
        validation: ValidationResult,
    ) -> ReportArtifacts:
        """Persist the execution report and return paths to both artefacts.

        Args:
            result:     The fully-populated RunnerExecutionResult.
            validation: The ValidationResult produced by ValidationEngine.

        Returns:
            ReportArtifacts with absolute paths to report.json and report.md.

        Raises:
            OSError: if either file cannot be written.
        """
        artifacts_dir = Path(result.artifacts_path)

        json_path = artifacts_dir / "report.json"
        md_path = artifacts_dir / "report.md"

        self._write_json(json_path, result, validation)
        self._write_md(md_path, result, validation)

        logger.info(
            "Report written for execution %s → %s, %s",
            result.execution_id, json_path, md_path,
        )

        return ReportArtifacts(json_path=str(json_path), md_path=str(md_path))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _write_json(
        self,
        path: Path,
        result: RunnerExecutionResult,
        validation: ValidationResult,
    ) -> None:
        data = {
            "execution_id": result.execution_id,
            "final_status": validation.final_status,
            "status": result.status.value,
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
            "modified_files": result.modified_files,
            "test_result": (
                dataclasses.asdict(result.test_result)
                if result.test_result is not None
                else None
            ),
            "validation_result": dataclasses.asdict(validation),
            "error": result.error,
            "summary": result.summary,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _write_md(
        self,
        path: Path,
        result: RunnerExecutionResult,
        validation: ValidationResult,
    ) -> None:
        lines = [
            "# Runner Execution Report",
            "",
            f"**Execution ID:** {result.execution_id}",
            f"**Final Status:** {validation.final_status.upper()}",
            f"**Started:** {result.started_at.isoformat()}",
            f"**Finished:** {result.finished_at.isoformat()}",
            "",
            "## Modified Files",
        ]

        if result.modified_files:
            for f in result.modified_files:
                lines.append(f"- {f}")
        else:
            lines.append("_(none)_")

        lines += ["", "## Test Result"]
        if result.test_result is not None:
            tr = result.test_result
            lines.append(f"Status: {tr.status}")
            if tr.exit_code is not None:
                lines.append(f"Exit code: {tr.exit_code}")
            if tr.duration_ms is not None:
                lines.append(f"Duration: {tr.duration_ms}ms")
            if tr.stdout_path:
                lines.append(f"Stdout: {tr.stdout_path}")
            if tr.stderr_path:
                lines.append(f"Stderr: {tr.stderr_path}")
        else:
            lines.append("_(no tests run)_")

        lines += ["", "## Validation"]
        lines.append(validation.validation_summary)
        if validation.reasons:
            for reason in validation.reasons:
                lines.append(f"- {reason}")

        lines += ["", "## Error"]
        lines.append(result.error if result.error else "_(none)_")

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
