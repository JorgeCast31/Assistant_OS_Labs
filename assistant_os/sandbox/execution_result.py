"""
ExecutionResult — structured output from a single sandbox execution.

All executions produce an ExecutionResult regardless of success or failure.
stdout/stderr are always bounded by _MAX_STREAM_CHARS to prevent unbounded
output reaching callers.

Separation of concerns
-----------------------
ExecutionMetadata  — always-persisted system record; describes the execution
                     event itself (ids, timing, exit status, policy binding).
ArtifactManifest   — policy-gated; lists accepted artifact files from out/.
OutputRecord       — governed I/O streams with explicit classification metadata.
ExecutionResult    — runtime envelope; carries I/O streams + all of the above.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..output.models import InspectionResult
    from .artifact_policy import ArtifactManifest
    from .output_policy import OutputRecord

# Hard cap per stream — prevents unbounded output from reaching callers.
_MAX_STREAM_CHARS: int = 8_192   # 8 KB


@dataclass
class ExecutionMetadata:
    """
    Always-persisted execution metadata (non-artifact).

    This record is persisted for every execution regardless of outcome.
    It contains no user-generated content — only system-level facts.

    Fields
    ------
    execution_id         : Unique execution request ID (from AuthorizedPlan, or "").
    plan_id              : Plan that authorized the execution (or "").
    policy_id            : Policy that governed the execution (or "").
    authorized_plan_hash : Hash of the AuthorizedPlan that was validated (or "").
    delegated_seat_ref   : Delegated MSO seat ref associated with the plan, if any.
    runtime_profile      : Runtime used (e.g. "python3.11").
    duration_ms          : Wall-clock execution time in milliseconds.
    exit_code            : Process exit code (-1 for internal errors / timeout).
    timed_out            : Whether execution was killed due to timeout.
    truncated            : Whether stdout or stderr was truncated.
    backend              : Class name of the execution backend used.
    status               : Final ExecutionStatus value (completed/failed/aborted).
    termination_reason   : Final TerminationReason value.
    container_id         : Container name or identifier (empty if not applicable).
    stdout_bytes         : Original stdout byte count before truncation/suppression.
    stderr_bytes         : Original stderr byte count before truncation/suppression.
    artifact_count       : Number of accepted artifacts from workspace/out/.
    """

    execution_id: str
    plan_id: str
    policy_id: str
    runtime_profile: str
    duration_ms: int
    exit_code: int
    timed_out: bool
    truncated: bool
    authorized_plan_hash: str = ""
    delegated_seat_ref: str = ""
    # --- fields populated by RunnerAPI at execution completion ---
    backend: str = ""            # execution backend class name
    status: str = ""             # final ExecutionStatus value
    termination_reason: str = "" # final TerminationReason value
    container_id: str = ""       # container name / identifier
    stdout_bytes: int = 0        # original stdout size before any truncation
    stderr_bytes: int = 0        # original stderr size before any truncation
    artifact_count: int = 0      # number of accepted artifacts (from manifest)

    def to_dict(self) -> dict:
        """Serialise to plain dict (safe for JSON / ToolResult.data)."""
        return {
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "policy_id": self.policy_id,
            "authorized_plan_hash": self.authorized_plan_hash,
            "delegated_seat_ref": self.delegated_seat_ref,
            "runtime_profile": self.runtime_profile,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "backend": self.backend,
            "status": self.status,
            "termination_reason": self.termination_reason,
            "container_id": self.container_id,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "artifact_count": self.artifact_count,
        }


@dataclass
class ExecutionResult:
    """
    Structured output from a single container execution.

    Fields
    ------
    exit_code   : int                          — 0 = success; -1 = internal error
    stdout      : str                          — captured stdout (may be truncated)
    stderr      : str                          — captured stderr (may be truncated)
    duration_ms : int                          — wall-clock time in milliseconds
    truncated   : bool                         — True if stdout OR stderr was cut
    artifacts   : list[str]                    — relative paths from workspace root
    apply_mode  : str                          — "stub" | "real"
    timed_out   : bool                         — True if killed due to timeout
    error       : str | None                   — internal runner error (not stderr)
    metadata    : ExecutionMetadata | None     — always-persisted system record
    manifest    : ArtifactManifest | None      — policy-gated artifact manifest
    """

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool
    artifacts: list[str] = field(default_factory=list)
    apply_mode: str = "real"
    timed_out: bool = False
    error: Optional[str] = None
    metadata: Optional["ExecutionMetadata"] = field(default=None, repr=False)
    manifest: Optional[object] = field(default=None, repr=False)   # ArtifactManifest
    output_record: Optional["OutputRecord"] = field(default=None, repr=False)
    inspection_result: Optional["InspectionResult"] = field(default=None, repr=False)
    persisted_stdout: Optional[str] = field(default=None, repr=False)
    persisted_stderr: Optional[str] = field(default=None, repr=False)
    persistence_mode: str = "raw"
    was_redacted: bool = False

    @classmethod
    def make_internal_error(cls, error: str = "internal backend error") -> "ExecutionResult":
        """
        Factory for normalized infrastructure failure results.

        Used by RunnerAPI when backend.execute() raises an unhandled exception.
        This produces a structurally complete ExecutionResult with safe defaults
        so callers always receive a coherent outcome, even on hard backend failures.

        Fields
        ------
        exit_code   : -1   (indicates infrastructure failure, not sandbox exit)
        stdout/err  : ""   (nothing captured — backend never ran to completion)
        duration_ms : 0    (unknown — backend never returned timing)
        truncated   : False
        error       : caller-supplied description (typically exc type + message)
        """
        return cls(
            exit_code=-1,
            stdout="",
            stderr="",
            duration_ms=0,
            truncated=False,
            error=error,
        )

    @property
    def ok(self) -> bool:
        """True iff execution completed without timeout, exited 0, no runner error."""
        return not self.timed_out and self.exit_code == 0 and self.error is None

    def to_dict(self) -> dict:
        """Serialise to plain dict for ToolResult.data compatibility."""
        d: dict = {
            "apply_mode": self.apply_mode,
            "exit_code": self.exit_code,
            "stdout": self.persisted_stdout if self.persisted_stdout is not None else self.stdout,
            "stderr": self.persisted_stderr if self.persisted_stderr is not None else self.stderr,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
            "artifacts": list(self.artifacts),
            "timed_out": self.timed_out,
            "error": self.error,
            "ok": self.ok,
            "persistence_mode": self.persistence_mode,
            "was_redacted": self.was_redacted,
        }
        if self.metadata is not None:
            d["metadata"] = self.metadata.to_dict()
        if self.manifest is not None:
            d["manifest"] = self.manifest.to_dict()
        if self.output_record is not None:
            d["output_record"] = self.output_record.to_dict()
        if self.inspection_result is not None:
            d["inspection_result"] = self.inspection_result.to_dict()
        return d
