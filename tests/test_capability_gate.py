"""
Capability Gate Tests — Sprint 9.

Validates the canonical MO capability check model.

Capability model
----------------
  action_type → Capability mapping:
    "execute" → EXECUTE_CODE
    "write"   → WRITE_FILES
    others    → None (no specific capability required)

  subject_state → allowed capabilities:
    "active"      → {EXECUTE_CODE, WRITE_FILES}
    "quarantined" → {WRITE_FILES}            (code execution blocked)
    "suspended"   → {}                       (nothing allowed)
    "terminated"  → {}                       (nothing allowed)
    unknown/""    → {}                       (fail-closed)

Guarantees
----------
  - capability_blocked → orchestrator returns result_type="denied", error.type="capability_denied"
  - capability_allowed → orchestrator does NOT return error.type="capability_denied"
  - read action_type   → gate always passes (no MO capability required)
  - unknown state      → fail-closed (all capabilities denied)

Scope
-----
  Unit tests: capability_gate module in isolation.
  Integration tests: orchestrator.handle_request() with capability gate active.
  The integration tests verify gate position in the pipeline, not downstream execution.
"""

from __future__ import annotations

import pytest


# ===========================================================================
# Unit tests — capability_gate module in isolation
# ===========================================================================

class TestRequiredCapability:
    """required_capability(action_type) → Capability mapping."""

    def test_execute_maps_to_execute_code(self):
        from assistant_os.capabilities.capability_gate import (
            Capability, required_capability,
        )
        assert required_capability("execute") == Capability.EXECUTE_CODE

    def test_write_maps_to_write_files(self):
        from assistant_os.capabilities.capability_gate import (
            Capability, required_capability,
        )
        assert required_capability("write") == Capability.WRITE_FILES

    def test_read_returns_none(self):
        """Read operations require no specific MO capability — gate passes."""
        from assistant_os.capabilities.capability_gate import required_capability
        assert required_capability("read") is None

    def test_empty_string_returns_none(self):
        """Absent action_type (legacy/NL callers) → gate passes."""
        from assistant_os.capabilities.capability_gate import required_capability
        assert required_capability("") is None

    def test_unknown_action_type_returns_none(self):
        """Unknown action types are not MO capabilities — gate passes."""
        from assistant_os.capabilities.capability_gate import required_capability
        assert required_capability("network") is None
        assert required_capability("policy") is None
        assert required_capability("unknown_action") is None


class TestEvaluateCapability:
    """evaluate_capability(subject_state, capability) → bool."""

    # --- active state: all capabilities allowed ---

    def test_active_allows_execute_code(self):
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        assert evaluate_capability("active", Capability.EXECUTE_CODE) is True

    def test_active_allows_write_files(self):
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        assert evaluate_capability("active", Capability.WRITE_FILES) is True

    # --- quarantined state: write only, no code execution ---

    def test_quarantined_denies_execute_code(self):
        """Quarantined subjects must NOT execute code."""
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        assert evaluate_capability("quarantined", Capability.EXECUTE_CODE) is False

    def test_quarantined_allows_write_files(self):
        """Quarantined subjects may write files (limited capability)."""
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        assert evaluate_capability("quarantined", Capability.WRITE_FILES) is True

    # --- suspended state: nothing allowed ---

    def test_suspended_denies_execute_code(self):
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        assert evaluate_capability("suspended", Capability.EXECUTE_CODE) is False

    def test_suspended_denies_write_files(self):
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        assert evaluate_capability("suspended", Capability.WRITE_FILES) is False

    # --- terminated state: nothing allowed ---

    def test_terminated_denies_execute_code(self):
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        assert evaluate_capability("terminated", Capability.EXECUTE_CODE) is False

    def test_terminated_denies_write_files(self):
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        assert evaluate_capability("terminated", Capability.WRITE_FILES) is False

    # --- unknown/empty state: fail-closed ---

    def test_empty_state_denies_all(self):
        """Absent subject_state → fail-closed (no capabilities)."""
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        assert evaluate_capability("", Capability.EXECUTE_CODE) is False
        assert evaluate_capability("", Capability.WRITE_FILES) is False

    def test_unknown_state_denies_all(self):
        """Unrecognised subject_state → fail-closed."""
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        assert evaluate_capability("unknown_state", Capability.EXECUTE_CODE) is False
        assert evaluate_capability("unknown_state", Capability.WRITE_FILES) is False
        assert evaluate_capability("root", Capability.EXECUTE_CODE) is False

    # --- distinctness: quarantined ≠ active ---

    def test_quarantined_is_strictly_less_capable_than_active(self):
        """Quarantined has a strict subset of active's capabilities."""
        from assistant_os.capabilities.capability_gate import (
            Capability, evaluate_capability,
        )
        # active has both; quarantined only has write
        assert evaluate_capability("active", Capability.EXECUTE_CODE) is True
        assert evaluate_capability("active", Capability.WRITE_FILES) is True
        assert evaluate_capability("quarantined", Capability.EXECUTE_CODE) is False
        assert evaluate_capability("quarantined", Capability.WRITE_FILES) is True


