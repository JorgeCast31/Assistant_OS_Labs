"""
Grants package — Sprint 13.

Explicit grant layer for the authorization pipeline.
Grants are evaluated inside policy_engine.evaluate_policy() at step 5,
after capability evaluation and before APPROVED/DEGRADED outcomes.
"""

from .grant_models import Grant, GrantQuery
from .grant_store import InMemoryGrantStore, get_default_store

__all__ = [
    "Grant",
    "GrantQuery",
    "InMemoryGrantStore",
    "get_default_store",
]
