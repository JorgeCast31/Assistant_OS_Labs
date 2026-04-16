"""
Tests — control_plane.py

Coverage
--------
A. AgentStatus defaults and transitions
B. In-flight registration and retrieval
C. kill_switch — quarantine + abort_in_flight
D. abort_in_flight — per-PID SIGTERM, error handling
D2. deregister_in_flight
D3. reconcile_in_flight (Phase 2.5)
E. Thread safety (basic)
"""

from __future__ import annotations

import os
import signal
from unittest.mock import call, patch

import pytest

import assistant_os.core.control_plane as cp
from assistant_os.core.control_plane import (
    AbortResult,
    AgentStatus,
    KillSwitchResult,
    ReconcileResult,
    _reset_state_for_tests,
    abort_in_flight,
    activate_agent,
    clear_in_flight,
    deregister_in_flight,
    get_agent_status,
    get_in_flight,
    kill_switch,
    pause_agent,
    quarantine_agent,
    reconcile_in_flight,
    register_in_flight,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Guarantee clean module state before and after every test."""
    _reset_state_for_tests()
    yield
    _reset_state_for_tests()


# ===========================================================================
# A. AgentStatus defaults and transitions
# ===========================================================================


class TestAgentStatus:
    def test_unknown_agent_defaults_to_paused(self):
        assert get_agent_status("never_registered") == AgentStatus.PAUSED

    def test_activate_sets_active(self):
        activate_agent("agent-1")
        assert get_agent_status("agent-1") == AgentStatus.ACTIVE

    def test_pause_sets_paused(self):
        activate_agent("agent-1")
        pause_agent("agent-1")
        assert get_agent_status("agent-1") == AgentStatus.PAUSED

    def test_quarantine_sets_quarantine(self):
        activate_agent("agent-1")
        quarantine_agent("agent-1")
        assert get_agent_status("agent-1") == AgentStatus.QUARANTINE

    def test_activate_after_quarantine(self):
        quarantine_agent("agent-1")
        activate_agent("agent-1")
        assert get_agent_status("agent-1") == AgentStatus.ACTIVE

    def test_multiple_agents_independent(self):
        activate_agent("agent-a")
        quarantine_agent("agent-b")
        assert get_agent_status("agent-a") == AgentStatus.ACTIVE
        assert get_agent_status("agent-b") == AgentStatus.QUARANTINE


# ===========================================================================
# B. In-flight registration
# ===========================================================================


class TestInFlight:
    def test_register_single_pid(self):
        register_in_flight("agent-1", 1234, "exec-001")
        records = get_in_flight("agent-1")
        assert len(records) == 1
        assert records[0]["pid"] == 1234
        assert records[0]["execution_id"] == "exec-001"

    def test_register_multiple_pids(self):
        register_in_flight("agent-1", 100, "exec-001")
        register_in_flight("agent-1", 200, "exec-002")
        records = get_in_flight("agent-1")
        pids = {r["pid"] for r in records}
        assert pids == {100, 200}

    def test_get_in_flight_returns_copy(self):
        register_in_flight("agent-1", 999, "exec-x")
        records = get_in_flight("agent-1")
        records.clear()  # mutate the returned copy
        assert len(get_in_flight("agent-1")) == 1  # original unaffected

    def test_get_in_flight_empty_for_unknown_agent(self):
        assert get_in_flight("nobody") == []

    def test_clear_in_flight_removes_all(self):
        register_in_flight("agent-1", 1, "e1")
        register_in_flight("agent-1", 2, "e2")
        clear_in_flight("agent-1")
        assert get_in_flight("agent-1") == []

    def test_clear_in_flight_idempotent_on_unknown(self):
        clear_in_flight("nobody")  # must not raise

    def test_multiple_agents_independent_in_flight(self):
        register_in_flight("agent-a", 10, "ea1")
        register_in_flight("agent-b", 20, "eb1")
        a_records = get_in_flight("agent-a")
        b_records = get_in_flight("agent-b")
        assert len(a_records) == 1
        assert a_records[0]["pid"] == 10
        assert a_records[0]["execution_id"] == "ea1"
        assert len(b_records) == 1
        assert b_records[0]["pid"] == 20
        assert b_records[0]["execution_id"] == "eb1"


# ===========================================================================
# C. kill_switch
# ===========================================================================


class TestKillSwitch:
    def test_kill_switch_quarantines_agent(self):
        activate_agent("agent-1")
        with patch("os.kill"):
            kill_switch("agent-1")
        assert get_agent_status("agent-1") == AgentStatus.QUARANTINE

    def test_kill_switch_returns_kill_switch_result(self):
        activate_agent("agent-1")
        with patch("os.kill"):
            result = kill_switch("agent-1")
        assert isinstance(result, KillSwitchResult)
        assert result.agent_id == "agent-1"

    def test_kill_switch_no_in_flight_gives_empty_abort_results(self):
        activate_agent("agent-1")
        result = kill_switch("agent-1")
        assert result.abort_results == []
        assert result.all_aborted is True  # vacuously true

    def test_kill_switch_sees_registered_pid(self):
        activate_agent("agent-1")
        register_in_flight("agent-1", 5555, "exec-555")

        with patch("os.kill") as mock_kill:
            result = kill_switch("agent-1")

        mock_kill.assert_any_call(5555, signal.SIGTERM)
        sigterm_calls = [c for c in mock_kill.call_args_list if c.args[1] == signal.SIGTERM]
        assert len(sigterm_calls) == 1
        assert len(result.abort_results) == 1
        assert result.abort_results[0].pid == 5555
        assert result.abort_results[0].execution_id == "exec-555"
        assert result.abort_results[0].success is True

    def test_kill_switch_aborts_multiple_pids(self):
        activate_agent("agent-1")
        register_in_flight("agent-1", 100, "e1")
        register_in_flight("agent-1", 200, "e2")
        register_in_flight("agent-1", 300, "e3")

        with patch("os.kill") as mock_kill:
            result = kill_switch("agent-1")

        sigterm_calls = [c for c in mock_kill.call_args_list if c.args[1] == signal.SIGTERM]
        assert len(sigterm_calls) == 3
        pids = {r.pid for r in result.abort_results}
        assert pids == {100, 200, 300}
        assert all(r.success for r in result.abort_results)

    def test_kill_switch_clears_in_flight_after_abort(self):
        activate_agent("agent-1")
        register_in_flight("agent-1", 777, "e7")

        with patch("os.kill"):
            kill_switch("agent-1")

        assert get_in_flight("agent-1") == []

    def test_kill_switch_on_already_quarantined_agent(self):
        quarantine_agent("agent-1")
        register_in_flight("agent-1", 888, "e8")

        with patch("os.kill") as mock_kill:
            result = kill_switch("agent-1")

        mock_kill.assert_any_call(888, signal.SIGTERM)
        sigterm_calls = [c for c in mock_kill.call_args_list if c.args[1] == signal.SIGTERM]
        assert len(sigterm_calls) == 1
        assert get_agent_status("agent-1") == AgentStatus.QUARANTINE


# ===========================================================================
# D. abort_in_flight — error handling
# ===========================================================================


class TestAbortInFlight:
    def test_abort_success_when_os_kill_succeeds(self):
        register_in_flight("agent-1", 1001, "exec-1001")
        with patch("os.kill"):
            results = abort_in_flight("agent-1")
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].error is None

    def test_abort_captures_oserror_per_pid(self):
        register_in_flight("agent-1", 9999, "dead-exec")
        with patch("os.kill", side_effect=OSError("no such process")):
            results = abort_in_flight("agent-1")
        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error is not None

    def test_abort_continues_after_single_pid_error(self):
        register_in_flight("agent-1", 111, "e1")
        register_in_flight("agent-1", 222, "e2")

        def kill_side_effect(pid, sig):
            if pid == 111:
                raise OSError("process gone")
            # pid 222 succeeds

        with patch("os.kill", side_effect=kill_side_effect):
            results = abort_in_flight("agent-1")

        assert len(results) == 2
        by_pid = {r.pid: r for r in results}
        assert by_pid[111].success is False
        assert by_pid[222].success is True

    def test_abort_empty_returns_empty_list(self):
        results = abort_in_flight("nobody")
        assert results == []

    def test_all_aborted_false_when_any_failed(self):
        result = KillSwitchResult(
            agent_id="a",
            abort_results=[
                AbortResult(pid=1, execution_id="e1", success=True),
                AbortResult(pid=2, execution_id="e2", success=False, error="gone"),
            ],
        )
        assert result.all_aborted is False

    def test_all_aborted_true_when_all_succeeded(self):
        result = KillSwitchResult(
            agent_id="a",
            abort_results=[
                AbortResult(pid=1, execution_id="e1", success=True),
                AbortResult(pid=2, execution_id="e2", success=True),
            ],
        )
        assert result.all_aborted is True


# ===========================================================================
# D2. deregister_in_flight
# ===========================================================================


class TestDeregisterInFlight:
    def test_removes_target_pid(self):
        register_in_flight("agent-1", 1234, "exec-001")
        deregister_in_flight("agent-1", 1234)
        assert get_in_flight("agent-1") == []

    def test_leaves_other_pids_intact(self):
        register_in_flight("agent-1", 100, "exec-100")
        register_in_flight("agent-1", 200, "exec-200")
        deregister_in_flight("agent-1", 100)
        records = get_in_flight("agent-1")
        assert len(records) == 1
        assert records[0]["pid"] == 200

    def test_idempotent_on_absent_pid(self):
        """Removing a pid that was never registered must not raise."""
        register_in_flight("agent-1", 111, "exec-111")
        deregister_in_flight("agent-1", 999)  # 999 never registered
        assert len(get_in_flight("agent-1")) == 1

    def test_idempotent_on_unknown_agent(self):
        """Deregistering from an agent with no records must not raise."""
        deregister_in_flight("nobody", 1)

    def test_removes_only_matching_pid_by_value(self):
        register_in_flight("agent-1", 50, "exec-50")
        register_in_flight("agent-1", 51, "exec-51")
        register_in_flight("agent-1", 52, "exec-52")
        deregister_in_flight("agent-1", 51)
        pids = {r["pid"] for r in get_in_flight("agent-1")}
        assert pids == {50, 52}

    def test_does_not_affect_other_agents(self):
        register_in_flight("agent-a", 10, "ea1")
        register_in_flight("agent-b", 10, "eb1")
        deregister_in_flight("agent-a", 10)
        assert get_in_flight("agent-a") == []
        b_records = get_in_flight("agent-b")
        assert len(b_records) == 1
        assert b_records[0]["pid"] == 10
        assert b_records[0]["execution_id"] == "eb1"


# ===========================================================================
# D3. reconcile_in_flight (Phase 2.5)
# ===========================================================================


class TestReconcileInFlight:
    def test_empty_registry_returns_empty_result(self):
        result = reconcile_in_flight("agent-1")
        assert isinstance(result, ReconcileResult)
        assert result.alive == []
        assert result.cleaned == []

    def test_alive_pid_stays_in_registry(self):
        register_in_flight("agent-1", 1234, "exec-001")
        with patch("os.kill"):  # signal 0 succeeds → alive
            result = reconcile_in_flight("agent-1")
        assert len(result.alive) == 1
        assert result.alive[0]["pid"] == 1234
        assert result.cleaned == []
        # Still in registry
        assert len(get_in_flight("agent-1")) == 1

    def test_dead_pid_removed_from_registry(self):
        register_in_flight("agent-1", 9999, "exec-dead")
        with patch("os.kill", side_effect=OSError("no such process")):
            result = reconcile_in_flight("agent-1")
        assert result.alive == []
        assert len(result.cleaned) == 1
        assert result.cleaned[0]["pid"] == 9999
        # Removed from registry
        assert get_in_flight("agent-1") == []

    def test_mixed_alive_and_dead(self):
        register_in_flight("agent-1", 100, "exec-100")
        register_in_flight("agent-1", 200, "exec-200")
        register_in_flight("agent-1", 300, "exec-300")

        def fake_kill(pid, sig):
            if pid == 200:
                raise OSError("gone")

        with patch("os.kill", side_effect=fake_kill):
            result = reconcile_in_flight("agent-1")

        alive_pids  = {r["pid"] for r in result.alive}
        cleaned_pids = {r["pid"] for r in result.cleaned}
        assert alive_pids  == {100, 300}
        assert cleaned_pids == {200}

        remaining = {r["pid"] for r in get_in_flight("agent-1")}
        assert remaining == {100, 300}

    def test_permission_error_treated_as_alive(self):
        """PermissionError means the process EXISTS — must not be cleaned."""
        register_in_flight("agent-1", 5555, "exec-perm")
        with patch("os.kill", side_effect=PermissionError("access denied")):
            result = reconcile_in_flight("agent-1")
        assert len(result.alive) == 1
        assert result.cleaned == []
        assert len(get_in_flight("agent-1")) == 1

    def test_does_not_affect_other_agents(self):
        register_in_flight("agent-a", 11, "ea-1")
        register_in_flight("agent-b", 22, "eb-1")

        def fake_kill(pid, sig):
            if pid == 11:
                raise OSError("gone")

        with patch("os.kill", side_effect=fake_kill):
            reconcile_in_flight("agent-a")

        # agent-a dead pid removed; agent-b untouched
        assert get_in_flight("agent-a") == []
        b_records = get_in_flight("agent-b")
        assert len(b_records) == 1
        assert b_records[0]["pid"] == 22
        assert b_records[0]["execution_id"] == "eb-1"

    def test_returns_reconcile_result_type(self):
        register_in_flight("agent-1", 777, "exec-777")
        with patch("os.kill"):
            result = reconcile_in_flight("agent-1")
        assert isinstance(result, ReconcileResult)
        assert result.agent_id == "agent-1"

    def test_kill_switch_after_reconcile_only_sees_alive_pids(self):
        """Reconcile removes a dead pid; subsequent kill_switch skips it."""
        register_in_flight("agent-1", 444, "exec-dead")
        register_in_flight("agent-1", 555, "exec-alive")

        # Reconcile: 444 is dead, 555 is alive
        def check_alive(pid, sig):
            if pid == 444 and sig == 0:
                raise OSError("gone")

        with patch("os.kill", side_effect=check_alive):
            reconcile_in_flight("agent-1")

        # After reconcile, only 555 remains
        with patch("os.kill") as mock_kill:
            result = kill_switch("agent-1")

        called_pids = {c.args[0] for c in mock_kill.call_args_list}
        assert 555 in called_pids
        assert 444 not in called_pids


# ===========================================================================
# E. Basic thread safety
# ===========================================================================


class TestThreadSafety:
    def test_concurrent_register_and_read(self):
        """Multiple threads registering in parallel must not lose entries."""
        import threading

        activate_agent("agent-concurrent")
        errors = []

        def register(n):
            try:
                register_in_flight("agent-concurrent", n, f"exec-{n}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=register, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        records = get_in_flight("agent-concurrent")
        assert len(records) == 50