class TestCapabilityEnum:
    """Capability values are stable strings (used as tokens in AuthorizedPlan.capability_scope)."""

    def test_execute_code_value(self):
        from assistant_os.capabilities.capability_gate import Capability
        assert Capability.EXECUTE_CODE.value == "execute_code"

    def test_write_files_value(self):
        from assistant_os.capabilities.capability_gate import Capability
        assert Capability.WRITE_FILES.value == "write_files"

    def test_capability_values_are_strings(self):
        """Capability is a str enum — tokens can be compared against scope lists."""
        from assistant_os.capabilities.capability_gate import Capability
        assert isinstance(Capability.EXECUTE_CODE, str)
        assert isinstance(Capability.WRITE_FILES, str)
        assert "execute_code" in {Capability.EXECUTE_CODE}
        assert "write_files" in {Capability.WRITE_FILES}


# ===========================================================================
# Integration tests — orchestrator.handle_request() with capability gate
# ===========================================================================

def _make_cap_blocked_request(action_type: str, subject_state: str) -> dict:
    """
    Minimal CanonicalRequest where:
    - guard_decision = "allow" (identity guard already passed)
    - action_type and subject_state supplied explicitly (as if from build_guarded_request)
    """
    return {
        "text": "test request",
        "context_id": f"ctx-cap-{action_type}-{subject_state}",
        "filters": {},
        "metadata": {},
        "principal_id": "user-cap-test",
        "subject_state": subject_state,
        "guard_decision": "allow",
        "action_type": action_type,
    }


class TestCapabilityBlockedInOrchestrator:
    """
    When capability is denied, orchestrator returns result_type='denied'
    with error.type='capability_denied' and does NOT proceed to execution.
    """

    def test_execute_blocked_for_quarantined_returns_denied(self):
        from assistant_os.core.orchestrator import handle_request
        req = _make_cap_blocked_request("execute", "quarantined")
        result = handle_request(req)
        assert result["ok"] is False
        assert result["result_type"] == "denied"

    def test_execute_blocked_for_quarantined_error_type_is_capability_denied(self):
        from assistant_os.core.orchestrator import handle_request
        req = _make_cap_blocked_request("execute", "quarantined")
        result = handle_request(req)
        assert result["error"]["type"] == "capability_denied"

    def test_execute_blocked_for_suspended_returns_denied(self):
        from assistant_os.core.orchestrator import handle_request
        req = _make_cap_blocked_request("execute", "suspended")
        result = handle_request(req)
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "capability_denied"

    def test_execute_blocked_for_terminated_returns_denied(self):
        from assistant_os.core.orchestrator import handle_request
        req = _make_cap_blocked_request("execute", "terminated")
        result = handle_request(req)
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "capability_denied"

    def test_write_blocked_for_suspended_returns_denied(self):
        from assistant_os.core.orchestrator import handle_request
        req = _make_cap_blocked_request("write", "suspended")
        result = handle_request(req)
        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "capability_denied"

    def test_capability_denied_is_distinct_from_access_denied(self):
        """capability_denied and access_denied are different error types."""
        from assistant_os.core.orchestrator import handle_request

        # Capability gate denial
        cap_req = _make_cap_blocked_request("execute", "quarantined")
        cap_result = handle_request(cap_req)
        assert cap_result["error"]["type"] == "capability_denied"

        # Identity guard denial (guard_decision="deny")
        guard_req = {
            "text": "test",
            "context_id": "ctx-guard-deny",
            "filters": {},
            "metadata": {},
            "principal_id": "user-1",
            "subject_state": "suspended",
            "guard_decision": "deny",
        }
        guard_result = handle_request(guard_req)
        assert guard_result["error"]["type"] == "access_denied"

        # The two error types must be different
        assert cap_result["error"]["type"] != guard_result["error"]["type"]

    def test_capability_block_does_not_reach_execution(self):
        """
        When capability is denied, no execution occurs.
        Verified by the early-return: result carries no execution artifacts.
        """
        from assistant_os.core.orchestrator import handle_request
        req = _make_cap_blocked_request("execute", "quarantined")
        result = handle_request(req)
        # Should be a bare denied result — no plan, no pipeline artifacts
        assert result["ok"] is False
        assert result["data"] == {}


