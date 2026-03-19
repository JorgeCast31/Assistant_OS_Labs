"""
OutputPolicy — governed capture, bounding, and classification of execution output.

Design
------
Execution output (stdout/stderr) is distinct from:
  - ExecutionMetadata  (always-persisted system record)
  - ArtifactManifest   (policy-gated files from workspace/out/)

This module governs the I/O streams only.

Output classifications
----------------------
    user-visible    : May be returned to the caller and shown to the user.
    internal-only   : May be stored for internal diagnostics; NOT user-visible.
    blocked         : Must not be persisted anywhere outside runtime memory.
                      Content is suppressed and replaced with an empty string.

Truncation contract
-------------------
If a stream exceeds its policy limit:
  - It is truncated deterministically at the byte boundary.
  - stdout_truncated / stderr_truncated flags are set on OutputRecord.
  - OutputPolicyEngine.apply() returns the affected stream names so the
    caller can emit explicit OutputTruncated audit events.
  - There is NO silent truncation.

Blocked output contract
-----------------------
If a stream's classification is OUTPUT_CLASSIFICATION_BLOCKED:
  - The stored value is replaced with an empty string.
  - stdout_bytes / stderr_bytes still record the original size (for audit).
  - stdout_truncated / stderr_truncated are set to True when content existed
    (the content was "suppressed", which is the strictest form of truncation).
  - to_dict() always returns empty string for blocked streams.

Separation from ArtifactPolicy
-------------------------------
OutputPolicy governs stdout/stderr streams captured at execution time.
ArtifactPolicy governs files written to workspace/out/ during execution.
These two policies operate independently and must not be merged.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Classification constants
# ---------------------------------------------------------------------------

OUTPUT_CLASSIFICATION_USER_VISIBLE = "user-visible"
OUTPUT_CLASSIFICATION_INTERNAL_ONLY = "internal-only"
OUTPUT_CLASSIFICATION_BLOCKED = "blocked"

VALID_CLASSIFICATIONS: frozenset[str] = frozenset({
    OUTPUT_CLASSIFICATION_USER_VISIBLE,
    OUTPUT_CLASSIFICATION_INTERNAL_ONLY,
    OUTPUT_CLASSIFICATION_BLOCKED,
})

# Default per-stream cap (must stay aligned with _MAX_STREAM_CHARS in execution_result.py)
_DEFAULT_MAX_BYTES: int = 8_192  # 8 KB


# ---------------------------------------------------------------------------
# OutputPolicy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OutputPolicy:
    """
    Policy controlling how execution output is captured and classified.

    Fields
    ------
    policy_id               : Identifier for this policy configuration.
    max_stdout_bytes        : Hard cap on captured stdout (chars). Excess is truncated.
    max_stderr_bytes        : Hard cap on captured stderr (chars). Excess is truncated.
    stdout_classification   : "user-visible" | "internal-only" | "blocked"
    stderr_classification   : "user-visible" | "internal-only" | "blocked"
    """

    policy_id: str = "default"
    max_stdout_bytes: int = _DEFAULT_MAX_BYTES
    max_stderr_bytes: int = _DEFAULT_MAX_BYTES
    stdout_classification: str = OUTPUT_CLASSIFICATION_USER_VISIBLE
    stderr_classification: str = OUTPUT_CLASSIFICATION_INTERNAL_ONLY

    def __post_init__(self) -> None:
        if self.stdout_classification not in VALID_CLASSIFICATIONS:
            raise ValueError(
                f"Invalid stdout_classification: {self.stdout_classification!r}. "
                f"Must be one of {sorted(VALID_CLASSIFICATIONS)}"
            )
        if self.stderr_classification not in VALID_CLASSIFICATIONS:
            raise ValueError(
                f"Invalid stderr_classification: {self.stderr_classification!r}. "
                f"Must be one of {sorted(VALID_CLASSIFICATIONS)}"
            )
        if self.max_stdout_bytes < 0:
            raise ValueError("max_stdout_bytes must be non-negative")
        if self.max_stderr_bytes < 0:
            raise ValueError("max_stderr_bytes must be non-negative")

    def to_dict(self) -> dict:
        """Safe for structured logs."""
        return {
            "policy_id": self.policy_id,
            "max_stdout_bytes": self.max_stdout_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
            "stdout_classification": self.stdout_classification,
            "stderr_classification": self.stderr_classification,
        }


# Singleton for the most common case — avoids repeated construction.
DEFAULT_OUTPUT_POLICY: OutputPolicy = OutputPolicy()

# Strict policy: both streams internal-only with tighter caps.
STRICT_OUTPUT_POLICY: OutputPolicy = OutputPolicy(
    policy_id="strict",
    max_stdout_bytes=4_096,
    max_stderr_bytes=4_096,
    stdout_classification=OUTPUT_CLASSIFICATION_INTERNAL_ONLY,
    stderr_classification=OUTPUT_CLASSIFICATION_INTERNAL_ONLY,
)

# Read-only policy: both streams blocked (no output persistence at all).
READONLY_OUTPUT_POLICY: OutputPolicy = OutputPolicy(
    policy_id="readonly",
    max_stdout_bytes=0,
    max_stderr_bytes=0,
    stdout_classification=OUTPUT_CLASSIFICATION_BLOCKED,
    stderr_classification=OUTPUT_CLASSIFICATION_BLOCKED,
)

# Registry of named policies (keyed by policy_id).
OUTPUT_POLICY_REGISTRY: dict[str, OutputPolicy] = {
    "default": DEFAULT_OUTPUT_POLICY,
    "strict": STRICT_OUTPUT_POLICY,
    "readonly": READONLY_OUTPUT_POLICY,
}


# ---------------------------------------------------------------------------
# OutputRecord
# ---------------------------------------------------------------------------

@dataclass
class OutputRecord:
    """
    Governed execution output — the result of applying OutputPolicy to raw streams.

    Unlike bare strings, OutputRecord carries explicit metadata:
      - original stream sizes before truncation/suppression
      - per-stream truncation flags
      - per-stream classifications
      - the policy that governed this output

    Fields
    ------
    stdout                  : Bounded stdout; empty string if blocked.
    stderr                  : Bounded stderr; empty string if blocked.
    stdout_truncated        : True if stdout exceeded policy limit or was blocked.
    stderr_truncated        : True if stderr exceeded policy limit or was blocked.
    stdout_bytes            : Original byte count before any truncation/suppression.
    stderr_bytes            : Original byte count before any truncation/suppression.
    stdout_classification   : Classification of the stdout stream.
    stderr_classification   : Classification of the stderr stream.
    output_policy_id        : ID of the policy that governed this output.
    """

    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_bytes: int
    stderr_bytes: int
    stdout_classification: str
    stderr_classification: str
    output_policy_id: str

    @property
    def truncated(self) -> bool:
        """True if either stream was truncated or suppressed."""
        return self.stdout_truncated or self.stderr_truncated

    def stdout_persistable(self) -> bool:
        """True if stdout may be persisted outside runtime memory."""
        return self.stdout_classification != OUTPUT_CLASSIFICATION_BLOCKED

    def stderr_persistable(self) -> bool:
        """True if stderr may be persisted outside runtime memory."""
        return self.stderr_classification != OUTPUT_CLASSIFICATION_BLOCKED

    def to_dict(self) -> dict:
        """
        Safe for structured logs.

        Blocked streams appear as empty strings — never their suppressed content.
        """
        return {
            "stdout": self.stdout if self.stdout_persistable() else "",
            "stderr": self.stderr if self.stderr_persistable() else "",
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "stdout_classification": self.stdout_classification,
            "stderr_classification": self.stderr_classification,
            "output_policy_id": self.output_policy_id,
            "truncated": self.truncated,
        }


# ---------------------------------------------------------------------------
# OutputPolicyEngine
# ---------------------------------------------------------------------------

class OutputPolicyEngine:
    """
    Stateless transform: applies OutputPolicy to raw stdout/stderr.

    Returns (OutputRecord, truncated_streams) where truncated_streams is a
    list of stream names that were truncated or suppressed.  The caller is
    responsible for emitting audit events for each truncated stream.

    There is no silent truncation — all size reductions are reflected in
    the returned flags and the truncated_streams list.
    """

    @staticmethod
    def apply(
        raw_stdout: str,
        raw_stderr: str,
        policy: OutputPolicy,
    ) -> tuple[OutputRecord, list[str]]:
        """
        Apply policy to raw output streams.

        Parameters
        ----------
        raw_stdout : Raw stdout string from execution backend.
        raw_stderr : Raw stderr string from execution backend.
        policy     : OutputPolicy to enforce.

        Returns
        -------
        (OutputRecord, truncated_streams)
          OutputRecord        — governed output with all metadata.
          truncated_streams   — list of stream names ("stdout", "stderr") that
                                were truncated or suppressed.  Empty if neither
                                stream was altered.
        """
        stdout_bytes = len(raw_stdout)
        stderr_bytes = len(raw_stderr)

        # stdout: apply classification + size cap
        if policy.stdout_classification == OUTPUT_CLASSIFICATION_BLOCKED:
            stdout = ""
            stdout_truncated = stdout_bytes > 0  # suppressed
        else:
            stdout = raw_stdout[: policy.max_stdout_bytes]
            stdout_truncated = stdout_bytes > policy.max_stdout_bytes

        # stderr: apply classification + size cap
        if policy.stderr_classification == OUTPUT_CLASSIFICATION_BLOCKED:
            stderr = ""
            stderr_truncated = stderr_bytes > 0  # suppressed
        else:
            stderr = raw_stderr[: policy.max_stderr_bytes]
            stderr_truncated = stderr_bytes > policy.max_stderr_bytes

        truncated_streams: list[str] = []
        if stdout_truncated:
            truncated_streams.append("stdout")
        if stderr_truncated:
            truncated_streams.append("stderr")

        return OutputRecord(
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
            stdout_classification=policy.stdout_classification,
            stderr_classification=policy.stderr_classification,
            output_policy_id=policy.policy_id,
        ), truncated_streams
