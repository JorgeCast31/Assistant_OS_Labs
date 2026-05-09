"""
HOST / MACHINE_OPERATOR Direct-Call Characterization Tests
===========================================================

Phase A — characterization of the bypass gap documented in
HOST_MACHINE_OPERATOR_DIRECT_CALL_AUDIT.md (section 9).

PURPOSE
-------
These tests CHARACTERIZE current (as-built) behavior without fixing it.
They make the bypass surface observable and regression-safe so that:

  1. Future guard implementations can reference these tests as baseline.
  2. Any accidental closure of the bypass raises a test failure and forces
     a conscious decision (fix the test or keep the guard).
  3. The audit findings are verifiable via CI, not just static analysis.

WHAT THESE TESTS DO NOT DO
---------------------------
- They do NOT implement S-POLICE-CORE-03.
- They do NOT add governance checks to the registry path.
- They do NOT modify any pipeline, orchestrator, or webhook code.
- They do NOT close the bypass — they document it.

TESTS
-----
T1  test_host_registry_direct_call_blocked_when_agent_not_active
    Registry → execute_host_action() gate fires (CONTROL_PLANE_BLOCKED).
    No PolicyDecision / CapabilityToken / MSO Governance consulted.

T2  test_machine_operator_registry_direct_call_rejects_unknown_capability
    Registry → pipeline policy gate fires on unknown capability.
    No orchestrator path traversed.

T3  test_machine_operator_registry_does_not_check_mso_governance
    Registry path executes while _evaluate_mso_governance is NEVER called.
    Confirms governance BLOCKED does not propagate through the registry.

T4  test_execute_host_action_has_no_policy_decision_check
    execute_host_action() runs through its own gates without calling
    evaluate_policy (the orchestrator's S10/S13 policy step).

T5  test_playwright_runtime_has_no_sovereign_gate_internally
    NullRuntimeDispatcher.execute() raises RuntimeUnavailableError.
    No SovereignStore / OpenClaw HTTP sovereign gate is consulted.

T6  test_host_blocked_via_orchestrator_but_not_via_registry
    Contrast: orchestrator with governance BLOCKED → RESULT_TYPE_PLAN_GENERATED.
    Registry with same conditions → execute_host_action gates (CONTROL_PLANE_BLOCKED),
    NOT plan_generated — confirms the bypass is real, not default behavior.

REFERENCE
---------
Audit: HOST_MACHINE_OPERATOR_DIRECT_CALL_AUDIT.md §9 Recommended Tests
Sprint: Phase A (characterization only)
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from assistant_os.agents.host_agent import (
    HOST_AGENT_ID,
    HostActionRequest,
    _reset_host_agent_state_for_tests,
    execute_host_action,
)
from assistant_os.agents.host_audit import HOST_AUDIT_LOG
from assistant_os.agents.registry import (
    _host_launcher_entrypoint,
    _machine_operator_entrypoint,
)
from assistant_os.contracts import (
    EXECUTION_MODE_AUTO,
    EXECUTION_MODE_BLOCKED,
    RESULT_TYPE_PLAN_GENERATED,
    RESULT_TYPE_WORK_QUERY,
    normalize_request,
)
from assistant_os.core.control_plane import _reset_state_for_tests, activate_agent
from assistant_os.mso.contracts import (
    GovernanceDecision,
    GovernanceIntervention,
    GovernanceReason,
)
from assistant_os.mso.machine_operator_audit import MACHINE_OPERATOR_AUDIT_LOG
from assistant_os.openclaw_backend.runtime import (
    NullRuntimeDispatcher,
    RuntimeUnavailableError,
)


# ---------------------------------------------------------------------------
# Shared reset fixture
# ---------------------------------------------------------------------------

def _full_reset() -> None:
    """Reset all MSO and agent state to clean baseline."""
    from assistant_os.mso.capability_registry import reset_dynamic_capabilities
    from assistant_os.mso.machine_operator_adapter import reset_machine_operator_backend_health
    from assistant_os.mso.system_state import clear_operational_mode_override
    from assistant_os.mso.task_registry import reset_task_registry
    from assistant_os.mso.trace_aggregator import reset_trace_aggregator
    from assistant_os.storage.mso_store import clear_mso_store

    _reset_state_for_tests()
    _reset_host_agent_state_for_tests()
    HOST_AUDIT_LOG.clear()
    MACHINE_OPERATOR_AUDIT_LOG.clear()
    reset_task_registry()
    reset_trace_aggregator()
    clear_operational_mode_override()
    reset_dynamic_capabilities()
    clear_mso_store()
    reset_machine_operator_backend_health()


# ---------------------------------------------------------------------------
# Governance decision factories (mirrors test_mso_governance_blocked_enforcement)
# ---------------------------------------------------------------------------

def _governance_blocked() -> GovernanceDecision:
    return GovernanceDecision(
        governance_ref="gov-char-blocked-001",
        action="BLOCK",
        target_domain="HOST",
        target_action="HOST_ACTION",
        effective_execution_mode=EXECUTION_MODE_BLOCKED,
        risk_level="high",
        justification="Characterization test: governance blocks execution",
        reasons=[
            GovernanceReason(code="char_block", detail="Characterization BLOCK"),
        ],
        constraints=[],
        interventions=[
            GovernanceIntervention(
                kind="char_block", value="*", reason="Characterization BLOCK"
            ),
        ],
        capability_mode="allow",
        base_execution_mode="auto",
        operational_mode="normal",
        created_at="2026-05-08T00:00:00+00:00",
    )


def _governance_auto() -> GovernanceDecision:
    return GovernanceDecision(
        governance_ref="gov-char-auto-001",
        action="ALLOW",
        target_domain="HOST",
        target_action="HOST_ACTION",
        effective_execution_mode=EXECUTION_MODE_AUTO,
        risk_level="low",
        justification="Characterization test: governance allows auto",
        reasons=[
            GovernanceReason(code="char_auto", detail="Characterization AUTO"),
        ],
        constraints=[],
        interventions=[],
        capability_mode="allow",
        base_execution_mode="auto",
        operational_mode="normal",
        created_at="2026-05-08T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# T1 — Host registry direct call is blocked when agent is not ACTIVE
# ---------------------------------------------------------------------------

class TestT1HostRegistryDirectCallBlockedWhenAgentNotActive(unittest.TestCase):
    """
    T1: _host_launcher_entrypoint() calls execute_host_action() directly.

    When the HOST agent is NOT active (control_plane default), Gate 2
    (CONTROL_PLANE_BLOCKED) fires and execution is refused.

    This characterizes that:
    - The registry bypasses the full orchestrator sovereign path
    - Its only defense is execute_host_action()'s internal gates
    - Gate 2 is the last line of defense here (no PolicyDecision, no Governance)
    """

    def setUp(self):
        _full_reset()
        # Deliberately do NOT call activate_agent(HOST_AGENT_ID) — agent stays inactive

    def tearDown(self):
        _full_reset()

    def test_host_registry_direct_call_blocked_when_agent_not_active(self):
        """
        CHARACTERIZATION: Registry path hits CONTROL_PLANE_BLOCKED gate.
        No governance or policy check is performed — only the internal
        host_agent gate stands between caller and execution.
        """
        from assistant_os.agents.host_audit import HostErrorCode

        request = HostActionRequest(
            execution_id="char-t1-001",
            action="open_app",
            confirmed=True,
            app_name="notepad",
        )

        result = _host_launcher_entrypoint(request)

        # Gate 2 fires: agent not active → execution refused
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, HostErrorCode.CONTROL_PLANE_BLOCKED)

        # No governance or policy was needed — the bypass gap is real:
        # only an internal host_agent gate stopped execution


# ---------------------------------------------------------------------------
# T2 — Machine operator registry rejects unknown capability via policy gate
# ---------------------------------------------------------------------------

class TestT2MachineOperatorRegistryDirectCallRejectsUnknownCapability(unittest.TestCase):
    """
    T2: _machine_operator_entrypoint() calls the MO pipeline directly.

    An unknown capability is rejected by the pipeline's internal policy gate
    (enforce_machine_operator_request) without consulting the orchestrator.

    This characterizes that:
    - The registry bypasses orchestrator, PolicyDecision, CapabilityToken, Governance
    - The pipeline's own policy gate is the only check
    - Known capabilities would proceed to adapter execution without governance
    """

    def setUp(self):
        _full_reset()

    def tearDown(self):
        _full_reset()

    def test_machine_operator_registry_direct_call_rejects_unknown_capability(self):
        """
        CHARACTERIZATION: Unknown capability is rejected by MO pipeline policy gate.
        No orchestrator traversal. Only internal enforce_machine_operator_request fires.
        """
        # Unknown capability → policy gate must reject via fail-closed default (N2)
        request = {
            "intent_id": "char-t2-001",
            "correlation_id": "corr-char-t2",
            "capability_name": "browser.unknown_capability_xyz",
            "capability_tier": "read_only",
            "arguments": {"url": "https://example.test"},
            "policy_context": {
                "policy_decision_ref": "policy-char-t2",
                "governance_ref": "gov-char-t2",
                "execution_mode": "auto",
                "approval_mode": "none",
                "constraints": [],
                "allowlist_refs": ["allowlist:web-safe"],
                "secret_refs": [],
            },
            "budget": {
                "max_steps": 1,
                "max_duration_ms": 5000,
                "max_output_bytes": 2048,
                "max_side_effects": 0,
            },
            "requested_side_effects": [],
            "approval": None,
        }

        result = _machine_operator_entrypoint(request)

        # Pipeline policy gate fires: unknown capability → policy violation
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "MachineOperatorPolicyViolation")

        # CHARACTERIZATION GAP: no governance was consulted.
        # A BLOCKED governance decision would NOT have reached this gate.


# ---------------------------------------------------------------------------
# T3 — Machine operator registry does NOT call MSO governance
# ---------------------------------------------------------------------------

class TestT3MachineOperatorRegistryDoesNotCheckMsoGovernance(unittest.TestCase):
    """
    T3: _machine_operator_entrypoint() bypasses _evaluate_mso_governance entirely.

    Even if governance would return BLOCKED, the registry path is unaffected.
    _evaluate_mso_governance is never called from the registry → pipeline path.

    This characterizes the critical governance bypass in the registry path.
    """

    def setUp(self):
        _full_reset()

    def tearDown(self):
        _full_reset()

    @patch("assistant_os.core.orchestrator._evaluate_mso_governance")
    def test_machine_operator_registry_does_not_check_mso_governance(
        self, mock_governance
    ):
        """
        CHARACTERIZATION: _evaluate_mso_governance is NEVER called through
        the registry → pipeline path, even though a BLOCKED decision exists.

        This is the documented bypass gap: governance cannot block the registry.
        """
        mock_governance.return_value = _governance_blocked()

        # Use a known capability that would pass policy gate (browser.snapshot)
        # but mock the adapter so we don't need a real network call
        request = {
            "intent_id": "char-t3-001",
            "correlation_id": "corr-char-t3",
            "capability_name": "browser.snapshot",
            "capability_tier": "read_only",
            "arguments": {"url": "https://example.test"},
            "policy_context": {
                "policy_decision_ref": "policy-char-t3",
                "governance_ref": "gov-char-t3",
                "execution_mode": "auto",
                "approval_mode": "none",
                "constraints": [],
                "allowlist_refs": ["allowlist:web-safe"],
                "secret_refs": [],
            },
            "budget": {
                "max_steps": 1,
                "max_duration_ms": 5000,
                "max_output_bytes": 2048,
                "max_side_effects": 0,
            },
            "requested_side_effects": [],
            "approval": None,
        }

        with patch(
            "assistant_os.mso.machine_operator_adapter.requests.post"
        ) as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "status": "ok",
                    "final_url": "https://example.test",
                    "observation": {"summary": "mocked", "detail": "", "structured_data": {}},
                    "evidence_refs": [],
                    "consumed_budget": {"steps": 1},
                },
            )
            result = _machine_operator_entrypoint(request)

        # CRITICAL: governance was NEVER consulted from the registry path
        mock_governance.assert_not_called()

        # The pipeline ran (or hit adapter-level error) WITHOUT governance blessing
        # This documents the bypass: governance BLOCKED does not protect registry callers


# ---------------------------------------------------------------------------
# T4 — execute_host_action has no policy decision check
# ---------------------------------------------------------------------------

class TestT4ExecuteHostActionHasNoPolicyDecisionCheck(unittest.TestCase):
    """
    T4: execute_host_action() runs its own internal gates without ever
    calling the orchestrator's evaluate_policy (S10/S13 policy step).

    This characterizes that direct callers of execute_host_action() bypass
    the sovereign policy enforcement layer entirely.
    """

    def setUp(self):
        _full_reset()

    def tearDown(self):
        _full_reset()

    @patch("assistant_os.policy.policy_engine.evaluate_policy")
    def test_execute_host_action_has_no_policy_decision_check(
        self, mock_evaluate_policy
    ):
        """
        CHARACTERIZATION: execute_host_action() does NOT call evaluate_policy.

        Gate 1 (confirmed=False) fires before any execution — policy was
        irrelevant. Direct callers bypass sovereign policy entirely.
        """
        # Gate 1 fires: confirmed=False → CONFIRMED_REQUIRED (stops execution early)
        # Policy is never reached regardless
        request = HostActionRequest(
            execution_id="char-t4-001",
            action="open_app",
            confirmed=False,  # Gate 1 will fire
            app_name="notepad",
        )

        result = execute_host_action(request)

        # Gate 1 fired — execution stopped at internal gate
        self.assertFalse(result.ok)

        # CRITICAL: evaluate_policy was NEVER called
        mock_evaluate_policy.assert_not_called()

    @patch("assistant_os.policy.policy_engine.evaluate_policy")
    def test_execute_host_action_active_agent_no_policy_check(
        self, mock_evaluate_policy
    ):
        """
        CHARACTERIZATION: Even with ACTIVE agent and confirmed=True,
        execute_host_action() still does NOT call evaluate_policy.

        Gate 2 passes (ACTIVE). Gate 1 passes (confirmed=True).
        Execution reaches domain logic without any policy consultation.
        """
        activate_agent(HOST_AGENT_ID)

        # confirmed=True, action=list_directory — runs without path restriction gate
        # (will fail at domain level if path not in sandbox, but policy is never called)
        request = HostActionRequest(
            execution_id="char-t4-002",
            action="list_directory",
            confirmed=True,
            path="C:\\NonExistent\\Path\\That\\Fails\\At\\Domain\\Level",
        )

        result = execute_host_action(request)

        # Execution attempted (ok may be False at domain level, that's fine)
        # The key invariant: evaluate_policy was NEVER consulted
        mock_evaluate_policy.assert_not_called()


# ---------------------------------------------------------------------------
# T5 — Playwright runtime has no sovereign gate internally
# ---------------------------------------------------------------------------

class TestT5PlaywrightRuntimeHasNoSovereignGateInternally(unittest.TestCase):
    """
    T5: NullRuntimeDispatcher.execute() raises RuntimeUnavailableError.

    No SovereignStore is consulted before raising. The sovereign gate lives
    only in the HTTP server (server.py), not in the Python-callable runtime.

    Python-direct callers bypass the sovereign gate entirely.

    This characterizes that:
    - The sovereign gate is an HTTP-layer concern (server.py)
    - PlaywrightRuntimeDispatcher.execute() has no internal sovereign check
    - A Python caller can invoke runtime dispatch without sovereign approval
    """

    def test_playwright_runtime_has_no_sovereign_gate_internally(self):
        """
        CHARACTERIZATION: NullRuntimeDispatcher.execute() raises RuntimeUnavailableError
        without consulting any sovereign store.

        The runtime itself has no sovereign gate — the gate is HTTP-layer only.
        """
        dispatcher = NullRuntimeDispatcher()

        # Verify runtime is correctly reporting unavailable
        self.assertFalse(dispatcher.is_available())

        # execute() raises RuntimeUnavailableError — no sovereign store consulted
        with self.assertRaises(RuntimeUnavailableError):
            dispatcher.execute(
                capability_name="browser.snapshot",
                arguments={"url": "https://example.test"},
                timeout_seconds=5.0,
            )

    def test_null_runtime_dispatcher_has_no_sovereign_store_attribute(self):
        """
        CHARACTERIZATION: NullRuntimeDispatcher has no sovereign store attribute.

        This confirms the bypass: sovereign gate is not architecturally part of
        the runtime dispatch layer — it must be added as a separate guard.
        """
        dispatcher = NullRuntimeDispatcher()

        # No sovereign store, no sovereign gate, no execution_allowed check
        self.assertFalse(hasattr(dispatcher, "_sovereign_store"))
        self.assertFalse(hasattr(dispatcher, "sovereign_store"))
        self.assertFalse(hasattr(dispatcher, "is_execution_allowed"))
        self.assertFalse(hasattr(dispatcher, "sovereign_gate"))


# ---------------------------------------------------------------------------
# T6 — HOST blocked via orchestrator but NOT via registry
# ---------------------------------------------------------------------------

class TestT6HostBlockedViaOrchestratorButNotViaRegistry(unittest.TestCase):
    """
    T6: Contrast test proving the bypass is real, not default behavior.

    Orchestrator path + BLOCKED governance → RESULT_TYPE_PLAN_GENERATED.
    Registry path + BLOCKED governance (mocked but not consulted) → execute_host_action
    internal gates fire (CONTROL_PLANE_BLOCKED), not plan_generated.

    The same governance BLOCK that stops the orchestrator path is invisible
    to the registry path — demonstrating the gap is structural, not incidental.
    """

    def setUp(self):
        _full_reset()

    def tearDown(self):
        _full_reset()

    @patch("assistant_os.classifier.classify_text")
    @patch("assistant_os.core.orchestrator._evaluate_mso_governance")
    def test_orchestrator_with_blocked_governance_returns_plan_generated(
        self, mock_governance, mock_classify
    ):
        """
        Reference: orchestrator correctly enforces BLOCKED governance.
        Returns RESULT_TYPE_PLAN_GENERATED (not execution result).
        Baseline for the contrast in the next test.
        """
        mock_classify.return_value = {
            "domain": "WORK",
            "operation": "WORK_QUERY",
            "confidence": 0.95,
            "alternatives": [],
            "needs_confirmation": False,
            "reason": "test",
            "type": "",
            "cognitive_load": "",
            "impact": "",
            "next_action": "",
        }
        mock_governance.return_value = _governance_blocked()

        from assistant_os.core.orchestrator import handle_request

        req = normalize_request(text="dame mis tareas")
        result = handle_request(req)

        # Orchestrator respects BLOCKED: returns plan, no execution
        self.assertEqual(result["result_type"], RESULT_TYPE_PLAN_GENERATED)
        self.assertTrue(result["data"]["governance_blocked"])

    @patch("assistant_os.core.orchestrator._evaluate_mso_governance")
    def test_host_registry_path_ignores_governance_blocked(
        self, mock_governance
    ):
        """
        CHARACTERIZATION: Registry path with governance BLOCKED set —
        _evaluate_mso_governance is NEVER called.

        The execute_host_action internal gate fires (CONTROL_PLANE_BLOCKED)
        because agent is inactive — NOT because governance blocked it.

        The same BLOCKED decision that stops the orchestrator has ZERO effect
        on the registry path. This is the documented bypass gap.
        """
        from assistant_os.agents.host_audit import HostErrorCode

        mock_governance.return_value = _governance_blocked()
        # Agent stays INACTIVE (no activate_agent call)

        request = HostActionRequest(
            execution_id="char-t6-001",
            action="open_app",
            confirmed=True,
            app_name="notepad",
        )

        result = _host_launcher_entrypoint(request)

        # Governance was NEVER consulted — registry bypasses it entirely
        mock_governance.assert_not_called()

        # Execution was refused by INTERNAL gate (CONTROL_PLANE_BLOCKED),
        # not by governance. Different reason, same surface outcome.
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, HostErrorCode.CONTROL_PLANE_BLOCKED)

    @patch("assistant_os.core.orchestrator._evaluate_mso_governance")
    def test_host_registry_path_with_active_agent_bypasses_governance(
        self, mock_governance
    ):
        """
        CHARACTERIZATION: When the HOST agent IS active, governance BLOCKED
        is still NEVER consulted on the registry path.

        With confirmed=False, Gate 1 fires (CONFIRMED_REQUIRED) instead.
        But with confirmed=True and active agent, execution would proceed
        through domain logic — again without governance consultation.

        This confirms the bypass is structural: active or inactive, the
        registry path never reaches governance.
        """
        from assistant_os.agents.host_audit import HostErrorCode

        mock_governance.return_value = _governance_blocked()
        activate_agent(HOST_AGENT_ID)  # agent is NOW active

        # confirmed=False → Gate 1 fires (CONFIRMED_REQUIRED)
        # Even with ACTIVE agent, governance is never called first
        request = HostActionRequest(
            execution_id="char-t6-002",
            action="open_app",
            confirmed=False,
            app_name="notepad",
        )

        result = _host_launcher_entrypoint(request)

        # Governance was NEVER consulted — bypass holds with active agent too
        mock_governance.assert_not_called()

        # Stopped by Gate 1, not governance
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, HostErrorCode.CONFIRMED_REQUIRED)


if __name__ == "__main__":
    unittest.main()