class TestCapabilityAllowedInOrchestrator:
    """
    When capability is allowed, the orchestrator does NOT return capability_denied.
    Execution may fail for other reasons (no real backend), but the gate itself passes.
    """

    def test_execute_allowed_for_active_does_not_return_capability_denied(self):
        from assistant_os.core.orchestrator import handle_request
        req = _make_cap_blocked_request("execute", "active")
        result = handle_request(req)
        # Gate passes — error type must NOT be capability_denied
        error_type = result.get("error", {})
        if isinstance(error_type, dict):
            error_type = error_type.get("type", "")
        assert error_type != "capability_denied"

    def test_write_allowed_for_active_does_not_return_capability_denied(self):
        from assistant_os.core.orchestrator import handle_request
        req = _make_cap_blocked_request("write", "active")
        result = handle_request(req)
        error_type = result.get("error", {})
        if isinstance(error_type, dict):
            error_type = error_type.get("type", "")
        assert error_type != "capability_denied"

    def test_read_for_quarantined_does_not_return_capability_denied(self):
        """Read requires no MO capability — quarantined state is fine for reads."""
        from assistant_os.core.orchestrator import handle_request
        req = _make_cap_blocked_request("read", "quarantined")
        result = handle_request(req)
        error_type = result.get("error", {})
        if isinstance(error_type, dict):
            error_type = error_type.get("type", "")
        assert error_type != "capability_denied"

    def test_no_action_type_for_suspended_does_not_return_capability_denied(self):
        """
        Absent action_type (NL requests, legacy callers) → gate passes unconditionally.
        The gate should never block requests that don't specify an MO action type.
        """
        from assistant_os.core.orchestrator import handle_request
        req = {
            "text": "What is the status?",
            "context_id": "ctx-cap-nl",
            "filters": {},
            "metadata": {},
            "subject_state": "suspended",
            "guard_decision": "deny",  # Guard blocks it, but not for capability reasons
        }
        result = handle_request(req)
        # Blocked by identity guard (access_denied), not by capability gate
        assert result.get("error", {}).get("type") != "capability_denied"


class TestCapabilityGatePosition:
    """
    The capability gate must fire AFTER identity guard checks and BEFORE
    any execution path (confirm, structured, NL).
    """

    def test_identity_guard_deny_is_checked_before_capability_gate(self):
        """
        Guard DENY should return access_denied even if capability would also be blocked.
        The identity guard is the first line — it fires before the capability gate.
        """
        from assistant_os.core.orchestrator import handle_request
        req = {
            "text": "execute something",
            "context_id": "ctx-order-test",
            "filters": {},
            "metadata": {},
            "principal_id": "user-1",
            "subject_state": "quarantined",
            "guard_decision": "deny",       # Guard blocks first
            "action_type": "execute",       # Cap gate would also block
        }
        result = handle_request(req)
        # Must be blocked by identity guard (access_denied), not capability gate
        assert result["error"]["type"] == "access_denied"
        assert result["error"]["type"] != "capability_denied"

    def test_capability_gate_fires_when_guard_allows(self):
        """
        When guard_decision='allow', capability gate is the next check.
        """
        from assistant_os.core.orchestrator import handle_request
        req = {
            "text": "execute something",
            "context_id": "ctx-gate-fires",
            "filters": {},
            "metadata": {},
            "principal_id": "user-1",
            "subject_state": "quarantined",
            "guard_decision": "allow",      # Guard passes
            "action_type": "execute",       # Cap gate blocks
        }
        result = handle_request(req)
        # Capability gate fires and blocks it
        assert result["error"]["type"] == "capability_denied"
