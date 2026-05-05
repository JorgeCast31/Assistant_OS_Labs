"""
Unified Truthfulness Observability Contract.

Policy/MSO decides whether an action is authorized; readiness/truthfulness
determines whether the system can honestly claim execution or must report
unavailable.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch
from assistant_os.contracts import (
    EXECUTION_MODE_AUTO,
    EXECUTION_MODE_CONFIRM,
    EXECUTION_STATUS_UNAVAILABLE,
    normalize_request,
)

# --- Proposed Unified Vocabulary ---
# reachable, healthy, unavailable, unknown, stub, operational

class TestReadinessContractIntegrity:
    """Checks for standardized technical observability shape across domains."""

    @pytest.mark.xfail(reason="Unified readiness schema not yet implemented across domains")
    def test_unified_readiness_shape_consistency(self):
        """All domains must return a dictionary with standard observability keys."""
        # This represents the target state for get_code_readiness, get_fin_readiness, etc.
        from assistant_os.codeops.readiness import get_code_readiness
        
        readiness = get_code_readiness()
        required_keys = {"domain", "status", "last_check", "error"}
        
        assert required_keys.issubset(readiness.keys())
        assert readiness["status"] in {"reachable", "healthy", "unavailable", "unknown", "stub", "operational"}

class TestAuthorityIsolationInvariants:
    """Ensures technical observability does not usurp sovereign decision authority."""

    def test_readiness_failure_preserves_sovereign_execution_mode(self):
        """Technical failures (e.g. offline) must NOT modify the MSO execution_mode."""
        from assistant_os.core.semantic import classify
        
        req = normalize_request(text="Analiza este repo https://github.com/x/y", metadata={"surface": "assistant_chat"})
        
        # Scenario 1: Healthy/Normal
        with patch("assistant_os.codeops.readiness.get_code_readiness", return_value={"status": "healthy"}):
            intent_healthy = classify(req)
            mode_healthy = intent_healthy.get("execution_mode") # Note: classify currently returns 'intent' dict

        # Scenario 2: Technical Failure
        with patch("assistant_os.codeops.readiness.get_code_readiness", return_value={"status": "unavailable"}):
            intent_failed = classify(req)
            mode_failed = intent_failed.get("execution_mode")

        # Invariant: mode must remain unchanged by technical status
        assert mode_failed == mode_healthy

    def test_policy_explanation_remains_pure(self):
        """Policy explanations must only contain governance reasoning, not technical errors."""
        from assistant_os.core.semantic import classify
        
        req = normalize_request(text="Analiza este repo https://github.com/x/y", metadata={"surface": "assistant_chat"})
        
        with patch("assistant_os.codeops.readiness.get_code_readiness", return_value={"status": "unavailable", "error": "connection refused"}):
            intent = classify(req)
            explanation = intent.get("reason", "") # Currently 'reason' is the audit field
            
            assert "connection refused" not in explanation.lower()

class TestObservationalSignals:
    """Checks how technical truth is reported to the user/UI."""

    @pytest.mark.xfail(reason="Centralized truthfulness signal propagation to audit.truthfulness not yet implemented")
    def test_truthfulness_signals_in_observational_metadata(self):
        """Technical failures must appear in observational metadata, not authority fields."""
        from assistant_os.core.orchestrator import handle_request
        
        req = normalize_request(text="Analiza un repo", metadata={"surface": "assistant_chat"})
        
        with patch("assistant_os.codeops.readiness.get_code_readiness", return_value={"status": "unavailable"}):
            result = handle_request(req)
            
            # Should be in observational fields
            assert result.get("execution_status") == EXECUTION_STATUS_UNAVAILABLE
            assert "truthfulness" in result.get("audit", {})

    @pytest.mark.xfail(reason="Current implementation may describe configured status as healthy without probe")
    def test_configured_status_does_not_imply_healthy(self):
        """A configured feature must be reported as unavailable if the technical probe fails."""
        from assistant_os.surface_behavior import _machine_operator_summary
        
        with patch("assistant_os.operability.build_system_capabilities_response", return_value={
            "features": {"machine_operator": "operational"}, # Assuming 'operational' as per instructions
            "reachable": False
        }):
            summary = _machine_operator_summary().lower()
            
            assert "reachable" not in summary
            assert "activo" not in summary
            assert any(term in summary for term in ["no verificado", "indisponible", "unavailable", "probe"])
