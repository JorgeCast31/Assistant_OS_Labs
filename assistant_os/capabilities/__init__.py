"""Capability Gate — Sprint 9.

Provides deterministic, fail-closed capability checking for MO execution.
"""

from .capability_gate import (
    Capability,
    evaluate_capability,
    required_capability,
)

__all__ = [
    "Capability",
    "evaluate_capability",
    "required_capability",
]
