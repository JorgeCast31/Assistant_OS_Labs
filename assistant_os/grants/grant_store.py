"""
Grant Store — Sprint 13.

Process-local, in-memory grant store.

Public API
----------
InMemoryGrantStore
    add_grant(grant: Grant) -> None
    find_applicable_grant(query: GrantQuery) -> Grant | None
    has_grants() -> bool
    clear() -> None

get_default_store() -> InMemoryGrantStore
    Returns the module-level singleton used by the orchestrator.

Design
------
The default store starts empty.  An empty store causes policy_engine to
skip the grant check (permissive fallback), preserving backward
compatibility with Sprint 9–12 tests and callers.

Once at least one grant is registered (has_grants() → True), the grant
check becomes mandatory: every evaluate_policy call that reaches step 5
must find an applicable grant or be denied.

Matching rules (all must hold for a grant to apply):
  1. grant.is_active is True
  2. grant.principal_id == query.principal_id
  3. grant.action_type  == query.action_type
  4. grant.capability   == query.capability   (None == None is valid)
  5. scope_prefix == "" OR query.operation_key.startswith(grant.scope_prefix)
  6. grant.expires_at is None OR time.time() <= grant.expires_at

find_applicable_grant returns the first matching grant found.
The order is insertion order (list).  For this skeleton there is no
priority or specificity ordering — that belongs to a future sprint.

Non-negotiable constraints
--------------------------
- No SQLite / DB (process memory only).
- No provenance metadata.
- No attenuation.
- No revocation engine (set is_active=False to revoke).
- Thread-safety: not required (single-threaded test / dev context).
"""

from __future__ import annotations

import time
from typing import Optional

from .grant_models import Grant, GrantQuery


# ---------------------------------------------------------------------------
# InMemoryGrantStore
# ---------------------------------------------------------------------------

class InMemoryGrantStore:
    """
    Process-local, in-memory store for Grant records.

    Lifecycle
    ---------
    1. add_grant(grant)                   → register a grant
    2. has_grants()                       → True when at least one grant exists
    3. find_applicable_grant(query)       → Grant | None
    4. clear()                            → test isolation helper
    """

    def __init__(self) -> None:
        self._grants: list[Grant] = []

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_grant(self, grant: Grant) -> None:
        """
        Register a grant.

        Duplicate grant_ids are allowed (the store does not enforce
        uniqueness at this stage).  Future sprints may add deduplication.

        Parameters
        ----------
        grant : Grant — the grant to register.
        """
        self._grants.append(grant)

    def clear(self) -> None:
        """
        Remove all grants.

        FOR TEST USE — provides isolation between test cases.
        Calling this in production code resets all authorization.
        """
        self._grants.clear()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def has_grants(self) -> bool:
        """
        Return True when the store contains at least one grant record.

        Used by evaluate_policy to decide whether the grant check is
        active.  An empty store means the grant layer has not been seeded
        yet → grant check is skipped (permissive fallback).
        """
        return len(self._grants) > 0

    def find_applicable_grant(self, query: GrantQuery) -> Optional[Grant]:
        """
        Return the first grant that matches the query, or None.

        Matching rules (all must hold):
          1. grant.is_active is True
          2. grant.principal_id == query.principal_id
          3. grant.action_type  == query.action_type
          4. grant.capability   == query.capability
          5. scope: grant.scope_prefix == "" OR
                    query.operation_key.startswith(grant.scope_prefix)
          6. not expired: grant.expires_at is None OR
                          time.time() <= grant.expires_at

        Parameters
        ----------
        query : GrantQuery — the lookup inputs from evaluate_policy step 5.

        Returns
        -------
        Grant if a matching grant is found; None otherwise (fail-closed).
        """
        now = time.time()
        for grant in self._grants:
            if _matches(grant, query, now):
                return grant
        return None


# ---------------------------------------------------------------------------
# Matching predicate
# ---------------------------------------------------------------------------

def _matches(grant: Grant, query: GrantQuery, now: float) -> bool:
    """Return True iff the grant applies to the query at time `now`."""
    # Rule 1: active
    if not grant.is_active:
        return False
    # Rule 2: principal
    if grant.principal_id != query.principal_id:
        return False
    # Rule 3: action_type (exact)
    if grant.action_type != query.action_type:
        return False
    # Rule 4: capability (exact, None == None)
    if grant.capability != query.capability:
        return False
    # Rule 5: scope_prefix
    if grant.scope_prefix and not query.operation_key.startswith(grant.scope_prefix):
        return False
    # Rule 6: expiry
    if grant.expires_at is not None and now > grant.expires_at:
        return False
    return True


# ---------------------------------------------------------------------------
# Module-level singleton (default store)
# ---------------------------------------------------------------------------

_default_store: InMemoryGrantStore = InMemoryGrantStore()


def get_default_store() -> InMemoryGrantStore:
    """
    Return the process-local default grant store.

    Used by the orchestrator to pass to evaluate_policy.
    Tests can call get_default_store().clear() (or use the autouse
    fixture pattern) to isolate each test case.
    """
    return _default_store
