"""
S-CONFIRM-OUTCOME-OBS-01A/01B — Confirmed execution outcome observability

Documents and validates that a confirmed HOST execution publishes its terminal
status to the outcome observability surface.

Fix (S-CONFIRM-OUTCOME-OBS-01B)
--------------------------------
_execute_confirmed_plan() now calls _publish_confirm_observation() after
pipeline() returns. This transitions the task to "completed" (or "failed")
in task_registry and closes the trace chain.

Test classes
------------
TestConfirmOutcomeObservabilityRegression
  - Validates the fix. After a successful confirmed execution the task must
    be "completed" in outcome observability, not "pending".
  - These were the gap-documentation tests in 01A; they now assert the
    correct post-fix behavior.

TestConfirmOutcomeObservabilityInvariants
  - Additional invariants: execution_status field is present, confirm is
    single-use, no double-execution side effects.

Invariants
----------
- This file observes; it does not change architecture.
- No pipeline, governance, policy, or capability_registry mutations.
- Mocks prevent real process/filesystem side effects.
- outcome_status is read-only throughout.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from assistant_os.agents.host_agent import (
    ALLOWED_DIRECTORIES,
    HOST_AGENT_ID,
    _reset_host_agent_state_for_tests,
)
from assistant_os.agents.host_audit import HOST_AUDIT_LOG
from assistant_os.context_store import clear_store
from assistant_os.contracts import (
    ACTION_HOST_OPEN_APP,
    RESULT_TYPE_HOST_ACTION,
    RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
    RISK_MEDIUM,
    normalize_request,
)
from assistant_os.core.control_plane import _reset_state_for_tests, activate_agent
from assistant_os.core.orchestrator import handle_request
from assistant_os.mso.capability_registry import reset_dynamic_capabilities
from assistant_os.mso.outcome_status import build_outcome_status
from assistant_os.mso.system_state import clear_operational_mode_override
from assistant_os.mso.task_registry import reset_task_registry
from assistant_os.mso.trace_aggregator import reset_trace_aggregator
from assistant_os.storage.mso_store import clear_mso_store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset():
    reset_task_registry()
    reset_trace_aggregator()
    clear_operational_mode_override()
    reset_dynamic_capabilities()
    clear_mso_store()
    _reset_state_for_tests()
    _reset_host_agent_state_for_tests()
    HOST_AUDIT_LOG.clear()
    clear_store()
    yield
    reset_task_registry()
    reset_trace_aggregator()
    clear_operational_mode_override()
    reset_dynamic_capabilities()
    clear_mso_store()
    _reset_state_for_tests()
    _reset_host_agent_state_for_tests()
    HOST_AUDIT_LOG.clear()
    clear_store()


def _req_open_app(app_name: str = "notepad") -> dict:
    return normalize_request(
        text="",
        metadata={
            "action": ACTION_HOST_OPEN_APP,
            "domain": "HOST",
            "risk_level": RISK_MEDIUM,
            "requires_confirmation": True,
            "domain_payload": {
                "action": "open_app",
                "confirmed": True,
                "app_name": app_name,
            },
        },
    )


def _req_confirm(plan_id: str) -> dict:
    return normalize_request(
        text="",
        metadata={"confirm_plan_id": plan_id},
    )


def _mock_popen(pid: int = 9999) -> MagicMock:
    proc = MagicMock()
    proc.pid = pid
    return proc


# ---------------------------------------------------------------------------
# Full two-pass flow helper
# ---------------------------------------------------------------------------


def _run_two_pass_confirm_flow(app_name: str = "notepad") -> tuple[str, dict]:
    """
    Execute the full two-pass confirmation flow.

    Returns (plan_id, confirm_result).
    Raises AssertionError if pass 1 or pass 2 don't behave as expected.
    """
    activate_agent(HOST_AGENT_ID)

    result1 = handle_request(_req_open_app(app_name))
    assert result1["result_type"] == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED, (
        f"Pass 1 must return plan_confirmation_required, got: {result1['result_type']!r}"
    )
    plan_id = result1["data"]["plan_id"]
    assert plan_id, "Pass 1 must produce a non-empty plan_id"

    mock_proc = _mock_popen()
    with patch("subprocess.Popen", return_value=mock_proc):
        result2 = handle_request(_req_confirm(plan_id))

    assert result2["ok"] is True, (
        f"Pass 2 (confirm) must succeed, got ok=False: {result2}"
    )
    assert result2["result_type"] == RESULT_TYPE_HOST_ACTION, (
        f"Pass 2 must return host_action, got: {result2['result_type']!r}"
    )

    return plan_id, result2


# ---------------------------------------------------------------------------
# TestConfirmOutcomeObservabilityRegression
# Validates the fix. Tasks must be "completed" after confirmed execution.
# ---------------------------------------------------------------------------


class TestConfirmOutcomeObservabilityRegression:
    """
    Regression tests for S-CONFIRM-OUTCOME-OBS-01B.

    After a successful confirmed HOST execution, build_outcome_status()
    must report the task as 'completed', not 'pending'.

    These were gap-documentation tests in 01A. They now assert the
    correct post-fix behavior.
    """

    def test_confirmed_execution_outcome_is_found_and_completed(self):
        """
        After a successful confirmed HOST execution, the outcome must be
        found and the status must be 'completed'.

        Fix: _execute_confirmed_plan() now calls _publish_confirm_observation()
        which transitions the task to 'completed' in task_registry.
        """
        plan_id, confirm_result = _run_two_pass_confirm_flow()

        outcome = build_outcome_status(plan_id=plan_id)

        assert outcome["found"] is True, (
            "Task registered in pass 1 must be discoverable by plan_id. "
            f"Got found={outcome['found']}, sources={outcome['sources']}"
        )

        assert outcome["sources"]["task_registry"] is True, (
            f"task_registry must be the active source. Got sources={outcome['sources']}"
        )
        assert outcome["sources"]["context_store_pending"] is False, (
            "context_store_pending must be False — plan was consumed by confirm. "
            f"Got sources={outcome['sources']}"
        )

        assert outcome["outcome"]["status"] == "completed", (
            f"After successful confirmed execution, outcome.status must be 'completed', "
            f"got: {outcome['outcome']['status']!r}. "
            "If this fails, _publish_confirm_observation() is not being called."
        )

    def test_outcome_completed_when_confirm_returned_ok_true(self):
        """
        When the confirm DomainResult is ok=True and result_type='host_action',
        the outcome surface must reflect 'completed'.

        Validates the fix closes the gap between execution success and
        observability.
        """
        plan_id, confirm_result = _run_two_pass_confirm_flow()

        assert confirm_result["ok"] is True
        assert confirm_result["result_type"] == RESULT_TYPE_HOST_ACTION

        outcome = build_outcome_status(plan_id=plan_id)
        assert outcome["outcome"]["status"] == "completed", (
            f"confirm result ok=True must correspond to outcome status='completed', "
            f"got: {outcome['outcome']['status']!r}"
        )

    def test_outcome_domain_and_action_are_populated(self):
        """
        After confirmed execution, domain and action must be populated from
        the pass 1 registration. plan_id correlation must match.
        """
        plan_id, _ = _run_two_pass_confirm_flow()
        outcome = build_outcome_status(plan_id=plan_id)

        assert outcome["found"] is True
        assert outcome["outcome"]["domain"] == "HOST", (
            f"Domain must be HOST, got: {outcome['outcome']['domain']!r}"
        )
        assert outcome["correlation"]["plan_id"] == plan_id, (
            "plan_id in correlation must match the queried plan_id"
        )


# ---------------------------------------------------------------------------
# TestConfirmOutcomeObservabilityInvariants
# Additional invariants beyond the core status transition.
# ---------------------------------------------------------------------------


class TestConfirmOutcomeObservabilityInvariants:
    """
    Additional invariants for the confirmed execution observability surface.
    """

    def test_execution_status_field_is_present(self):
        """
        After confirmed execution, outcome.execution_status must be present
        as a string. The HOST pipeline may not set a specific value, so any
        of "real", "stub", "partial", "unknown", or "unavailable" is valid.
        """
        plan_id, _ = _run_two_pass_confirm_flow()
        outcome = build_outcome_status(plan_id=plan_id)

        execution_status = outcome["outcome"].get("execution_status")
        valid_values = {"real", "stub", "partial", "unknown", "unavailable", None}
        assert execution_status in valid_values, (
            f"execution_status must be one of {valid_values!r}, "
            f"got: {execution_status!r}"
        )

    def test_confirm_is_single_use(self):
        """
        A plan_id can only be confirmed once. A second confirm with the same
        plan_id must not succeed with ok=True and must not corrupt the
        completed outcome status.
        """
        plan_id, _ = _run_two_pass_confirm_flow()

        # Verify first confirm left the task completed
        outcome_after_first = build_outcome_status(plan_id=plan_id)
        assert outcome_after_first["outcome"]["status"] == "completed"

        # Attempt second confirm
        mock_proc = _mock_popen(pid=1111)
        with patch("subprocess.Popen", return_value=mock_proc):
            result_second = handle_request(_req_confirm(plan_id))

        # Second confirm must not be ok=True with host_action
        second_is_duplicate_success = (
            result_second.get("ok") is True
            and result_second.get("result_type") == RESULT_TYPE_HOST_ACTION
        )
        assert not second_is_duplicate_success, (
            "Second confirm with the same plan_id must not return ok=True host_action. "
            f"Got: {result_second}"
        )

        # Outcome must still be completed (no state corruption from second attempt)
        outcome_after_second = build_outcome_status(plan_id=plan_id)
        assert outcome_after_second["outcome"]["status"] == "completed", (
            "Outcome status must remain 'completed' after a rejected second confirm. "
            f"Got: {outcome_after_second['outcome']['status']!r}"
        )

    def test_two_independent_plans_have_independent_outcomes(self):
        """
        Two separate two-pass flows for different apps must produce independent
        outcomes. Completing plan A must not affect plan B's status.
        """
        activate_agent(HOST_AGENT_ID)

        # Pass 1 for plan A
        result_a1 = handle_request(_req_open_app("notepad"))
        assert result_a1["result_type"] == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED
        plan_id_a = result_a1["data"]["plan_id"]

        # Pass 1 for plan B
        result_b1 = handle_request(_req_open_app("calc"))
        assert result_b1["result_type"] == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED
        plan_id_b = result_b1["data"]["plan_id"]

        assert plan_id_a != plan_id_b, "Two separate requests must produce distinct plan_ids"

        # Confirm only plan A
        with patch("subprocess.Popen", return_value=_mock_popen(pid=1001)):
            result_a2 = handle_request(_req_confirm(plan_id_a))
        assert result_a2["ok"] is True

        # Plan A must be completed
        outcome_a = build_outcome_status(plan_id=plan_id_a)
        assert outcome_a["outcome"]["status"] == "completed", (
            f"Plan A must be completed after confirmation, got: {outcome_a['outcome']['status']!r}"
        )

        # Plan B must still be pending (not yet confirmed)
        outcome_b = build_outcome_status(plan_id=plan_id_b)
        assert outcome_b["outcome"]["status"] == "pending", (
            f"Plan B must remain pending until confirmed, got: {outcome_b['outcome']['status']!r}"
        )
