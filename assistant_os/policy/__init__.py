"""
Policy package — Sprint 10 / Sprint 13.

Unified authorization layer for the orchestrator pipeline.
S13 adds grant-backed approval: PolicyDecision.APPROVED requires
an applicable grant when the grant store is non-empty.
"""

from .policy_models import (
    PolicyContext,
    PolicyDecision,
    PolicyOutcome,
    PolicyReason,
)
from .policy_engine import evaluate_policy

__all__ = [
    "PolicyContext",
    "PolicyDecision",
    "PolicyOutcome",
    "PolicyReason",
    "evaluate_policy",
]
