"""Pytest configuration and shared fixtures for Assistant_OS tests.

Police token registry isolation
--------------------------------
The police token registry is a process-local singleton (a module-level dict).
Tests that call enforcement.check() must reset it before each test to prevent
state bleed between tests.

The autouse fixture below:
  1. Resets the registry before each test.
  2. Pre-seeds common token refs (matching the factories in each test file) as
     ACTIVE with the binding_ref that factory defaults supply.
  3. Resets again after the test (belt-and-suspenders cleanup).

Tests that need specific lifecycle states (expired, spent) or binding
constraints that differ from the defaults call register_token() themselves
within the test body, overriding the pre-seeded entries.

Authority artifact dev mode
---------------------------
ASSISTANT_OS_DEV_MODE=1 is set for the entire test session so that tests
that sign/verify authority artifacts do not require a real production secret.
Tests that need to verify hardened production behaviour (i.e. that the
RuntimeError IS raised) use monkeypatch.delenv() to clear this flag for the
duration of that individual test.
"""
import os

import pytest

# Allow the dev-default signing secret for all tests.  Individual tests that
# exercise the production-hardened path use monkeypatch.delenv() to override.
os.environ.setdefault("ASSISTANT_OS_DEV_MODE", "1")

from assistant_os.police.token_registry import (
    _reset_for_testing,
    register_token,
)
from assistant_os.police.authorized_plan_registry import (
    _reset_for_testing as _reset_authorized_plan_registry_for_testing,
    register_authorized_plan_ref,
)

# Token refs used by the three police gate test file factories, paired with
# the binding_ref their factories supply by default.
_COMMON_ACTIVE_TOKENS: dict[str, str] = {
    "token-ref-1":     "binding-ref-1",      # test_police_gate_behavior_xfail.py
    "token-valid-001": "binding-valid-001",  # test_police_token_bound_gate.py
    "token-1":         "binding-1",          # test_police_gate_contract.py
}

_COMMON_ACTIVE_PLANS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "plan-ref-1": ("exec-1", "token-ref-1", "binding-ref-1", ("write",)),
    "plan-valid-001": (
        "exec-test-001",
        "token-valid-001",
        "binding-valid-001",
        ("code.execute", "code.write"),
    ),
    "plan-1": ("exec-1", "token-1", "binding-1", ("host.notepad",)),
}


@pytest.fixture(autouse=True)
def _police_token_registry_isolation():
    """Reset and pre-seed the police token registry before each test."""
    _reset_for_testing()
    _reset_authorized_plan_registry_for_testing()
    for token_ref, binding_ref in _COMMON_ACTIVE_TOKENS.items():
        register_token(token_ref, binding_ref=binding_ref)
    for plan_ref, (
        execution_id,
        token_ref,
        binding_ref,
        capability_scope,
    ) in _COMMON_ACTIVE_PLANS.items():
        register_authorized_plan_ref(
            plan_ref,
            execution_id=execution_id,
            token_ref=token_ref,
            binding_ref=binding_ref,
            capability_scope=capability_scope,
        )
    yield
    _reset_for_testing()
    _reset_authorized_plan_registry_for_testing()
