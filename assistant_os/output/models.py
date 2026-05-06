"""
assistant_os.output.models
--------------------------
Data models for the Output Control layer.

OutputFlag         — single finding from content inspection.
InspectionResult   — full result of inspecting one execution's output.

Classification hierarchy (ordered by severity)
-----------------------------------------------
    safe       — no suspicious content detected.
    warning    — possible path leakage, env var patterns, or long encoded strings.
    sensitive  — high-confidence secret or credential pattern detected.
    invalid    — structurally invalid output (binary/non-printable content).

Design principles
-----------------
- Inspection NEVER blocks execution.  It annotates results after the fact.
- InspectionResult.to_dict() is log-safe: no raw secret values included.
- stdout_redacted / stderr_redacted replace matched patterns with "[REDACTED]"
  so API consumers can see what happened without receiving the actual value.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

# ---------------------------------------------------------------------------
# Classification constants
# ---------------------------------------------------------------------------

OUTPUT_INSPECTION_SAFE      = "safe"
OUTPUT_INSPECTION_WARNING   = "warning"
OUTPUT_INSPECTION_SENSITIVE = "sensitive"
OUTPUT_INSPECTION_INVALID   = "invalid"

VALID_INSPECTION_CLASSIFICATIONS: frozenset[str] = frozenset({
    OUTPUT_INSPECTION_SAFE,
    OUTPUT_INSPECTION_WARNING,
    OUTPUT_INSPECTION_SENSITIVE,
    OUTPUT_INSPECTION_INVALID,
})

# ---------------------------------------------------------------------------
# Flag type constants
# ---------------------------------------------------------------------------

FLAG_POTENTIAL_SECRET     = "potential_secret"
FLAG_ABSOLUTE_PATH        = "absolute_path"
FLAG_ENV_VAR_PATTERN      = "env_var_pattern"
FLAG_LONG_ENCODED_STRING  = "long_encoded_string"
FLAG_BINARY_CONTENT       = "binary_content"

VALID_FLAG_TYPES: frozenset[str] = frozenset({
    FLAG_POTENTIAL_SECRET,
    FLAG_ABSOLUTE_PATH,
    FLAG_ENV_VAR_PATTERN,
    FLAG_LONG_ENCODED_STRING,
    FLAG_BINARY_CONTENT,
})


# ---------------------------------------------------------------------------
# OutputFlag
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OutputFlag:
    """
    A single finding from output content inspection.

    Fields
    ------
    flag_type : One of the FLAG_* constants.
    detail    : Human-readable description.  NEVER includes the matched value.
    stream    : "stdout" | "stderr"
    """

    flag_type: str
    detail: str
    stream: str

    def to_dict(self) -> dict:
        return {
            "flag_type": self.flag_type,
            "detail": self.detail,
            "stream": self.stream,
        }


# ---------------------------------------------------------------------------
# InspectionResult
# ---------------------------------------------------------------------------

@dataclass
class InspectionResult:
    """
    Full result of inspecting execution output streams.

    Fields
    ------
    classification  : Overall risk level (safe / warning / sensitive / invalid).
    flags           : Individual findings from pattern matching.
    inspected_at    : Wall-clock time of the inspection.
    stdout_redacted : stdout with matched sensitive patterns replaced by [REDACTED].
    stderr_redacted : stderr with matched sensitive patterns replaced by [REDACTED].
    """

    classification: str
    flags: List[OutputFlag]
    inspected_at: float
    stdout_redacted: str
    stderr_redacted: str

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    def is_sensitive(self) -> bool:
        return self.classification == OUTPUT_INSPECTION_SENSITIVE

    def is_safe(self) -> bool:
        return self.classification == OUTPUT_INSPECTION_SAFE

    def has_flags(self) -> bool:
        return len(self.flags) > 0

    def flag_types(self) -> frozenset[str]:
        return frozenset(f.flag_type for f in self.flags)

    # ------------------------------------------------------------------
    # Serialization (log-safe — no raw matched values)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """
        Log-safe serialization.

        normalized_output reflects what would be safe to show users — it is the
        redacted version of the governed streams, with sensitive patterns masked.
        """
        return {
            "classification": self.classification,
            "flag_count": len(self.flags),
            "flags": [f.to_dict() for f in self.flags],
            "inspected_at": self.inspected_at,
            "normalized_output": {
                "stdout": self.stdout_redacted,
                "stderr": self.stderr_redacted,
            },
        }
