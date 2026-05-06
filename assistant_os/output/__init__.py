"""
assistant_os.output
--------------------
Output Control layer — inspection, classification, normalization, and persistence.

Public surface
--------------
    OutputFlag          — a single finding from content inspection
    InspectionResult    — full inspection result with classification + redacted output
    OutputInspector     — stateless inspector; call inspect(stdout, stderr) → InspectionResult

    PersistenceDecision — result of decide_persistence(); governed stdout/stderr + mode
    decide_persistence  — pure function: (stdout, stderr, InspectionResult) → PersistenceDecision

    PERSIST_MODE_RAW
    PERSIST_MODE_REDACTED
    PERSIST_MODE_TRUNCATED

    OUTPUT_INSPECTION_SAFE
    OUTPUT_INSPECTION_WARNING
    OUTPUT_INSPECTION_SENSITIVE
    OUTPUT_INSPECTION_INVALID

    FLAG_POTENTIAL_SECRET
    FLAG_ABSOLUTE_PATH
    FLAG_ENV_VAR_PATTERN
    FLAG_LONG_ENCODED_STRING
    FLAG_BINARY_CONTENT
"""

from .inspector import OutputInspector
from .models import (
    FLAG_ABSOLUTE_PATH,
    FLAG_BINARY_CONTENT,
    FLAG_ENV_VAR_PATTERN,
    FLAG_LONG_ENCODED_STRING,
    FLAG_POTENTIAL_SECRET,
    OUTPUT_INSPECTION_INVALID,
    OUTPUT_INSPECTION_SAFE,
    OUTPUT_INSPECTION_SENSITIVE,
    OUTPUT_INSPECTION_WARNING,
    InspectionResult,
    OutputFlag,
)
from .persistence_policy import (
    PERSIST_MODE_RAW,
    PERSIST_MODE_REDACTED,
    PERSIST_MODE_TRUNCATED,
    PersistenceDecision,
    decide_persistence,
)

__all__ = [
    "FLAG_ABSOLUTE_PATH",
    "FLAG_BINARY_CONTENT",
    "FLAG_ENV_VAR_PATTERN",
    "FLAG_LONG_ENCODED_STRING",
    "FLAG_POTENTIAL_SECRET",
    "InspectionResult",
    "OUTPUT_INSPECTION_INVALID",
    "OUTPUT_INSPECTION_SAFE",
    "OUTPUT_INSPECTION_SENSITIVE",
    "OUTPUT_INSPECTION_WARNING",
    "OutputFlag",
    "OutputInspector",
    "PERSIST_MODE_RAW",
    "PERSIST_MODE_REDACTED",
    "PERSIST_MODE_TRUNCATED",
    "PersistenceDecision",
    "decide_persistence",
]
