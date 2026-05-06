"""
assistant_os.output.persistence_policy
---------------------------------------
Governs what version of execution output is persisted after inspection.

The key invariant: persistence != mirror of raw output.
After inspection, the system decides which form of the output to keep
based on its classification.

Rules (MVP)
-----------
    safe      → persist raw output unchanged
    warning   → persist raw output (flagged in metadata)
    sensitive → persist ONLY the redacted form (secrets replaced with [REDACTED])
    invalid   → persist truncated redacted form (first _TRUNCATION_LIMIT chars)
    None      → persist raw output (no inspection available — safe fallback)

PersistenceDecision
-------------------
Immutable result of decide_persistence().  Carries the governed stdout/stderr
that callers should actually persist, plus mode metadata.

decide_persistence()
--------------------
Pure function — no side effects, no I/O.  Returns a PersistenceDecision.
All exceptions are swallowed at the call site in runner_api.py so they can
never block execution result delivery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import InspectionResult

# ---------------------------------------------------------------------------
# Persistence mode constants
# ---------------------------------------------------------------------------

PERSIST_MODE_RAW       = "raw"        # original output stored unchanged
PERSIST_MODE_REDACTED  = "redacted"   # sensitive patterns replaced with [REDACTED]
PERSIST_MODE_TRUNCATED = "truncated"  # invalid output capped at _TRUNCATION_LIMIT chars

# Maximum chars to retain for invalid (binary/garbage) output.
# Enough to show the user what happened without storing large binary blobs.
_TRUNCATION_LIMIT: int = 2_048


# ---------------------------------------------------------------------------
# PersistenceDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PersistenceDecision:
    """
    Immutable result of decide_persistence().

    Fields
    ------
    stdout        : governed stdout — the form callers should persist / expose
    stderr        : governed stderr — the form callers should persist / expose
    mode          : "raw" | "redacted" | "truncated"
    was_redacted  : True iff sensitive patterns were replaced with [REDACTED]
    was_truncated : True iff output was shortened due to invalid classification
    """

    stdout: str
    stderr: str
    mode: str
    was_redacted: bool
    was_truncated: bool

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "was_redacted": self.was_redacted,
            "was_truncated": self.was_truncated,
            # stdout/stderr intentionally NOT included — callers own the streams
        }


# ---------------------------------------------------------------------------
# decide_persistence
# ---------------------------------------------------------------------------


def decide_persistence(
    stdout: str,
    stderr: str,
    inspection_result: "InspectionResult | None",
) -> PersistenceDecision:
    """
    Decide what form of stdout/stderr to persist, based on inspection_result.

    Parameters
    ----------
    stdout            : raw captured stdout from the sandbox
    stderr            : raw captured stderr from the sandbox
    inspection_result : output of OutputInspector.inspect(), or None

    Returns
    -------
    PersistenceDecision with governed streams and mode metadata.

    This function never raises.  Callers should wrap it in try/except as a
    belt-and-suspenders guard, but it handles all edge cases internally.
    """
    # No inspection result → safe fallback, persist as-is
    if inspection_result is None:
        return PersistenceDecision(
            stdout=stdout,
            stderr=stderr,
            mode=PERSIST_MODE_RAW,
            was_redacted=False,
            was_truncated=False,
        )

    classification = inspection_result.classification

    # safe / warning → raw (warning is flagged via inspection metadata, not stream mutation)
    if classification in ("safe", "warning"):
        return PersistenceDecision(
            stdout=stdout,
            stderr=stderr,
            mode=PERSIST_MODE_RAW,
            was_redacted=False,
            was_truncated=False,
        )

    # sensitive → redacted form only (secrets replaced with [REDACTED])
    if classification == "sensitive":
        return PersistenceDecision(
            stdout=inspection_result.stdout_redacted,
            stderr=inspection_result.stderr_redacted,
            mode=PERSIST_MODE_REDACTED,
            was_redacted=True,
            was_truncated=False,
        )

    # invalid → truncated redacted form
    # Apply redaction first (binary output may contain embedded secrets),
    # then cap at _TRUNCATION_LIMIT chars.
    if classification == "invalid":
        redacted_stdout = inspection_result.stdout_redacted
        redacted_stderr = inspection_result.stderr_redacted
        truncated_stdout = redacted_stdout[:_TRUNCATION_LIMIT]
        truncated_stderr = redacted_stderr[:_TRUNCATION_LIMIT]
        was_truncated = (
            len(redacted_stdout) > _TRUNCATION_LIMIT
            or len(redacted_stderr) > _TRUNCATION_LIMIT
        )
        return PersistenceDecision(
            stdout=truncated_stdout,
            stderr=truncated_stderr,
            mode=PERSIST_MODE_TRUNCATED,
            was_redacted=True,
            was_truncated=was_truncated,
        )

    # Unknown classification (future-proofing) → raw fallback
    return PersistenceDecision(
        stdout=stdout,
        stderr=stderr,
        mode=PERSIST_MODE_RAW,
        was_redacted=False,
        was_truncated=False,
    )
