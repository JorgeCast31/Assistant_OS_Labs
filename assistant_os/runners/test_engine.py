"""
TestEngine — Slice 3.

Executes tests inside an isolated workspace using a controlled subprocess.

Risk mitigations:
  1. Shell arbitrary execution   — shell=False always; command is a list, never a string.
  2. Dangerous commands          — whitelist: only pytest-based commands accepted.
  3. Execution outside workspace — cwd=workspace_path enforced; no default cwd.
  4. Infinite / hung tests       — timeout enforced; TimeoutExpired caught and reported.
  5. Untraceable output          — stdout and stderr captured and persisted to disk.
  6. Responsibility mixing       — TestEngine only runs tests; no apply, no file writing outside artifacts.
"""

from __future__ import annotations

import subprocess
import time
import logging
from pathlib import Path
from typing import Any, Dict

from .errors import TestExecutionError
from .policies import DEFAULT_TEST_TIMEOUT, MAX_TIMEOUT, validate_test_spec
from .runner_models import TestExecutionResult
from .workspace_manager import _append_log

logger = logging.getLogger(__name__)

# Artifact file names written alongside runner.log.
_STDOUT_LOG = "test.stdout.log"
_STDERR_LOG = "test.stderr.log"


class TestEngine:
    """Runs tests inside a prepared workspace with strict safety controls."""

    def run_tests(
        self,
        workspace_path: Path,
        test_spec: Dict[str, Any],
        log_file: Path,
    ) -> TestExecutionResult:
        """Execute tests according to *test_spec* inside *workspace_path*.

        Artifacts (stdout, stderr) are written to the same directory as
        *log_file* (i.e. the execution's artifacts directory).

        Returns:
            TestExecutionResult with status "passed", "failed", or "timed_out".

        Raises:
            TestExecutionError: if the spec is invalid or execution cannot start.
        """
        artifacts_dir = log_file.parent
        stdout_path = artifacts_dir / _STDOUT_LOG
        stderr_path = artifacts_dir / _STDERR_LOG

        # --- Validate spec (raises PolicyViolationError on violation) ---
        try:
            validate_test_spec(test_spec)
        except Exception as exc:
            _append_log(log_file, f"test: rejected — {exc}")
            raise TestExecutionError(f"test_spec validation failed: {exc}") from exc

        command = test_spec["command"]
        timeout_sec = float(test_spec.get("timeout_sec") or DEFAULT_TEST_TIMEOUT)
        # Cap at MAX_TIMEOUT as defence-in-depth (validate_test_spec already checked this).
        timeout_sec = min(timeout_sec, MAX_TIMEOUT)

        _append_log(log_file, "phase: TEST_START")
        _append_log(log_file, f"test: command accepted — {command!r}")
        _append_log(log_file, "test: running")

        start = time.monotonic()

        try:
            proc = subprocess.run(
                command,
                shell=False,                     # Risk 1: never invoke shell
                cwd=str(workspace_path),         # Risk 3: enforce workspace cwd
                capture_output=True,             # Risk 5: capture all output
                text=True,
                timeout=timeout_sec,             # Risk 4: bound execution time
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            # Persist whatever partial output was captured before timeout.
            _persist(stdout_path, getattr(exc, "stdout", "") or "")
            _persist(stderr_path, getattr(exc, "stderr", "") or "")
            _append_log(log_file, f"test: timed_out after {timeout_sec}s")
            _append_log(log_file, "phase: TEST_DONE")
            return TestExecutionResult(
                status="timed_out",
                command=command,
                duration_ms=duration_ms,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )
        except (OSError, FileNotFoundError) as exc:
            _append_log(log_file, f"test: error — cannot start process: {exc}")
            _append_log(log_file, "phase: TEST_DONE")
            raise TestExecutionError(f"Cannot start test command {command!r}: {exc}") from exc

        duration_ms = int((time.monotonic() - start) * 1000)

        _persist(stdout_path, proc.stdout or "")
        _persist(stderr_path, proc.stderr or "")

        status = "passed" if proc.returncode == 0 else "failed"
        _append_log(log_file, f"test: {status} (exit_code={proc.returncode}, {duration_ms}ms)")
        _append_log(log_file, "phase: TEST_DONE")

        logger.info(
            "TestEngine: %s | cmd=%r | exit=%d | %dms",
            status, command, proc.returncode, duration_ms,
        )

        return TestExecutionResult(
            status=status,
            command=command,
            exit_code=proc.returncode,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            duration_ms=duration_ms,
        )


def _persist(path: Path, content: str) -> None:
    """Write *content* to *path*, silently skipping on IO failure."""
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write %s: %s", path, exc)
