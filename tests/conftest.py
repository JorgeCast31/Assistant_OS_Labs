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
"""
import pytest

from assistant_os.police.token_registry import (
    _reset_for_testing,
    register_token,
)

# Token refs used by the three police gate test file factories, paired with
# the binding_ref their factories supply by default.
_COMMON_ACTIVE_TOKENS: dict[str, str] = {
    "token-ref-1":     "binding-ref-1",      # test_police_gate_behavior_xfail.py
    "token-valid-001": "binding-valid-001",  # test_police_token_bound_gate.py
    "token-1":         "binding-1",          # test_police_gate_contract.py
}


@pytest.fixture(autouse=True)
def _police_token_registry_isolation():
    """Reset and pre-seed the police token registry before each test."""
    _reset_for_testing()
    for token_ref, binding_ref in _COMMON_ACTIVE_TOKENS.items():
        register_token(token_ref, binding_ref=binding_ref)
    yield
    _reset_for_testing()
