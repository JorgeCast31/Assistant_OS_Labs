"""Capabilities package — Sprint 9 + Sprint 12.

Provides:
  - Capability gate: deterministic, fail-closed MO capability checking.
  - Token layer: process-local capability tokens (issue / verify / consume).
"""

from .capability_gate import (
    Capability,
    evaluate_capability,
    required_capability,
)
from .token_models import (
    CapabilityToken,
    OperationBinding,
    TokenStatus,
)
from .token_issuer import issue_token
from .token_verifier import verify_token, consume_token

__all__ = [
    # Capability gate
    "Capability",
    "evaluate_capability",
    "required_capability",
    # Token layer
    "CapabilityToken",
    "OperationBinding",
    "TokenStatus",
    "issue_token",
    "verify_token",
    "consume_token",
]
