"""
ContainerBackend — Docker-based ephemeral execution backend.

Security model
--------------
- One container per execution, auto-removed on exit (--rm).
- Network completely disabled (--network none).
- Memory and CPU capped to prevent resource exhaustion.
- PID namespace limited (--pids-limit) to prevent fork-bomb attacks.
- Root filesystem is read-only (--read-only); only /tmp and /workspace are writable.
- Container runs as UID 65534 (nobody) — non-root, no privilege escalation.
- Only the workspace directory is mounted; host filesystem is inaccessible.
- stdout/stderr truncated at _MAX_STREAM_CHARS each.

Execution paths
---------------
When abort_signal is None (default):
  - Uses subprocess.run() with a hard timeout (simple, backward-compatible path).
  - Container is stopped via docker stop on TimeoutExpired.

When abort_signal is provided (revocation-aware path):
  - Uses subprocess.Popen() with a polling loop (_POLL_INTERVAL_S).
  - Polls abort_signal on every iteration; stops container immediately when set.
  - Also enforces timeout via deadline comparison.

Error handling
--------------
- Docker not found → ExecutionResult(ok=False, error="Docker not found...")
- Timeout          → ExecutionResult(timed_out=True, exit_code=-1)
- Abort signal     → ExecutionResult(error="Execution aborted — revocation signal")
- Non-zero exit    → ExecutionResult(ok=False) with stderr populated
"""

from __future__ import annotations

import subprocess
import threading
import time
import uuid
from typing import Optional

from .execution_backend import ExecutionBackend
from .execution_result import ExecutionResult
from .workspace_model import WorkspaceModel

# Per-stream output cap (8 KB).  Prevents unbounded output from reaching callers.
_MAX_STREAM_CHARS: int = 8_192

# Seconds to wait when stopping a timed-out or aborted container.
_STOP_TIMEOUT_S: int = 10

# Default PID limit per container.
_DEFAULT_PIDS_LIMIT: int = 64

# Default UID for non-root container execution (nobody).
_CONTAINER_UID: str = "65534"

# Poll interval for the abort-aware Popen path (seconds).
_POLL_INTERVAL_S: float = 0.2

# Error message for aborted executions — does not include any secret values.
_ABORT_ERROR_MSG: str = "Execution aborted — revocation signal received"


def _truncate(text: str, max_chars: int = _MAX_STREAM_CHARS) -> tuple[str, bool]:
    """Return (text, was_truncated).  Appends a notice if truncated."""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n... (output truncated)", True


class ContainerBackend(ExecutionBackend):
    """
    Docker-based execution backend.

    Each call to execute() spins up a fresh ephemeral container,
    runs the entry point script, captures output, and destroys the container.

    Parameters
    ----------
    base_image   : Docker image tag.  Must be a pre-pulled, fixed image.
    memory_limit : Docker --memory value (e.g. "128m").
    cpu_limit    : Docker --cpus value (e.g. "0.5").
    pids_limit   : Docker --pids-limit value.  Prevents fork-bomb attacks.
    """

    def __init__(
        self,
        base_image: str = "python:3.11-slim",
        memory_limit: str = "128m",
        cpu_limit: str = "0.5",
        pids_limit: int = _DEFAULT_PIDS_LIMIT,
    ) -> None:
        self._base_image = base_image
        self._memory_limit = memory_limit
        self._cpu_limit = cpu_limit
        self._pids_limit = pids_limit

    # ------------------------------------------------------------------
    # ExecutionBackend interface
    # ------------------------------------------------------------------

    def prepare(self, workspace_path: str) -> None:
        """No-op: containers are created fresh on each execute() call."""

    def execute(
        self,
        workspace_path: str,
        entry_point: str = "main.py",
        timeout_seconds: int = 30,
        env_file: str = "",
        abort_signal: Optional[threading.Event] = None,
        container_name: str = "",
    ) -> ExecutionResult:
        """
        Run entry_point inside an ephemeral Docker container.

        When abort_signal is provided, uses the Popen-based abort-aware path.
        When abort_signal is None, uses the simpler subprocess.run path.

        Parameters
        ----------
        env_file       : path to Docker --env-file (secret injection, optional).
        abort_signal   : threading.Event set by RevocationManager to abort.
        container_name : pre-generated container name from RunnerAPI (optional).
        """
        if not container_name:
            container_name = f"assistantos-runner-{uuid.uuid4().hex[:12]}"

        cmd = self._build_docker_cmd(container_name, workspace_path, entry_point, env_file)

        # Choose execution path based on whether abort control is needed.
        if abort_signal is not None:
            raw = self._run_popen(cmd, container_name, timeout_seconds, abort_signal)
        else:
            raw = self._run_blocking(cmd, container_name, timeout_seconds)

        # Early-return for infrastructure errors (Docker not found, etc.)
        if "error" in raw and raw.get("exit_code") is None:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=0,
                truncated=False,
                apply_mode="real",
                timed_out=False,
                error=raw["error"],
            )

        stdout, stdout_cut = _truncate(raw.get("stdout_raw", ""))
        stderr, stderr_cut = _truncate(raw.get("stderr_raw", ""))

        # Only collect artifacts when execution actually ran (not aborted before start)
        artifacts = WorkspaceModel(workspace_path).list_artifacts()

        return ExecutionResult(
            exit_code=raw.get("exit_code", -1),
            stdout=stdout,
            stderr=stderr,
            duration_ms=raw.get("duration_ms", 0),
            truncated=stdout_cut or stderr_cut,
            artifacts=artifacts,
            apply_mode="real",
            timed_out=raw.get("timed_out", False),
            error=raw.get("abort_error"),
        )

    def cleanup(self, workspace_path: str) -> None:
        """
        No-op: --rm ensures the container is auto-removed on exit.
        Workspace sub-directory cleanup is handled by WorkspaceModel.
        """

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    def _run_blocking(
        self,
        cmd: list[str],
        container_name: str,
        timeout_seconds: int,
    ) -> dict:
        """
        Original subprocess.run path — backward-compatible, no abort support.
        Used when abort_signal is None.
        """
        start_ns = time.monotonic_ns()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            return {
                "stdout_raw": proc.stdout or "",
                "stderr_raw": proc.stderr or "",
                "exit_code": proc.returncode,
                "timed_out": False,
                "duration_ms": (time.monotonic_ns() - start_ns) // 1_000_000,
            }
        except subprocess.TimeoutExpired:
            self._stop_container(container_name)
            return {
                "stdout_raw": "",
                "stderr_raw": f"Execution timed out after {timeout_seconds}s",
                "exit_code": -1,
                "timed_out": True,
                "duration_ms": (time.monotonic_ns() - start_ns) // 1_000_000,
            }
        except FileNotFoundError:
            return {
                "error": (
                    "Docker not found on this host. "
                    "Install Docker to use ContainerBackend."
                ),
            }

    def _run_popen(
        self,
        cmd: list[str],
        container_name: str,
        timeout_seconds: int,
        abort_signal: threading.Event,
    ) -> dict:
        """
        Abort-aware execution path using Popen + polling.
        Used when abort_signal is not None.

        Polls abort_signal every _POLL_INTERVAL_S seconds.
        When set, calls docker stop immediately, then drains output.
        """
        start_ns = time.monotonic_ns()
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            return {
                "error": (
                    "Docker not found on this host. "
                    "Install Docker to use ContainerBackend."
                ),
            }

        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        aborted = False

        # Poll until process exits, abort is signalled, or timeout is reached.
        while proc.poll() is None:
            if abort_signal.is_set():
                aborted = True
                self._stop_container(container_name)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                self._stop_container(container_name)
                break
            time.sleep(_POLL_INTERVAL_S)

        # Drain stdout/stderr (bounded by communicate's implicit buffer).
        try:
            stdout_raw, stderr_raw = proc.communicate(timeout=_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_raw, stderr_raw = proc.communicate()

        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        exit_code = proc.returncode if proc.returncode is not None else -1

        result: dict = {
            "stdout_raw": stdout_raw or "",
            "stderr_raw": stderr_raw or "",
            "exit_code": exit_code,
            "timed_out": timed_out,
            "duration_ms": duration_ms,
        }

        if aborted:
            result["exit_code"] = -1
            result["abort_error"] = _ABORT_ERROR_MSG

        return result

    # ------------------------------------------------------------------
    # Docker command builder
    # ------------------------------------------------------------------

    def _build_docker_cmd(
        self,
        container_name: str,
        workspace_path: str,
        entry_point: str,
        env_file: str = "",
    ) -> list[str]:
        # Platform note (Windows):
        # workspace_path is a host absolute path (e.g. C:\Users\...).
        # Docker Desktop on Windows translates Windows drive paths in -v bind mounts
        # automatically (C:\foo → /c/foo inside the VM).  This relies on Docker
        # Desktop's path-translation layer and is NOT a portable Docker Engine
        # feature.  On bare Linux Docker Engine, workspace_path must be a POSIX path.
        # If Docker Desktop is not available on Windows, bind mounts with Windows
        # drive-letter paths will fail with a "invalid bind mount spec" error.
        # The same applies to env_file paths below.
        cmd = [
            "docker", "run",
            "--rm",
            "--name", container_name,
            "--network", "none",
            "--memory", self._memory_limit,
            "--memory-swap", self._memory_limit,
            "--cpus", self._cpu_limit,
            "--pids-limit", str(self._pids_limit),
            "--user", _CONTAINER_UID,
            "--read-only",
            "--tmpfs", "/tmp:size=64m,exec",
            "-v", f"{workspace_path}:/workspace:rw",
            "--workdir", "/workspace/input",
        ]
        # Inject secrets via --env-file (keeps values out of argv / ps aux).
        if env_file:
            cmd.extend(["--env-file", env_file])
        cmd.extend([self._base_image, "python", entry_point])
        return cmd

    @staticmethod
    def _stop_container(container_name: str) -> None:
        """Best-effort container stop.  Never raises."""
        try:
            subprocess.run(
                ["docker", "stop", container_name],
                capture_output=True,
                timeout=_STOP_TIMEOUT_S,
            )
        except Exception:  # noqa: BLE001
            pass
