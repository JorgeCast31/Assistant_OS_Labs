"""
Tests — host_agent.py  (Phase 1 + Phase 2 + Phase 2.5 hardening)

Coverage
--------
A. Gate: confirmed flag
B. Gate: agent status (ACTIVE / PAUSED / QUARANTINE) — always HOST_AGENT_ID
C. Gate: APP_REGISTRY (notepad, calc; rejects unknown)
D. Intent audit emitted BEFORE Popen; HostAuditError aborts launch
E. Outcome audit emitted AFTER Popen with pid
F. pid registered in _IN_FLIGHT after successful launch
G. HostActionResult correctness (incl. error_code field)
H. No subprocess launched on any failure path
I. Registry integration — host_launcher entrypoint delegates correctly
J. Canonical identity — HOST_AGENT_ID is the only identity used end-to-end
K. close_pid (Phase 2)
L. open_directory (Phase 2)
M. open_url (Phase 2)
N. Action audit events (Phase 2)
O. Phase 2 integration
P. validate_allowed_directory (Phase 2.5)
Q. validate_allowed_url (Phase 2.5)
R. Error codes on every failure path (Phase 2.5)
S. Rejection audit on gate failures (Phase 2.5)
T. Rate limits (Phase 2.5)
U. close_pid with stale PID / reconcile (Phase 2.5)
"""

from __future__ import annotations

import signal
import unittest.mock
from unittest.mock import MagicMock, call, patch

import pytest

from assistant_os.agents.host_agent import (
    APP_REGISTRY,
    ALLOWED_DIRECTORIES,
    ALLOWED_URL_DOMAINS,
    ALLOWED_URL_SCHEMES,
    WRITE_SANDBOX_DIRECTORIES,
    ALLOWED_WRITE_EXTENSIONS,
    MAX_WRITE_SIZE_BYTES,
    HOST_AGENT_ID,
    HostActionRequest,
    HostActionResult,
    _reset_host_agent_state_for_tests,
    _WINDOWS_RESERVED_STEMS,
    _check_no_symlink_in_path,
    _reject_unsafe_path_components,
    execute_host_action,
    validate_allowed_directory,
    validate_allowed_url,
    validate_allowed_write_path,
    validate_allowed_write_directory,
)
from assistant_os.agents.host_audit import (
    HOST_AUDIT_LOG,
    HostAuditEventType,
    HostErrorCode,
)
from assistant_os.core.control_plane import (
    AgentStatus,
    _reset_state_for_tests,
    activate_agent,
    get_agent_status,
    get_in_flight,
    kill_switch,
    quarantine_agent,
    reconcile_in_flight,
    register_in_flight,
)


@pytest.fixture(autouse=True)
def reset():
    """Clean state before and after every test."""
    _reset_state_for_tests()
    _reset_host_agent_state_for_tests()
    HOST_AUDIT_LOG.clear()
    yield
    _reset_state_for_tests()
    _reset_host_agent_state_for_tests()
    HOST_AUDIT_LOG.clear()


def _active_request(
    app_name: str = "notepad",
    confirmed: bool = True,
    execution_id: str = "exec-001",
) -> HostActionRequest:
    """Build a request with HOST_AGENT_ID pre-activated."""
    activate_agent(HOST_AGENT_ID)
    return HostActionRequest(
        app_name=app_name,
        execution_id=execution_id,
        confirmed=confirmed,
    )


# ===========================================================================
# A. Gate: confirmed flag
# ===========================================================================


class TestConfirmedGate:
    def test_confirmed_false_returns_error(self):
        req = _active_request(confirmed=False)
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error is not None
        mock_popen.assert_not_called()

    def test_confirmed_none_treated_as_falsy(self):
        """confirmed=None is falsy; must not launch."""
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(
            app_name="notepad", execution_id="e1",
            confirmed=None,  # type: ignore[arg-type]
        )
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_confirmed_true_proceeds_past_gate(self):
        """confirmed=True alone is not enough (also needs ACTIVE), but does not fail at gate 1.

        HOST_AGENT_ID is PAUSED by default → fails at gate 2, not gate 1.
        """
        req = HostActionRequest(
            app_name="notepad", execution_id="e1", confirmed=True,
        )
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        # fails at gate 2 (not ACTIVE), not gate 1
        assert result.ok is False
        assert "ACTIVE" in (result.error or "")
        mock_popen.assert_not_called()


# ===========================================================================
# B. Gate: agent status — always checked against HOST_AGENT_ID
# ===========================================================================


class TestAgentStatusGate:
    def test_paused_by_default_does_not_launch(self):
        """HOST_AGENT_ID is PAUSED by default (never activated) → no launch."""
        req = HostActionRequest(
            app_name="notepad", execution_id="e1", confirmed=True,
        )
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        assert "ACTIVE" in (result.error or "")
        mock_popen.assert_not_called()

    def test_quarantined_does_not_launch(self):
        quarantine_agent(HOST_AGENT_ID)
        req = HostActionRequest(
            app_name="notepad", execution_id="e1", confirmed=True,
        )
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        assert "ACTIVE" in (result.error or "")
        mock_popen.assert_not_called()

    def test_active_passes_status_gate(self):
        """HOST_AGENT_ID ACTIVE + valid app + confirmed=True → Popen called."""
        req = _active_request(app_name="notepad", confirmed=True)
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            result = execute_host_action(req)
        assert result.ok is True
        mock_popen.assert_called_once()

    def test_error_message_includes_status_value(self):
        """Error message names the status of HOST_AGENT_ID."""
        req = HostActionRequest(
            app_name="notepad", execution_id="e1", confirmed=True,
        )
        result = execute_host_action(req)
        assert "paused" in (result.error or "").lower()

    def test_error_message_includes_host_agent_id(self):
        """Error message names HOST_AGENT_ID so it's traceable."""
        req = HostActionRequest(
            app_name="notepad", execution_id="e1", confirmed=True,
        )
        result = execute_host_action(req)
        assert HOST_AGENT_ID in (result.error or "")


# ===========================================================================
# C. Gate: APP_REGISTRY
# ===========================================================================


class TestAppRegistryGate:
    def test_notepad_is_in_registry(self):
        assert "notepad" in APP_REGISTRY
        assert APP_REGISTRY["notepad"] == r"C:\Windows\System32\notepad.exe"

    def test_calc_is_in_registry(self):
        assert "calc" in APP_REGISTRY
        assert APP_REGISTRY["calc"] == r"C:\Windows\System32\calc.exe"

    def test_explorer_is_in_registry(self):
        assert "explorer" in APP_REGISTRY
        assert APP_REGISTRY["explorer"] == r"C:\Windows\explorer.exe"

    def test_unknown_app_name_returns_error(self):
        req = _active_request(app_name="malware")
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        assert "APP_REGISTRY" in (result.error or "")
        assert result.error_code == HostErrorCode.INVALID_APP_NAME
        mock_popen.assert_not_called()

    def test_shell_command_rejected(self):
        req = _active_request(app_name="cmd /c del C:\\Windows\\System32")
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_path_traversal_rejected(self):
        req = _active_request(app_name="../../evil.exe")
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_empty_app_name_rejected(self):
        req = _active_request(app_name="")
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_notepad_launches_absolute_path(self):
        req = _active_request(app_name="notepad")
        mock_proc = MagicMock()
        mock_proc.pid = 100
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            execute_host_action(req)
        mock_popen.assert_called_once_with([r"C:\Windows\System32\notepad.exe"])

    def test_calc_launches_absolute_path(self):
        req = _active_request(app_name="calc")
        mock_proc = MagicMock()
        mock_proc.pid = 200
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            execute_host_action(req)
        mock_popen.assert_called_once_with([r"C:\Windows\System32\calc.exe"])

    def test_popen_called_without_shell_true(self):
        """Verify shell=True is never passed."""
        req = _active_request(app_name="notepad")
        mock_proc = MagicMock()
        mock_proc.pid = 42
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            execute_host_action(req)
        _, kwargs = mock_popen.call_args
        assert kwargs.get("shell", False) is False


# ===========================================================================
# D. Intent audit — emitted BEFORE Popen; HostAuditError aborts launch
# ===========================================================================


class TestIntentAudit:
    def test_intent_event_emitted_before_popen(self):
        """Intent audit must be recorded before Popen is called."""
        call_order = []

        def record_intent(*args, **kwargs):
            call_order.append("intent")

        mock_proc = MagicMock()
        mock_proc.pid = 555

        def record_popen(*args, **kwargs):
            call_order.append("popen")
            return mock_proc

        req = _active_request(app_name="notepad")

        with (
            patch("assistant_os.agents.host_agent.emit_host_intent", side_effect=record_intent),
            patch("subprocess.Popen", side_effect=record_popen),
            patch("assistant_os.agents.host_agent.emit_host_outcome"),
            patch("assistant_os.agents.host_agent.register_in_flight"),
        ):
            execute_host_action(req)

        assert call_order.index("intent") < call_order.index("popen"), (
            "intent audit must be emitted BEFORE Popen"
        )

    def test_host_audit_error_aborts_launch(self):
        """If intent audit raises HostAuditError, Popen must NOT be called."""
        from assistant_os.agents.host_audit import HostAuditError

        req = _active_request(app_name="notepad")

        with (
            patch(
                "assistant_os.agents.host_agent.emit_host_intent",
                side_effect=HostAuditError("disk full"),
            ),
            patch("subprocess.Popen") as mock_popen,
        ):
            result = execute_host_action(req)

        assert result.ok is False
        assert "intent audit failed" in (result.error or "")
        mock_popen.assert_not_called()

    def test_intent_audit_receives_host_agent_id(self):
        """Intent audit must always receive HOST_AGENT_ID — never a caller-supplied value."""
        req = _active_request(app_name="calc", execution_id="exec-calc-99")
        mock_proc = MagicMock()
        mock_proc.pid = 1

        with (
            patch("assistant_os.agents.host_agent.emit_host_intent") as mock_intent,
            patch("subprocess.Popen", return_value=mock_proc),
            patch("assistant_os.agents.host_agent.emit_host_outcome"),
            patch("assistant_os.agents.host_agent.register_in_flight"),
        ):
            execute_host_action(req)

        mock_intent.assert_called_once_with(
            agent_id=HOST_AGENT_ID,
            app_name="calc",
            execution_id="exec-calc-99",
            executable=r"C:\Windows\System32\calc.exe",
        )

    def test_intent_event_in_host_audit_log(self):
        req = _active_request(app_name="notepad", execution_id="exec-np-log")
        mock_proc = MagicMock()
        mock_proc.pid = 77

        with patch("subprocess.Popen", return_value=mock_proc):
            execute_host_action(req)

        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_INTENT)
        assert len(events) == 1
        assert events[0].execution_id == "exec-np-log"
        assert events[0].agent_id == HOST_AGENT_ID


# ===========================================================================
# E. Outcome audit — emitted AFTER Popen with pid
# ===========================================================================


class TestOutcomeAudit:
    def test_outcome_event_emitted_after_popen(self):
        call_order = []

        def record_outcome(*args, **kwargs):
            call_order.append("outcome")

        mock_proc = MagicMock()
        mock_proc.pid = 999

        def record_popen(*args, **kwargs):
            call_order.append("popen")
            return mock_proc

        req = _active_request(app_name="notepad")

        with (
            patch("assistant_os.agents.host_agent.emit_host_intent"),
            patch("subprocess.Popen", side_effect=record_popen),
            patch("assistant_os.agents.host_agent.emit_host_outcome", side_effect=record_outcome),
            patch("assistant_os.agents.host_agent.register_in_flight"),
        ):
            execute_host_action(req)

        assert call_order.index("popen") < call_order.index("outcome"), (
            "outcome audit must be emitted AFTER Popen"
        )

    def test_outcome_event_in_host_audit_log_with_pid(self):
        req = _active_request(app_name="calc", execution_id="exec-outcome-1")
        mock_proc = MagicMock()
        mock_proc.pid = 4242

        with patch("subprocess.Popen", return_value=mock_proc):
            execute_host_action(req)

        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_OUTCOME)
        assert len(events) == 1
        assert events[0].pid == 4242
        assert events[0].execution_id == "exec-outcome-1"
        assert events[0].agent_id == HOST_AGENT_ID

    def test_outcome_not_emitted_when_intent_fails(self):
        from assistant_os.agents.host_audit import HostAuditError

        req = _active_request(app_name="notepad")

        with (
            patch(
                "assistant_os.agents.host_agent.emit_host_intent",
                side_effect=HostAuditError("fail"),
            ),
            patch("subprocess.Popen"),
        ):
            execute_host_action(req)

        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_OUTCOME) == 0

    def test_outcome_not_emitted_when_not_active(self):
        """HOST_AGENT_ID not activated → no outcome event."""
        req = HostActionRequest(
            app_name="notepad", execution_id="e1", confirmed=True,
        )
        execute_host_action(req)
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_OUTCOME) == 0


# ===========================================================================
# F. pid registered in _IN_FLIGHT
# ===========================================================================


class TestInFlightRegistration:
    def test_pid_registered_after_successful_launch(self):
        req = _active_request(app_name="notepad", execution_id="exec-flight-1")
        mock_proc = MagicMock()
        mock_proc.pid = 7777

        with patch("subprocess.Popen", return_value=mock_proc):
            result = execute_host_action(req)

        assert result.ok is True
        records = get_in_flight(HOST_AGENT_ID)
        assert any(r["pid"] == 7777 and r["execution_id"] == "exec-flight-1" for r in records)

    def test_pid_not_registered_when_confirmed_false(self):
        req = _active_request(app_name="notepad", confirmed=False, execution_id="e-nope")
        execute_host_action(req)
        assert get_in_flight(HOST_AGENT_ID) == []

    def test_pid_not_registered_when_not_active(self):
        req = HostActionRequest(
            app_name="notepad", execution_id="e-nope", confirmed=True,
        )
        execute_host_action(req)
        assert get_in_flight(HOST_AGENT_ID) == []

    def test_pid_not_registered_when_app_not_in_registry(self):
        req = _active_request(app_name="evil", execution_id="e-nope")
        execute_host_action(req)
        assert get_in_flight(HOST_AGENT_ID) == []

    def test_register_in_flight_called_with_host_agent_id(self):
        """register_in_flight must always receive HOST_AGENT_ID."""
        req = _active_request(app_name="calc", execution_id="exec-rif-1")
        mock_proc = MagicMock()
        mock_proc.pid = 8888

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("assistant_os.agents.host_agent.register_in_flight") as mock_rif,
        ):
            execute_host_action(req)

        mock_rif.assert_called_once_with(HOST_AGENT_ID, 8888, "exec-rif-1", action="open_app")


# ===========================================================================
# G. HostActionResult correctness
# ===========================================================================


class TestHostActionResult:
    def test_successful_result_has_pid(self):
        req = _active_request(app_name="notepad", execution_id="exec-res-1")
        mock_proc = MagicMock()
        mock_proc.pid = 3333

        with patch("subprocess.Popen", return_value=mock_proc):
            result = execute_host_action(req)

        assert result.ok is True
        assert result.pid == 3333
        assert result.execution_id == "exec-res-1"
        assert result.app_name == "notepad"
        assert result.error is None

    def test_failure_result_has_no_pid(self):
        req = _active_request(app_name="notepad", confirmed=False)
        result = execute_host_action(req)
        assert result.ok is False
        assert result.pid is None

    def test_result_echoes_execution_id_on_failure(self):
        req = _active_request(app_name="notepad", confirmed=False, execution_id="echo-me")
        result = execute_host_action(req)
        assert result.execution_id == "echo-me"

    def test_result_echoes_app_name_on_registry_failure(self):
        req = _active_request(app_name="blocked_app")
        result = execute_host_action(req)
        assert result.app_name == "blocked_app"


# ===========================================================================
# H. No subprocess on any failure path (consolidated)
# ===========================================================================


class TestNoSubprocessOnFailure:
    @pytest.mark.parametrize("confirmed", [False, None, 0, ""])
    def test_falsy_confirmed_never_calls_popen(self, confirmed):
        # Confirmed gate fires before status gate — no need to activate.
        req = HostActionRequest(
            app_name="notepad", execution_id="e1",
            confirmed=confirmed,  # type: ignore[arg-type]
        )
        with patch("subprocess.Popen") as mock_popen:
            execute_host_action(req)
        mock_popen.assert_not_called()

    @pytest.mark.parametrize("app_name", ["", "cmd", "powershell", "evil.exe", "../etc/passwd"])
    def test_non_allowlisted_app_never_calls_popen(self, app_name):
        req = _active_request(app_name=app_name)
        with patch("subprocess.Popen") as mock_popen:
            execute_host_action(req)
        mock_popen.assert_not_called()


# ===========================================================================
# I. Registry integration
# ===========================================================================


class TestRegistryIntegration:
    def test_host_launcher_registered_in_agent_registry(self):
        from assistant_os.agents.registry import get_agent
        agent = get_agent("host_launcher")
        assert agent["name"]            == "host_launcher"
        assert agent["domain"]          == "HOST"
        assert agent["input_contract"]  == "HostActionRequest"
        assert agent["output_contract"] == "HostActionResult"
        assert callable(agent["entrypoint"])

    def test_host_launcher_entrypoint_blocks_direct_call_without_authority_context(self):
        """Direct registry call without a valid Police token must be rejected closed.

        HOST_AGENT_ID is activated (gate 1 clears), but no authority context /
        token is provided, so the token-bound Police Gate fires and denies.
        """
        from assistant_os.agents.registry import get_agent

        req = _active_request(app_name="notepad", execution_id="exec-reg-1")

        with patch("subprocess.Popen") as mock_popen:
            agent = get_agent("host_launcher")
            result = agent["entrypoint"](req)

        assert result.ok is False
        assert result.error is not None
        assert "Police" in result.error or "token" in result.error.lower()
        mock_popen.assert_not_called()

    def test_host_launcher_entrypoint_respects_gates(self):
        """Entrypoint must enforce all gates — not bypass them.

        HOST_AGENT_ID not activated → gate 2 fires.
        """
        from assistant_os.agents.registry import get_agent

        req = HostActionRequest(
            app_name="notepad", execution_id="e1", confirmed=True,
        )
        with patch("subprocess.Popen") as mock_popen:
            agent = get_agent("host_launcher")
            result = agent["entrypoint"](req)

        assert result.ok is False
        mock_popen.assert_not_called()

    def test_registry_key_matches_host_agent_id(self):
        """AGENT_REGISTRY key must equal HOST_AGENT_ID — single canonical name."""
        from assistant_os.agents.registry import get_agent
        agent = get_agent(HOST_AGENT_ID)
        assert agent["name"] == HOST_AGENT_ID


# ===========================================================================
# J. Canonical identity — HOST_AGENT_ID is the only identity end-to-end
# ===========================================================================


class TestCanonicalIdentity:
    """Verify that HOST_AGENT_ID = 'host_launcher' is the single identity used
    across _IN_FLIGHT, audit events, and kill_switch.

    These tests are the primary regression guard against identity fragmentation.
    They must fail if any layer starts using a different agent_id.
    """

    def test_host_agent_id_constant_is_host_launcher(self):
        assert HOST_AGENT_ID == "host_launcher"

    def test_in_flight_registered_under_host_agent_id(self):
        """After a real launch, _IN_FLIGHT contains the pid under HOST_AGENT_ID only."""
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(app_name="notepad", execution_id="exec-canon-1", confirmed=True)
        mock_proc = MagicMock()
        mock_proc.pid = 6666

        with patch("subprocess.Popen", return_value=mock_proc):
            execute_host_action(req)

        records = get_in_flight(HOST_AGENT_ID)
        assert any(r["pid"] == 6666 for r in records), (
            f"pid must be registered under HOST_AGENT_ID={HOST_AGENT_ID!r}"
        )
        # Verify no other key holds the pid
        assert get_in_flight("host-agent-test") == []
        assert get_in_flight("ag") == []
        assert get_in_flight("agent-1") == []

    def test_kill_switch_sees_pids_from_real_launches(self):
        """kill_switch(HOST_AGENT_ID) must see the pid of a process launched by this executor."""
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(app_name="notepad", execution_id="exec-kill-1", confirmed=True)
        mock_proc = MagicMock()
        mock_proc.pid = 9001

        with patch("subprocess.Popen", return_value=mock_proc):
            execute_host_action(req)

        with patch("os.kill") as mock_kill:
            result = kill_switch(HOST_AGENT_ID)

        # Phase 5D: reconcile_in_flight calls os.kill(pid, 0) to check liveness,
        # then abort_in_flight calls os.kill(pid, SIGTERM).  Use assert_any_call.
        mock_kill.assert_any_call(9001, signal.SIGTERM)
        assert len(result.abort_results) == 1
        assert result.abort_results[0].pid == 9001
        assert result.abort_results[0].execution_id == "exec-kill-1"

    def test_audit_intent_event_uses_host_agent_id(self):
        """Every HOST_INTENT event must carry HOST_AGENT_ID as agent_id."""
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(app_name="calc", execution_id="exec-audit-canon-1", confirmed=True)
        mock_proc = MagicMock()
        mock_proc.pid = 100

        with patch("subprocess.Popen", return_value=mock_proc):
            execute_host_action(req)

        for event in HOST_AUDIT_LOG.events(HostAuditEventType.HOST_INTENT):
            assert event.agent_id == HOST_AGENT_ID, (
                f"intent event agent_id must be {HOST_AGENT_ID!r}, got {event.agent_id!r}"
            )

    def test_audit_outcome_event_uses_host_agent_id(self):
        """Every HOST_OUTCOME event must carry HOST_AGENT_ID as agent_id."""
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(app_name="notepad", execution_id="exec-audit-canon-2", confirmed=True)
        mock_proc = MagicMock()
        mock_proc.pid = 200

        with patch("subprocess.Popen", return_value=mock_proc):
            execute_host_action(req)

        for event in HOST_AUDIT_LOG.events(HostAuditEventType.HOST_OUTCOME):
            assert event.agent_id == HOST_AGENT_ID, (
                f"outcome event agent_id must be {HOST_AGENT_ID!r}, got {event.agent_id!r}"
            )

    def test_kill_switch_quarantines_host_agent_id(self):
        """After kill_switch, HOST_AGENT_ID must be QUARANTINE — no new launches possible."""
        activate_agent(HOST_AGENT_ID)
        with patch("os.kill"):
            kill_switch(HOST_AGENT_ID)
        assert get_agent_status(HOST_AGENT_ID) == AgentStatus.QUARANTINE

    def test_multiple_launches_all_visible_to_kill_switch(self):
        """Two launches → kill_switch(HOST_AGENT_ID) sees both pids."""
        activate_agent(HOST_AGENT_ID)

        mock_proc_1 = MagicMock()
        mock_proc_1.pid = 1001
        mock_proc_2 = MagicMock()
        mock_proc_2.pid = 1002

        with patch("subprocess.Popen", side_effect=[mock_proc_1, mock_proc_2]):
            execute_host_action(HostActionRequest(
                app_name="notepad", execution_id="exec-m1", confirmed=True,
            ))
            execute_host_action(HostActionRequest(
                app_name="calc", execution_id="exec-m2", confirmed=True,
            ))

        with patch("os.kill") as mock_kill:
            result = kill_switch(HOST_AGENT_ID)

        # Phase 5D: reconcile_in_flight calls os.kill(pid, 0) for each PID,
        # then abort_in_flight calls os.kill(pid, SIGTERM). Count only SIGTERM calls.
        sigterm_calls = [c for c in mock_kill.call_args_list if c.args[1] == signal.SIGTERM]
        assert len(sigterm_calls) == 2
        pids = {r.pid for r in result.abort_results}
        assert pids == {1001, 1002}


# ===========================================================================
# K. close_pid
# ===========================================================================


def _make_close_pid_request(pid: int, execution_id: str = "exec-cp-1") -> HostActionRequest:
    """Build a confirmed close_pid request with HOST_AGENT_ID pre-activated."""
    activate_agent(HOST_AGENT_ID)
    return HostActionRequest(
        execution_id=execution_id,
        action="close_pid",
        confirmed=True,
        pid=pid,
    )


class TestClosePid:
    def test_close_pid_sigterms_registered_pid(self):
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 5500, "exec-kill-me")
        req = HostActionRequest(execution_id="exec-kill-me", action="close_pid", confirmed=True, pid=5500)
        with patch("os.kill") as mock_kill:
            result = execute_host_action(req)
        assert result.ok is True
        # reconcile calls os.kill(5500, 0) first; then close_pid calls os.kill(5500, SIGTERM)
        sigterm_calls = [c for c in mock_kill.call_args_list if c.args[1] == signal.SIGTERM]
        assert len(sigterm_calls) == 1
        assert sigterm_calls[0] == call(5500, signal.SIGTERM)

    def test_close_pid_deregisters_pid_from_in_flight(self):
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 4400, "exec-dereg")
        req = HostActionRequest(execution_id="exec-dereg", action="close_pid", confirmed=True, pid=4400)
        with patch("os.kill"):
            execute_host_action(req)
        assert not any(r["pid"] == 4400 for r in get_in_flight(HOST_AGENT_ID))

    def test_close_pid_rejects_unregistered_pid(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="exec-unowned", action="close_pid", confirmed=True, pid=9999)
        with patch("os.kill") as mock_kill:
            result = execute_host_action(req)
        assert result.ok is False
        assert "managed process" in (result.error or "")
        mock_kill.assert_not_called()

    def test_close_pid_rejects_none_pid(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="exec-none-pid", action="close_pid", confirmed=True, pid=None)
        with patch("os.kill") as mock_kill:
            result = execute_host_action(req)
        assert result.ok is False
        mock_kill.assert_not_called()

    def test_close_pid_requires_confirmed(self):
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 3300, "exec-unconfirmed")
        req = HostActionRequest(execution_id="exec-unconfirmed", action="close_pid", confirmed=False, pid=3300)
        with patch("os.kill") as mock_kill:
            result = execute_host_action(req)
        assert result.ok is False
        mock_kill.assert_not_called()

    def test_close_pid_aborts_on_audit_error(self):
        from assistant_os.agents.host_audit import HostAuditError
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 2200, "exec-audit-fail")
        req = HostActionRequest(execution_id="exec-audit-fail", action="close_pid", confirmed=True, pid=2200)
        with (
            patch("assistant_os.agents.host_agent.emit_action_intent",
                  side_effect=HostAuditError("disk full")),
            patch("os.kill") as mock_kill,
        ):
            result = execute_host_action(req)
        assert result.ok is False
        assert "intent audit failed" in (result.error or "")
        # reconcile may call os.kill(pid, 0) — only SIGTERM must be absent
        sigterm_calls = [c for c in mock_kill.call_args_list if c.args[1] == signal.SIGTERM]
        assert sigterm_calls == []

    def test_close_pid_result_echoes_pid(self):
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 1100, "exec-echo")
        req = HostActionRequest(execution_id="exec-echo", action="close_pid", confirmed=True, pid=1100)
        with patch("os.kill"):
            result = execute_host_action(req)
        assert result.pid == 1100
        assert result.action == "close_pid"
        assert result.execution_id == "exec-echo"


# ===========================================================================
# L. open_directory
# ===========================================================================


_ALLOWED_DIR = r"C:\Users\Jorge\Documents"
_BLOCKED_DIR = r"C:\Windows\System32"


class TestOpenDirectory:
    def _req(self, path: str, execution_id: str = "exec-od-1") -> HostActionRequest:
        activate_agent(HOST_AGENT_ID)
        return HostActionRequest(
            execution_id=execution_id,
            action="open_directory",
            confirmed=True,
            path=path,
        )

    def test_allowed_directory_opens_explorer(self):
        req = self._req(_ALLOWED_DIR)
        mock_proc = MagicMock()
        mock_proc.pid = 7700
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            result = execute_host_action(req)
        assert result.ok is True
        mock_popen.assert_called_once_with(
            [APP_REGISTRY["explorer"], _ALLOWED_DIR]
        )

    def test_allowed_subdirectory_is_permitted(self):
        subdir = r"C:\Users\Jorge\Documents\Projects"
        req = self._req(subdir)
        mock_proc = MagicMock()
        mock_proc.pid = 8800
        with patch("subprocess.Popen", return_value=mock_proc):
            result = execute_host_action(req)
        assert result.ok is True

    def test_blocked_directory_rejected(self):
        req = self._req(_BLOCKED_DIR)
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        assert "ALLOWED_DIRECTORIES" in (result.error or "")
        mock_popen.assert_not_called()

    def test_empty_path_rejected(self):
        req = self._req("")
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_path_traversal_rejected(self):
        req = self._req(r"C:\Users\Jorge\Documents\..\..\..\Windows\System32")
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_pid_registered_in_flight(self):
        req = self._req(_ALLOWED_DIR, execution_id="exec-od-flight")
        mock_proc = MagicMock()
        mock_proc.pid = 6600
        with patch("subprocess.Popen", return_value=mock_proc):
            result = execute_host_action(req)
        assert result.ok is True
        records = get_in_flight(HOST_AGENT_ID)
        assert any(r["pid"] == 6600 and r["execution_id"] == "exec-od-flight" for r in records)

    def test_requires_confirmed(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(
            execution_id="exec-od-nc", action="open_directory", confirmed=False, path=_ALLOWED_DIR
        )
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_aborts_on_audit_error(self):
        from assistant_os.agents.host_audit import HostAuditError
        req = self._req(_ALLOWED_DIR)
        with (
            patch("assistant_os.agents.host_agent.emit_action_intent",
                  side_effect=HostAuditError("io error")),
            patch("subprocess.Popen") as mock_popen,
        ):
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_popen_no_shell_true(self):
        req = self._req(_ALLOWED_DIR)
        mock_proc = MagicMock()
        mock_proc.pid = 5500
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            execute_host_action(req)
        _, kwargs = mock_popen.call_args
        assert kwargs.get("shell", False) is False


# ===========================================================================
# M. open_url
# ===========================================================================


_ALLOWED_URL = "https://github.com/test/repo"
_BLOCKED_URL = "https://evil.com/phish"


class TestOpenUrl:
    def _req(self, url: str, execution_id: str = "exec-url-1") -> HostActionRequest:
        activate_agent(HOST_AGENT_ID)
        return HostActionRequest(
            execution_id=execution_id,
            action="open_url",
            confirmed=True,
            url=url,
        )

    def test_allowed_url_opens_via_rundll32(self):
        req = self._req(_ALLOWED_URL)
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is True
        mock_popen.assert_called_once_with(
            ["rundll32.exe", "url.dll,FileProtocolHandler", _ALLOWED_URL]
        )

    def test_blocked_domain_rejected(self):
        req = self._req(_BLOCKED_URL)
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        assert "ALLOWED_URL_DOMAINS" in (result.error or "")
        mock_popen.assert_not_called()

    def test_empty_url_rejected(self):
        req = self._req("")
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_subdomain_of_allowed_domain_permitted(self):
        req = self._req("https://docs.github.com/en/actions")
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is True

    def test_requires_confirmed(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(
            execution_id="exec-url-nc", action="open_url", confirmed=False, url=_ALLOWED_URL
        )
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_no_pid_registered_for_url(self):
        """rundll32 is ephemeral; no pid should be registered in _IN_FLIGHT."""
        req = self._req(_ALLOWED_URL, execution_id="exec-url-pid")
        with patch("subprocess.Popen"):
            execute_host_action(req)
        assert get_in_flight(HOST_AGENT_ID) == []

    def test_aborts_on_audit_error(self):
        from assistant_os.agents.host_audit import HostAuditError
        req = self._req(_ALLOWED_URL)
        with (
            patch("assistant_os.agents.host_agent.emit_action_intent",
                  side_effect=HostAuditError("io error")),
            patch("subprocess.Popen") as mock_popen,
        ):
            result = execute_host_action(req)
        assert result.ok is False
        mock_popen.assert_not_called()

    def test_popen_no_shell_true(self):
        req = self._req(_ALLOWED_URL)
        with patch("subprocess.Popen") as mock_popen:
            execute_host_action(req)
        _, kwargs = mock_popen.call_args
        assert kwargs.get("shell", False) is False

    def test_result_echoes_execution_id(self):
        req = self._req(_ALLOWED_URL, execution_id="exec-url-echo")
        with patch("subprocess.Popen"):
            result = execute_host_action(req)
        assert result.execution_id == "exec-url-echo"
        assert result.action == "open_url"


# ===========================================================================
# N. Fase 2 — action audit events (close_pid, open_directory, open_url)
# ===========================================================================


class TestActionAudit:
    def test_close_pid_audit_intent_emitted_before_kill(self):
        call_order = []

        def record_intent(*a, **kw):
            call_order.append("intent")

        def record_kill(pid, sig):
            # Only track the real kill (SIGTERM), not the reconcile liveness probe (sig 0)
            if sig == signal.SIGTERM:
                call_order.append("kill")

        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 3000, "exec-ca-1")
        req = HostActionRequest(execution_id="exec-ca-1", action="close_pid", confirmed=True, pid=3000)

        with (
            patch("assistant_os.agents.host_agent.emit_action_intent", side_effect=record_intent),
            patch("os.kill", side_effect=record_kill),
            patch("assistant_os.agents.host_agent.emit_action_outcome"),
            patch("assistant_os.agents.host_agent.deregister_in_flight"),
        ):
            execute_host_action(req)

        assert call_order.index("intent") < call_order.index("kill")

    def test_close_pid_audit_outcome_emitted_after_kill(self):
        call_order = []

        def record_kill(pid, sig):
            call_order.append("kill")

        def record_outcome(*a, **kw):
            call_order.append("outcome")

        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 3001, "exec-ca-2")
        req = HostActionRequest(execution_id="exec-ca-2", action="close_pid", confirmed=True, pid=3001)

        with (
            patch("assistant_os.agents.host_agent.emit_action_intent"),
            patch("os.kill", side_effect=record_kill),
            patch("assistant_os.agents.host_agent.emit_action_outcome", side_effect=record_outcome),
            patch("assistant_os.agents.host_agent.deregister_in_flight"),
        ):
            execute_host_action(req)

        assert call_order.index("kill") < call_order.index("outcome")

    def test_open_directory_audit_events_emitted(self):
        from assistant_os.agents.host_audit import HostAuditEventType
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(
            execution_id="exec-dir-audit", action="open_directory",
            confirmed=True, path=_ALLOWED_DIR,
        )
        mock_proc = MagicMock()
        mock_proc.pid = 1001
        with patch("subprocess.Popen", return_value=mock_proc):
            execute_host_action(req)

        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_INTENT)
        assert any(e.action == "open_directory" and e.execution_id == "exec-dir-audit" for e in events)
        events_out = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_OUTCOME)
        assert any(e.action == "open_directory" and e.result == "opened" for e in events_out)

    def test_open_url_audit_events_emitted(self):
        from assistant_os.agents.host_audit import HostAuditEventType
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(
            execution_id="exec-url-audit", action="open_url",
            confirmed=True, url=_ALLOWED_URL,
        )
        with patch("subprocess.Popen"):
            execute_host_action(req)

        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_INTENT)
        assert any(e.action == "open_url" and e.execution_id == "exec-url-audit" for e in events)
        events_out = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_OUTCOME)
        assert any(e.action == "open_url" and e.result == "opened" for e in events_out)

    def test_close_pid_audit_events_emitted(self):
        from assistant_os.agents.host_audit import HostAuditEventType
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 9090, "exec-cp-audit")
        req = HostActionRequest(
            execution_id="exec-cp-audit", action="close_pid",
            confirmed=True, pid=9090,
        )
        with patch("os.kill"):
            execute_host_action(req)

        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_INTENT)
        assert any(e.action == "close_pid" and e.execution_id == "exec-cp-audit" for e in events)
        events_out = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_OUTCOME)
        assert any(e.action == "close_pid" and e.result == "terminated" for e in events_out)


# ===========================================================================
# O. Fase 2 — integration: open_app backward compat + kill_switch sees Fase 2 pids
# ===========================================================================


class TestPhase2Integration:
    def test_open_app_still_works_with_default_action(self):
        """HostActionRequest with no explicit action defaults to open_app."""
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(app_name="notepad", execution_id="exec-bc-1", confirmed=True)
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        with patch("subprocess.Popen", return_value=mock_proc):
            result = execute_host_action(req)
        assert result.ok is True
        assert result.action == "open_app"

    def test_kill_switch_sees_open_directory_pid(self):
        """PIDs from open_directory must be visible to kill_switch."""
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(
            execution_id="exec-od-ks", action="open_directory",
            confirmed=True, path=_ALLOWED_DIR,
        )
        mock_proc = MagicMock()
        mock_proc.pid = 8888
        with patch("subprocess.Popen", return_value=mock_proc):
            execute_host_action(req)

        with patch("os.kill") as mock_kill:
            result = kill_switch(HOST_AGENT_ID)

        pids = {r.pid for r in result.abort_results}
        assert 8888 in pids

    def test_unknown_action_returns_error(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="exec-unk", action="nuke_everything", confirmed=True)
        result = execute_host_action(req)
        assert result.ok is False
        assert "unknown action" in (result.error or "").lower()
        assert result.error_code == HostErrorCode.UNKNOWN_ACTION


# ===========================================================================
# P. validate_allowed_directory (Phase 2.5)
# ===========================================================================


class TestValidateAllowedDirectory:
    def test_exact_allowed_path_returns_true(self):
        ok, reason = validate_allowed_directory(r"C:\Users\Jorge\Documents")
        assert ok is True
        assert reason == ""

    def test_subdirectory_of_allowed_returns_true(self):
        ok, _ = validate_allowed_directory(r"C:\Users\Jorge\Documents\Projects\foo")
        assert ok is True

    def test_blocked_path_returns_false(self):
        ok, reason = validate_allowed_directory(r"C:\Windows\System32")
        assert ok is False
        assert reason != ""

    def test_empty_path_returns_false(self):
        ok, reason = validate_allowed_directory("")
        assert ok is False
        assert "empty" in reason.lower()

    def test_path_traversal_resolves_and_is_blocked(self):
        # "Documents/../.." → resolves to "C:\Users" — not in allowlist
        ok, _ = validate_allowed_directory(r"C:\Users\Jorge\Documents\..\..\..\Windows")
        assert ok is False

    def test_traversal_within_allowed_to_outside_is_blocked(self):
        ok, _ = validate_allowed_directory(r"C:\Users\Jorge\Documents" + r"\..\..")
        assert ok is False

    def test_case_insensitive(self):
        # Windows paths are case-insensitive — normcase handles this
        ok, _ = validate_allowed_directory(r"c:\users\jorge\documents")
        assert ok is True

    def test_reason_contains_path_on_failure(self):
        _, reason = validate_allowed_directory(r"C:\Windows\Temp")
        assert "ALLOWED_DIRECTORIES" in reason or r"C:\Windows\Temp" in reason

    def test_desktop_allowed(self):
        ok, _ = validate_allowed_directory(r"C:\Users\Jorge\Desktop")
        assert ok is True

    def test_downloads_allowed(self):
        ok, _ = validate_allowed_directory(r"C:\Users\Jorge\Downloads")
        assert ok is True

    def test_adjacent_prefix_not_confused(self):
        # "C:\Users\JorgeEvil" must NOT match "C:\Users\Jorge\*"
        ok, _ = validate_allowed_directory(r"C:\Users\JorgeEvil\Documents")
        assert ok is False


# ===========================================================================
# Q. validate_allowed_url (Phase 2.5)
# ===========================================================================


class TestValidateAllowedUrl:
    def test_valid_https_url_returns_true(self):
        ok, reason, code = validate_allowed_url("https://github.com/repo")
        assert ok is True
        assert reason == ""
        assert code is None

    def test_http_scheme_rejected(self):
        ok, reason, code = validate_allowed_url("http://github.com/repo")
        assert ok is False
        assert code == HostErrorCode.URL_SCHEME_NOT_ALLOWED
        assert "http" in reason

    def test_ftp_scheme_rejected(self):
        ok, _, code = validate_allowed_url("ftp://github.com/file.txt")
        assert ok is False
        assert code == HostErrorCode.URL_SCHEME_NOT_ALLOWED

    def test_javascript_scheme_rejected(self):
        ok, _, code = validate_allowed_url("javascript:alert(1)")
        assert ok is False
        assert code == HostErrorCode.URL_SCHEME_NOT_ALLOWED

    def test_file_scheme_rejected(self):
        ok, _, code = validate_allowed_url("file:///C:/Windows/System32/cmd.exe")
        assert ok is False
        assert code == HostErrorCode.URL_SCHEME_NOT_ALLOWED

    def test_unknown_domain_rejected(self):
        ok, _, code = validate_allowed_url("https://evil.com/phish")
        assert ok is False
        assert code == HostErrorCode.URL_DOMAIN_NOT_ALLOWED

    def test_subdomain_of_allowed_permitted(self):
        ok, _, _ = validate_allowed_url("https://docs.github.com/en/actions")
        assert ok is True

    def test_deep_subdomain_permitted(self):
        ok, _, _ = validate_allowed_url("https://api.docs.github.com/v3")
        assert ok is True

    def test_empty_url_returns_invalid(self):
        ok, _, code = validate_allowed_url("")
        assert ok is False
        assert code == HostErrorCode.URL_INVALID

    def test_allowed_schemes_constant_contains_only_https(self):
        assert "https" in ALLOWED_URL_SCHEMES
        assert "http" not in ALLOWED_URL_SCHEMES

    def test_domain_not_matching_allowed_by_prefix(self):
        # "github.com.evil.com" must NOT match "github.com"
        ok, _, code = validate_allowed_url("https://github.com.evil.com/")
        assert ok is False
        assert code == HostErrorCode.URL_DOMAIN_NOT_ALLOWED

    def test_url_with_no_hostname_returns_invalid(self):
        ok, _, code = validate_allowed_url("https:///path/only")
        assert ok is False
        assert code == HostErrorCode.URL_INVALID

    def test_stackoverflow_allowed(self):
        ok, _, _ = validate_allowed_url("https://stackoverflow.com/questions/123")
        assert ok is True

    def test_docs_python_org_allowed(self):
        ok, _, _ = validate_allowed_url("https://docs.python.org/3/library/os.html")
        assert ok is True


# ===========================================================================
# R. Error codes on every failure path (Phase 2.5)
# ===========================================================================


class TestErrorCodes:
    def test_confirmed_false_gives_confirmed_required(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(app_name="notepad", execution_id="e1", confirmed=False)
        result = execute_host_action(req)
        assert result.error_code == HostErrorCode.CONFIRMED_REQUIRED

    def test_not_active_gives_control_plane_blocked(self):
        req = HostActionRequest(app_name="notepad", execution_id="e1", confirmed=True)
        result = execute_host_action(req)
        assert result.error_code == HostErrorCode.CONTROL_PLANE_BLOCKED

    def test_invalid_app_name_gives_invalid_app_name(self):
        req = _active_request(app_name="evil")
        result = execute_host_action(req)
        assert result.error_code == HostErrorCode.INVALID_APP_NAME

    def test_none_pid_gives_invalid_pid(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="e1", action="close_pid", confirmed=True, pid=None)
        result = execute_host_action(req)
        assert result.error_code == HostErrorCode.INVALID_PID

    def test_unregistered_pid_gives_pid_not_owned(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="e1", action="close_pid", confirmed=True, pid=9999)
        with patch("os.kill"):
            result = execute_host_action(req)
        assert result.error_code == HostErrorCode.PID_NOT_OWNED

    def test_directory_not_allowed_gives_directory_not_allowed(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="e1", action="open_directory",
                                confirmed=True, path=r"C:\Windows\System32")
        result = execute_host_action(req)
        assert result.error_code == HostErrorCode.DIRECTORY_NOT_ALLOWED

    def test_http_url_gives_url_scheme_not_allowed(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="e1", action="open_url",
                                confirmed=True, url="http://github.com/repo")
        result = execute_host_action(req)
        assert result.error_code == HostErrorCode.URL_SCHEME_NOT_ALLOWED

    def test_evil_domain_gives_url_domain_not_allowed(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="e1", action="open_url",
                                confirmed=True, url="https://evil.com/phish")
        result = execute_host_action(req)
        assert result.error_code == HostErrorCode.URL_DOMAIN_NOT_ALLOWED

    def test_unknown_action_gives_unknown_action(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="e1", action="rm_rf", confirmed=True)
        result = execute_host_action(req)
        assert result.error_code == HostErrorCode.UNKNOWN_ACTION

    def test_successful_result_has_no_error_code(self):
        req = _active_request(app_name="notepad")
        mock_proc = MagicMock()
        mock_proc.pid = 42
        with patch("subprocess.Popen", return_value=mock_proc):
            result = execute_host_action(req)
        assert result.ok is True
        assert result.error_code is None


# ===========================================================================
# S. Rejection audit on gate failures (Phase 2.5)
# ===========================================================================


class TestRejectionAudit:
    def test_confirmed_false_emits_rejection_event(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(app_name="notepad", execution_id="exec-rej-1", confirmed=False)
        execute_host_action(req)
        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_REJECTION)
        assert len(events) == 1
        assert events[0].error_code == HostErrorCode.CONFIRMED_REQUIRED
        assert events[0].execution_id == "exec-rej-1"

    def test_not_active_emits_rejection_event(self):
        req = HostActionRequest(app_name="notepad", execution_id="exec-rej-2", confirmed=True)
        execute_host_action(req)
        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_REJECTION)
        assert len(events) == 1
        assert events[0].error_code == HostErrorCode.CONTROL_PLANE_BLOCKED

    def test_rejection_event_carries_host_agent_id(self):
        req = HostActionRequest(app_name="notepad", execution_id="exec-rej-3", confirmed=False)
        execute_host_action(req)
        for event in HOST_AUDIT_LOG.events(HostAuditEventType.HOST_REJECTION):
            assert event.agent_id == HOST_AGENT_ID

    def test_rejection_event_carries_action(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="exec-rej-4", action="open_url",
                                confirmed=False, url="https://github.com")
        execute_host_action(req)
        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_REJECTION)
        assert events[0].action == "open_url"

    def test_successful_action_emits_no_rejection_event(self):
        req = _active_request(app_name="notepad", execution_id="exec-ok-1")
        mock_proc = MagicMock()
        mock_proc.pid = 99
        with patch("subprocess.Popen", return_value=mock_proc):
            result = execute_host_action(req)
        assert result.ok is True
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_REJECTION) == 0

    def test_unknown_action_emits_rejection_event(self):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(execution_id="exec-unk-2", action="delete_all", confirmed=True)
        execute_host_action(req)
        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_REJECTION)
        assert len(events) == 1
        assert events[0].error_code == HostErrorCode.UNKNOWN_ACTION


# ===========================================================================
# T. Rate limits (Phase 2.5)
# ===========================================================================


class TestRateLimits:
    """Rate limits: max 10 per 60s for open_app, open_directory, open_url.
    close_pid has no rate limit.
    """

    def _flood_action(self, action: str, count: int, base_exec_id: str = "exec-flood") -> list:
        """Issue `count` confirmed requests for `action` and return results."""
        results = []
        activate_agent(HOST_AGENT_ID)
        for i in range(count):
            if action == "open_app":
                req = HostActionRequest(
                    execution_id=f"{base_exec_id}-{i}", action=action,
                    confirmed=True, app_name="notepad",
                )
            elif action == "open_directory":
                req = HostActionRequest(
                    execution_id=f"{base_exec_id}-{i}", action=action,
                    confirmed=True, path=r"C:\Users\Jorge\Documents",
                )
            else:  # open_url
                req = HostActionRequest(
                    execution_id=f"{base_exec_id}-{i}", action=action,
                    confirmed=True, url="https://github.com/x",
                )
            mock_proc = MagicMock()
            mock_proc.pid = 10000 + i
            with patch("subprocess.Popen", return_value=mock_proc):
                results.append(execute_host_action(req))
        return results

    def test_open_app_within_limit_all_succeed(self):
        results = self._flood_action("open_app", count=5)
        assert all(r.ok for r in results)

    def test_open_app_exceeds_limit_rejected(self):
        results = self._flood_action("open_app", count=11)
        # First 10 succeed; 11th is rejected
        assert all(r.ok for r in results[:10])
        assert results[10].ok is False
        assert results[10].error_code == HostErrorCode.RATE_LIMIT_EXCEEDED

    def test_open_directory_exceeds_limit_rejected(self):
        results = self._flood_action("open_directory", count=11)
        assert results[10].ok is False
        assert results[10].error_code == HostErrorCode.RATE_LIMIT_EXCEEDED

    def test_open_url_exceeds_limit_rejected(self):
        results = self._flood_action("open_url", count=11)
        assert results[10].ok is False
        assert results[10].error_code == HostErrorCode.RATE_LIMIT_EXCEEDED

    def test_rate_limit_exceeded_emits_rejection_event(self):
        self._flood_action("open_app", count=11)
        rejection_events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_REJECTION)
        rate_rejections = [e for e in rejection_events
                           if e.error_code == HostErrorCode.RATE_LIMIT_EXCEEDED]
        assert len(rate_rejections) >= 1

    def test_close_pid_has_no_rate_limit(self):
        """close_pid is exempt from rate limiting — must never be blocked by it."""
        activate_agent(HOST_AGENT_ID)
        # Simulate 20 close_pid calls — none should be rate-limited
        for i in range(20):
            pid = 20000 + i
            register_in_flight(HOST_AGENT_ID, pid, f"exec-rl-cp-{i}")
            req = HostActionRequest(
                execution_id=f"exec-rl-cp-{i}", action="close_pid",
                confirmed=True, pid=pid,
            )
            with patch("os.kill"):
                result = execute_host_action(req)
            assert result.error_code != HostErrorCode.RATE_LIMIT_EXCEEDED, (
                f"close_pid was rate-limited on call {i}"
            )

    def test_rate_limit_reset_between_tests(self):
        """_reset_host_agent_state_for_tests clears counters — autouse fixture ensures isolation."""
        # If reset works, we can issue 10 calls without hitting the limit
        results = self._flood_action("open_app", count=10)
        assert all(r.ok for r in results)


# ===========================================================================
# U. close_pid with stale PID / reconcile (Phase 2.5)
# ===========================================================================


class TestClosePidReconcile:
    def test_close_pid_on_naturally_exited_process_returns_already_exited(self):
        """If a process dies between register and close_pid, reconcile removes it,
        and the ownership check correctly returns PID_NOT_OWNED (or PROCESS_ALREADY_EXITED
        if it dies after the reconcile window but before os.kill)."""
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 7777, "exec-stale-1")

        # Simulate: process is dead when reconcile runs (os.kill signal 0 → OSError)
        # and also dead when the real kill runs
        req = HostActionRequest(
            execution_id="exec-stale-1", action="close_pid",
            confirmed=True, pid=7777,
        )
        with patch("os.kill", side_effect=OSError("no such process")):
            result = execute_host_action(req)

        # After reconcile, 7777 is removed → PID_NOT_OWNED
        assert result.ok is False
        assert result.error_code in (
            HostErrorCode.PID_NOT_OWNED,
            HostErrorCode.PROCESS_ALREADY_EXITED,
        )

    def test_close_pid_process_dies_in_kill_window_returns_already_exited(self):
        """Process alive during reconcile, dead when os.kill fires → PROCESS_ALREADY_EXITED."""
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 8888, "exec-race-1")

        call_count = {"n": 0}

        def fake_kill(pid, sig):
            call_count["n"] += 1
            if sig == 0:
                return  # reconcile check: alive
            raise OSError("process gone")  # actual SIGTERM: dead

        req = HostActionRequest(
            execution_id="exec-race-1", action="close_pid",
            confirmed=True, pid=8888,
        )
        with patch("os.kill", side_effect=fake_kill):
            result = execute_host_action(req)

        assert result.ok is False
        assert result.error_code == HostErrorCode.PROCESS_ALREADY_EXITED

    def test_reconcile_called_before_ownership_check(self):
        """Verify reconcile runs before the ownership check by confirming a
        dead registered PID is rejected without calling os.kill(pid, SIGTERM)."""
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 5555, "exec-reconcile-check")

        sigterm_called = []

        def fake_kill(pid, sig):
            if sig == signal.SIGTERM:
                sigterm_called.append(pid)
            else:
                raise OSError("dead")  # signal 0 → process dead → reconcile removes it

        req = HostActionRequest(
            execution_id="exec-reconcile-check", action="close_pid",
            confirmed=True, pid=5555,
        )
        with patch("os.kill", side_effect=fake_kill):
            result = execute_host_action(req)

        assert result.ok is False
        assert 5555 not in sigterm_called  # never reached SIGTERM because reconcile cleaned it


# ===========================================================================
# V. validate_allowed_write_path / validate_allowed_write_directory (Phase 5A)
# ===========================================================================

_SANDBOX = WRITE_SANDBOX_DIRECTORIES[0]   # e.g. C:\Users\Jorge\Documents\assistant_sandbox
_SANDBOX_FILE   = _SANDBOX + r"\notes.txt"
_SANDBOX_SUBDIR = _SANDBOX + r"\subdir"
_OUTSIDE_FILE   = r"C:\Users\Jorge\Documents\outside.txt"


class TestValidateAllowedWritePath:
    def test_file_inside_sandbox_returns_true(self):
        ok, reason = validate_allowed_write_path(_SANDBOX_FILE)
        assert ok is True
        assert reason == ""

    def test_sandbox_root_itself_is_rejected(self):
        """The sandbox root is a directory; writing a file at that path is rejected."""
        ok, reason = validate_allowed_write_path(_SANDBOX)
        assert ok is False
        assert "sandbox root" in reason.lower() or "not a file" in reason.lower()

    def test_path_outside_sandbox_returns_false(self):
        ok, reason = validate_allowed_write_path(_OUTSIDE_FILE)
        assert ok is False
        assert "WRITE_SANDBOX_DIRECTORIES" in reason or _OUTSIDE_FILE in reason

    def test_traversal_to_outside_is_blocked(self):
        traversal = _SANDBOX + r"\..\..\..\Windows\evil.txt"
        ok, _ = validate_allowed_write_path(traversal)
        assert ok is False

    def test_traversal_staying_inside_sandbox_is_allowed(self):
        # sandbox\sub\..\file.txt normalises to sandbox\file.txt → still inside
        path = _SANDBOX + r"\sub\..\file.txt"
        ok, _ = validate_allowed_write_path(path)
        assert ok is True

    def test_empty_path_returns_false(self):
        ok, reason = validate_allowed_write_path("")
        assert ok is False
        assert "empty" in reason.lower()

    def test_case_insensitive(self):
        ok, _ = validate_allowed_write_path(_SANDBOX_FILE.lower())
        assert ok is True

    def test_adjacent_prefix_not_confused(self):
        evil_path = _SANDBOX + "_evil\\file.txt"
        ok, _ = validate_allowed_write_path(evil_path)
        assert ok is False

    def test_documents_root_is_not_write_sandbox(self):
        ok, _ = validate_allowed_write_path(r"C:\Users\Jorge\Documents\file.txt")
        assert ok is False


class TestValidateAllowedWriteDirectory:
    def test_sandbox_root_is_allowed(self):
        ok, reason = validate_allowed_write_directory(_SANDBOX)
        assert ok is True
        assert reason == ""

    def test_subdir_inside_sandbox_is_allowed(self):
        ok, _ = validate_allowed_write_directory(_SANDBOX_SUBDIR)
        assert ok is True

    def test_path_outside_sandbox_returns_false(self):
        ok, _ = validate_allowed_write_directory(r"C:\Users\Jorge\Documents")
        assert ok is False

    def test_traversal_to_outside_is_blocked(self):
        traversal = _SANDBOX + r"\..\.."
        ok, _ = validate_allowed_write_directory(traversal)
        assert ok is False

    def test_empty_path_returns_false(self):
        ok, reason = validate_allowed_write_directory("")
        assert ok is False
        assert "empty" in reason.lower()

    def test_case_insensitive(self):
        ok, _ = validate_allowed_write_directory(_SANDBOX.lower())
        assert ok is True


# ===========================================================================
# W. write_text_file (Phase 5A)
# ===========================================================================


def _write_req(
    path: str = _SANDBOX_FILE,
    content: str = "hello world",
    execution_id: str = "exec-w-1",
    confirmed: bool = True,
) -> HostActionRequest:
    activate_agent(HOST_AGENT_ID)
    return HostActionRequest(
        execution_id=execution_id,
        action="write_text_file",
        confirmed=confirmed,
        path=path,
        content=content,
    )


class TestWriteTextFile:
    # --- Happy paths ---

    def test_write_creates_file_in_sandbox(self):
        req = _write_req()
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()) as mock_open,
        ):
            result = execute_host_action(req)
        assert result.ok is True
        assert result.action == "write_text_file"
        assert result.write_mode == "create"
        assert result.bytes_written == len("hello world".encode("utf-8"))

    def test_write_overwrite_is_permitted(self):
        req = _write_req(content="updated content")
        mock_ntf_ctx = MagicMock()
        mock_ntf_ctx.__enter__.return_value.name = "/tmp/test.tmp"
        mock_ntf_ctx.__exit__ = MagicMock(return_value=False)
        with (
            patch("os.path.isfile", return_value=True),
            patch("tempfile.NamedTemporaryFile", return_value=mock_ntf_ctx),
            patch("os.replace"),
        ):
            result = execute_host_action(req)
        assert result.ok is True
        assert result.write_mode == "overwrite"
        assert result.atomic_replace_used is True

    def test_bytes_written_reported_correctly(self):
        content = "abc"
        req = _write_req(content=content)
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            result = execute_host_action(req)
        assert result.bytes_written == len(content.encode("utf-8"))

    # --- Sandbox validation ---

    def test_path_outside_sandbox_rejected(self):
        req = _write_req(path=_OUTSIDE_FILE)
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_NOT_ALLOWED
        mock_open.assert_not_called()

    def test_traversal_path_rejected(self):
        traversal = _SANDBOX + r"\..\..\..\Windows\evil.txt"
        req = _write_req(path=traversal)
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_NOT_ALLOWED
        mock_open.assert_not_called()

    # --- Extension validation ---

    def test_disallowed_extension_rejected(self):
        req = _write_req(path=_SANDBOX + r"\run.bat")
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.EXTENSION_NOT_ALLOWED
        mock_open.assert_not_called()

    def test_exe_extension_rejected(self):
        req = _write_req(path=_SANDBOX + r"\evil.exe")
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.EXTENSION_NOT_ALLOWED

    def test_allowed_extensions_all_pass_validation(self):
        for ext in (".txt", ".md", ".json"):
            req = _write_req(path=_SANDBOX + rf"\file{ext}")
            with (
                patch("os.path.isfile", return_value=False),
                patch("builtins.open", unittest.mock.mock_open()),
            ):
                result = execute_host_action(req)
            assert result.ok is True, f"expected ok for extension {ext}"

    # --- Size validation ---

    def test_oversized_content_rejected(self):
        big = "x" * (MAX_WRITE_SIZE_BYTES + 1)
        req = _write_req(content=big)
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_TOO_LARGE
        mock_open.assert_not_called()

    def test_exactly_max_size_is_accepted(self):
        content = "x" * MAX_WRITE_SIZE_BYTES  # ASCII: 1 byte per char
        req = _write_req(content=content)
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            result = execute_host_action(req)
        assert result.ok is True

    # --- Audit ---

    def test_intent_audit_emitted_before_open(self):
        call_order = []

        def record_intent(*a, **kw):
            call_order.append("intent")

        original_open = unittest.mock.mock_open()

        class TrackingOpen:
            def __call__(self, *a, **kw):
                call_order.append("open")
                return original_open(*a, **kw)

        req = _write_req(execution_id="exec-w-audit-1")
        with (
            patch("os.path.isfile", return_value=False),
            patch("assistant_os.agents.host_agent.emit_action_intent", side_effect=record_intent),
            patch("builtins.open", TrackingOpen()),
            patch("assistant_os.agents.host_agent.emit_action_outcome"),
        ):
            execute_host_action(req)

        assert call_order.index("intent") < call_order.index("open")

    def test_outcome_audit_emitted_after_open(self):
        call_order = []
        original_open = unittest.mock.mock_open()

        class TrackingOpen:
            def __call__(self, *a, **kw):
                call_order.append("open")
                return original_open(*a, **kw)

        def record_outcome(*a, **kw):
            call_order.append("outcome")

        req = _write_req(execution_id="exec-w-audit-2")
        with (
            patch("os.path.isfile", return_value=False),
            patch("assistant_os.agents.host_agent.emit_action_intent"),
            patch("builtins.open", TrackingOpen()),
            patch("assistant_os.agents.host_agent.emit_action_outcome", side_effect=record_outcome),
        ):
            execute_host_action(req)

        assert call_order.index("open") < call_order.index("outcome")

    def test_audit_outcome_result_contains_mode_and_bytes(self):
        captured = []

        def capture_outcome(*a, **kw):
            captured.append(kw)

        req = _write_req(content="hi", execution_id="exec-w-audit-3")
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
            patch("assistant_os.agents.host_agent.emit_action_outcome", side_effect=capture_outcome),
        ):
            execute_host_action(req)

        assert captured, "emit_action_outcome was not called"
        result_str = captured[0]["result"]
        assert "create" in result_str
        assert "b" in result_str  # bytes suffix

    def test_content_not_stored_in_audit_log(self):
        """Full content must never appear in the audit log."""
        sensitive = "my secret content 12345"
        req = _write_req(content=sensitive, execution_id="exec-w-audit-secret")
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            execute_host_action(req)

        # Serialise every audit event to dict and verify content not present
        all_dicts = HOST_AUDIT_LOG.all_dicts()
        for d in all_dicts:
            assert sensitive not in str(d), f"sensitive content leaked into audit: {d}"

    # --- Gate enforcement ---

    def test_confirmed_false_rejects(self):
        req = _write_req(confirmed=False)
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.CONFIRMED_REQUIRED
        mock_open.assert_not_called()

    def test_control_plane_blocked_rejects(self):
        from assistant_os.core.control_plane import quarantine_agent
        activate_agent(HOST_AGENT_ID)
        quarantine_agent(HOST_AGENT_ID)
        req = HostActionRequest(
            execution_id="exec-w-cp", action="write_text_file",
            confirmed=True, path=_SANDBOX_FILE, content="x",
        )
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.CONTROL_PLANE_BLOCKED
        mock_open.assert_not_called()

    def test_audit_failure_aborts_write(self):
        from assistant_os.agents.host_audit import HostAuditError
        req = _write_req()
        with (
            patch("os.path.isfile", return_value=False),
            patch("assistant_os.agents.host_agent.emit_action_intent",
                  side_effect=HostAuditError("fail")),
            patch("builtins.open") as mock_open,
        ):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.AUDIT_FAILURE
        mock_open.assert_not_called()

    def test_oserror_on_write_returns_write_not_allowed(self):
        req = _write_req()
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", side_effect=OSError("permission denied")),
        ):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.WRITE_NOT_ALLOWED


# ===========================================================================
# X. append_text_file (Phase 5A)
# ===========================================================================


def _append_req(
    path: str = _SANDBOX_FILE,
    content: str = "\nappended line",
    execution_id: str = "exec-a-1",
    confirmed: bool = True,
) -> HostActionRequest:
    activate_agent(HOST_AGENT_ID)
    return HostActionRequest(
        execution_id=execution_id,
        action="append_text_file",
        confirmed=confirmed,
        path=path,
        content=content,
    )


class TestAppendTextFile:
    def test_append_to_existing_file_succeeds(self):
        req = _append_req()
        with (
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            result = execute_host_action(req)
        assert result.ok is True
        assert result.action == "append_text_file"
        assert result.write_mode == "append"

    def test_bytes_written_reported_for_append(self):
        content = "extra"
        req = _append_req(content=content)
        with (
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            result = execute_host_action(req)
        assert result.bytes_written == len(content.encode("utf-8"))

    def test_file_not_found_returns_file_not_found(self):
        req = _append_req()
        with patch("os.path.isfile", return_value=False):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_NOT_FOUND

    def test_path_outside_sandbox_rejected(self):
        req = _append_req(path=_OUTSIDE_FILE)
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_NOT_ALLOWED
        mock_open.assert_not_called()

    def test_disallowed_extension_rejected(self):
        req = _append_req(path=_SANDBOX + r"\script.ps1")
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.EXTENSION_NOT_ALLOWED
        mock_open.assert_not_called()

    def test_oversized_content_rejected(self):
        big = "y" * (MAX_WRITE_SIZE_BYTES + 1)
        req = _append_req(content=big)
        with (
            patch("os.path.isfile", return_value=True),
            patch("builtins.open") as mock_open,
        ):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_TOO_LARGE
        mock_open.assert_not_called()

    def test_traversal_path_rejected(self):
        traversal = _SANDBOX + r"\..\sensitive.txt"
        req = _append_req(path=traversal)
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_NOT_ALLOWED
        mock_open.assert_not_called()

    def test_intent_audit_before_open(self):
        call_order = []

        def record_intent(*a, **kw):
            call_order.append("intent")

        original_open = unittest.mock.mock_open()

        class TrackingOpen:
            def __call__(self, *a, **kw):
                call_order.append("open")
                return original_open(*a, **kw)

        req = _append_req(execution_id="exec-a-audit-1")
        with (
            patch("os.path.isfile", return_value=True),
            patch("assistant_os.agents.host_agent.emit_action_intent", side_effect=record_intent),
            patch("builtins.open", TrackingOpen()),
            patch("assistant_os.agents.host_agent.emit_action_outcome"),
        ):
            execute_host_action(req)

        assert call_order.index("intent") < call_order.index("open")

    def test_outcome_audit_after_open(self):
        call_order = []
        original_open = unittest.mock.mock_open()

        class TrackingOpen:
            def __call__(self, *a, **kw):
                call_order.append("open")
                return original_open(*a, **kw)

        def record_outcome(*a, **kw):
            call_order.append("outcome")

        req = _append_req(execution_id="exec-a-audit-2")
        with (
            patch("os.path.isfile", return_value=True),
            patch("assistant_os.agents.host_agent.emit_action_intent"),
            patch("builtins.open", TrackingOpen()),
            patch("assistant_os.agents.host_agent.emit_action_outcome", side_effect=record_outcome),
        ):
            execute_host_action(req)

        assert call_order.index("open") < call_order.index("outcome")

    def test_confirmed_false_rejects(self):
        req = _append_req(confirmed=False)
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.CONFIRMED_REQUIRED
        mock_open.assert_not_called()

    def test_audit_failure_aborts_append(self):
        from assistant_os.agents.host_audit import HostAuditError
        req = _append_req()
        with (
            patch("os.path.isfile", return_value=True),
            patch("assistant_os.agents.host_agent.emit_action_intent",
                  side_effect=HostAuditError("fail")),
            patch("builtins.open") as mock_open,
        ):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.AUDIT_FAILURE
        mock_open.assert_not_called()

    def test_content_not_in_audit_log(self):
        sensitive = "secret append data"
        req = _append_req(content=sensitive, execution_id="exec-a-secret")
        with (
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            execute_host_action(req)

        all_dicts = HOST_AUDIT_LOG.all_dicts()
        for d in all_dicts:
            assert sensitive not in str(d), f"sensitive content leaked: {d}"


# ===========================================================================
# Y. create_directory (Phase 5A)
# ===========================================================================


def _mkdir_req(
    path: str = _SANDBOX_SUBDIR,
    execution_id: str = "exec-mkdir-1",
    confirmed: bool = True,
) -> HostActionRequest:
    activate_agent(HOST_AGENT_ID)
    return HostActionRequest(
        execution_id=execution_id,
        action="create_directory",
        confirmed=confirmed,
        path=path,
    )


class TestCreateDirectory:
    def test_new_dir_inside_sandbox_created(self):
        req = _mkdir_req()
        with (
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=False),
            patch("os.mkdir") as mock_mkdir,
        ):
            result = execute_host_action(req)
        assert result.ok is True
        assert result.action == "create_directory"
        mock_mkdir.assert_called_once()

    def test_directory_already_exists_returns_error(self):
        req = _mkdir_req()
        with (
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=True),
            patch("os.mkdir") as mock_mkdir,
        ):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.DIRECTORY_ALREADY_EXISTS
        mock_mkdir.assert_not_called()

    def test_path_conflict_with_existing_file(self):
        req = _mkdir_req()
        with (
            patch("os.path.isfile", return_value=True),
            patch("os.path.isdir", return_value=False),
            patch("os.mkdir") as mock_mkdir,
        ):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.PATH_CONFLICT
        mock_mkdir.assert_not_called()

    def test_path_outside_sandbox_rejected(self):
        req = _mkdir_req(path=r"C:\Users\Jorge\Documents\newdir")
        with patch("os.mkdir") as mock_mkdir:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.DIRECTORY_NOT_ALLOWED
        mock_mkdir.assert_not_called()

    def test_traversal_to_outside_rejected(self):
        traversal = _SANDBOX + r"\..\..\evil_dir"
        req = _mkdir_req(path=traversal)
        with patch("os.mkdir") as mock_mkdir:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.DIRECTORY_NOT_ALLOWED
        mock_mkdir.assert_not_called()

    def test_oserror_returns_write_not_allowed(self):
        req = _mkdir_req()
        with (
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=False),
            patch("os.mkdir", side_effect=OSError("no parent")),
        ):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.WRITE_NOT_ALLOWED

    def test_intent_audit_before_mkdir(self):
        call_order = []

        def record_intent(*a, **kw):
            call_order.append("intent")

        def record_mkdir(path):
            call_order.append("mkdir")

        req = _mkdir_req(execution_id="exec-mkdir-audit")
        with (
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=False),
            patch("assistant_os.agents.host_agent.emit_action_intent", side_effect=record_intent),
            patch("os.mkdir", side_effect=record_mkdir),
            patch("assistant_os.agents.host_agent.emit_action_outcome"),
        ):
            execute_host_action(req)

        assert call_order.index("intent") < call_order.index("mkdir")

    def test_outcome_audit_after_mkdir(self):
        call_order = []

        def record_mkdir(path):
            call_order.append("mkdir")

        def record_outcome(*a, **kw):
            call_order.append("outcome")

        req = _mkdir_req(execution_id="exec-mkdir-audit-2")
        with (
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=False),
            patch("assistant_os.agents.host_agent.emit_action_intent"),
            patch("os.mkdir", side_effect=record_mkdir),
            patch("assistant_os.agents.host_agent.emit_action_outcome", side_effect=record_outcome),
        ):
            execute_host_action(req)

        assert call_order.index("mkdir") < call_order.index("outcome")

    def test_confirmed_false_rejects(self):
        req = _mkdir_req(confirmed=False)
        with patch("os.mkdir") as mock_mkdir:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.CONFIRMED_REQUIRED
        mock_mkdir.assert_not_called()

    def test_control_plane_blocked_rejects(self):
        from assistant_os.core.control_plane import quarantine_agent
        activate_agent(HOST_AGENT_ID)
        quarantine_agent(HOST_AGENT_ID)
        req = HostActionRequest(
            execution_id="exec-mkdir-cp", action="create_directory",
            confirmed=True, path=_SANDBOX_SUBDIR,
        )
        with patch("os.mkdir") as mock_mkdir:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.CONTROL_PLANE_BLOCKED
        mock_mkdir.assert_not_called()

    def test_audit_failure_aborts_mkdir(self):
        from assistant_os.agents.host_audit import HostAuditError
        req = _mkdir_req()
        with (
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=False),
            patch("assistant_os.agents.host_agent.emit_action_intent",
                  side_effect=HostAuditError("fail")),
            patch("os.mkdir") as mock_mkdir,
        ):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.AUDIT_FAILURE
        mock_mkdir.assert_not_called()

    def test_single_level_only_no_makedirs(self):
        """Verify os.mkdir is called, not os.makedirs — enforcing single-level creation."""
        req = _mkdir_req()
        with (
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=False),
            patch("os.mkdir") as mock_mkdir,
            patch("os.makedirs") as mock_makedirs,
        ):
            execute_host_action(req)
        mock_mkdir.assert_called_once()
        mock_makedirs.assert_not_called()


# ===========================================================================
# Z. Phase 5A — general invariants
# ===========================================================================


class TestPhase5AGeneralInvariants:
    def test_write_does_not_break_read_text_file(self):
        """write_text_file must not affect read_text_file's validation."""
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(
            execution_id="exec-z-read", action="read_text_file",
            confirmed=True, path=r"C:\Users\Jorge\Documents\file.txt",
        )
        with (
            patch("os.path.isfile", return_value=True),
            patch("os.path.getsize", return_value=10),
            patch("builtins.open", unittest.mock.mock_open(read_data="data")),
        ):
            result = execute_host_action(req)
        assert result.ok is True  # read_text_file uses ALLOWED_DIRECTORIES, still works

    def test_write_outside_sandbox_but_inside_read_allowlist_is_rejected(self):
        """ALLOWED_DIRECTORIES ≠ WRITE_SANDBOX_DIRECTORIES.  A file allowed for
        reading must not be writable unless it is also in the write sandbox."""
        req = _write_req(path=r"C:\Users\Jorge\Documents\notes.txt")
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_NOT_ALLOWED
        mock_open.assert_not_called()

    def test_write_sandbox_is_distinct_from_read_allowlist(self):
        """Confirm the constants are separate objects with different contents."""
        assert WRITE_SANDBOX_DIRECTORIES is not ALLOWED_DIRECTORIES
        sandbox_set = set(p.lower() for p in WRITE_SANDBOX_DIRECTORIES)
        read_set = set(p.lower() for p in ALLOWED_DIRECTORIES)
        # They may overlap but the sandbox should be a strict subset or differ
        # The key invariant: sandbox ≠ full read allowlist (otherwise separation is meaningless)
        assert sandbox_set != read_set

    def test_allowed_write_extensions_are_subset_of_safe_formats(self):
        """No executable or script extension must be in ALLOWED_WRITE_EXTENSIONS."""
        dangerous = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".sh", ".py", ".js"}
        for ext in dangerous:
            assert ext not in ALLOWED_WRITE_EXTENSIONS, f"{ext} must not be writable"

    def test_error_codes_exist_for_all_write_actions(self):
        """Smoke-check that the Phase 5A error codes are defined."""
        assert HostErrorCode.WRITE_NOT_ALLOWED.value == "write_not_allowed"
        assert HostErrorCode.DIRECTORY_ALREADY_EXISTS.value == "directory_already_exists"
        assert HostErrorCode.PATH_CONFLICT.value == "path_conflict"

# ===========================================================================
# Phase 5C — Sandbox hardening, atomic writes, lifecycle enrichment
# ===========================================================================

_SANDBOX5C = WRITE_SANDBOX_DIRECTORIES[0]          # e.g. C:\...\assistant_sandbox
_SANDBOX5C_FILE = _SANDBOX5C + r"\notes.txt"
_SANDBOX5C_FILE_MD = _SANDBOX5C + r"\notes.md"
_SANDBOX5C_SUBDIR = _SANDBOX5C + r"\subdir"


# ---------------------------------------------------------------------------
# TestRejectUnsafePathComponents
# ---------------------------------------------------------------------------

class TestRejectUnsafePathComponents:
    """Unit tests for _reject_unsafe_path_components (Phase 5C helper)."""

    def test_clean_path_passes(self):
        ok, _ = _reject_unsafe_path_components(r"C:\Users\Jorge\Documents\assistant_sandbox\notes.txt")
        assert ok is True

    def test_trailing_dot_on_filename_rejected(self):
        ok, reason = _reject_unsafe_path_components(r"C:\sandbox\file.txt.")
        assert ok is False
        assert "trailing dot or space" in reason

    def test_trailing_space_on_filename_rejected(self):
        # Space must be TRAILING on the whole component.
        # "file.txt " (space after extension) → Windows strips it → audit mismatch.
        # "file .txt" (space before dot) is a valid name and is NOT rejected.
        ok, reason = _reject_unsafe_path_components("C:\\sandbox\\file.txt ")
        assert ok is False
        assert "trailing dot or space" in reason

    def test_trailing_dot_on_directory_component_rejected(self):
        ok, reason = _reject_unsafe_path_components(r"C:\sandbox\subdir.\file.txt")
        assert ok is False
        assert "trailing dot or space" in reason

    def test_reserved_nul_rejected(self):
        ok, reason = _reject_unsafe_path_components(r"C:\sandbox\NUL.txt")
        assert ok is False
        assert "reserved Windows device name" in reason

    def test_reserved_nul_lowercase_rejected(self):
        ok, reason = _reject_unsafe_path_components(r"C:\sandbox\nul.txt")
        assert ok is False
        assert "reserved Windows device name" in reason

    def test_reserved_con_rejected(self):
        ok, reason = _reject_unsafe_path_components(r"C:\sandbox\CON.json")
        assert ok is False

    def test_reserved_com1_rejected(self):
        ok, reason = _reject_unsafe_path_components(r"C:\sandbox\COM1.txt")
        assert ok is False
        assert "reserved Windows device name" in reason

    def test_reserved_lpt1_rejected(self):
        ok, reason = _reject_unsafe_path_components(r"C:\sandbox\LPT1.md")
        assert ok is False

    def test_reserved_prn_rejected(self):
        ok, reason = _reject_unsafe_path_components(r"C:\sandbox\PRN")
        assert ok is False

    def test_reserved_stem_case_insensitive(self):
        """com9 (lowercase) must be caught."""
        ok, reason = _reject_unsafe_path_components(r"C:\sandbox\com9.txt")
        assert ok is False

    def test_non_reserved_name_passes(self):
        ok, _ = _reject_unsafe_path_components(r"C:\sandbox\report.json")
        assert ok is True

    def test_all_reserved_stems_covered(self):
        """Smoke: every name in the constant is actually checked."""
        for stem in _WINDOWS_RESERVED_STEMS:
            path = rf"C:\sandbox\{stem}.txt"
            ok, _ = _reject_unsafe_path_components(path)
            assert ok is False, f"{stem!r} should be rejected"

    def test_drive_root_component_not_flagged(self):
        """C:\\ itself must not be treated as a reserved name."""
        ok, _ = _reject_unsafe_path_components(r"C:\sandbox\notes.txt")
        assert ok is True


# ---------------------------------------------------------------------------
# TestSandboxHardeningPhase5C
# ---------------------------------------------------------------------------

class TestSandboxHardeningPhase5C:
    """Integration: unsafe path components rejected via validate_allowed_write_path."""

    def test_trailing_dot_rejected_by_write_path_validator(self):
        path = _SANDBOX5C + r"\file.txt."
        ok, reason = validate_allowed_write_path(path)
        assert ok is False
        assert "trailing dot or space" in reason

    def test_trailing_space_rejected_by_write_path_validator(self):
        # Trailing space on the whole component (after extension) is dangerous.
        path = _SANDBOX5C + "\\file.txt "
        ok, reason = validate_allowed_write_path(path)
        assert ok is False
        assert "trailing dot or space" in reason

    def test_reserved_nul_rejected_by_write_path_validator(self):
        path = _SANDBOX5C + r"\NUL.txt"
        ok, reason = validate_allowed_write_path(path)
        assert ok is False
        assert "reserved Windows device name" in reason

    def test_reserved_com1_rejected_by_write_path_validator(self):
        path = _SANDBOX5C + r"\COM1.json"
        ok, reason = validate_allowed_write_path(path)
        assert ok is False

    def test_trailing_dot_rejected_by_write_directory_validator(self):
        path = _SANDBOX5C + r"\subdir."
        ok, reason = validate_allowed_write_directory(path)
        assert ok is False
        assert "trailing dot or space" in reason

    def test_reserved_nul_rejected_by_write_directory_validator(self):
        path = _SANDBOX5C + r"\NUL"
        ok, reason = validate_allowed_write_directory(path)
        assert ok is False

    def test_mixed_separators_valid_path_passes(self):
        """Forward slashes in an otherwise valid sandbox path still pass."""
        path = _SANDBOX5C.replace("\\", "/") + "/notes.txt"
        ok, _ = validate_allowed_write_path(path)
        assert ok is True

    def test_adjacent_prefix_still_rejected(self):
        """A path whose string-prefix matches but is not a subdirectory is rejected."""
        evil = _SANDBOX5C + "_evil\\notes.txt"
        ok, _ = validate_allowed_write_path(evil)
        assert ok is False

    def test_traversal_still_rejected(self):
        """Path traversal via .. is still blocked even with the new helper."""
        traversal = _SANDBOX5C + r"\..\evil.txt"
        ok, _ = validate_allowed_write_path(traversal)
        assert ok is False

    def test_sandbox_root_as_file_target_rejected(self):
        """Sandbox root itself is not a valid file target."""
        ok, reason = validate_allowed_write_path(_SANDBOX5C)
        assert ok is False
        assert "sandbox root" in reason


# ---------------------------------------------------------------------------
# TestAtomicWrites
# ---------------------------------------------------------------------------

class TestAtomicWrites:
    """Atomic write behavior for _handle_write_text_file (Phase 5C)."""

    # --- overwrite path ---

    def test_overwrite_uses_named_temp_file(self):
        """overwrite mode calls NamedTemporaryFile then os.replace."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=True),
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("os.replace") as mock_replace,
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value.name = "/tmp/abc.tmp"
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ntf.return_value = mock_ctx
            execute_host_action(HostActionRequest(
                execution_id="exec-atom-ow",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="hello",
            ))
        assert mock_ntf.called
        assert mock_replace.called

    def test_overwrite_atomic_replace_used_true(self):
        """atomic_replace_used=True for overwrite mode."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=True),
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("os.replace"),
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value.name = "/tmp/abc.tmp"
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ntf.return_value = mock_ctx
            result = execute_host_action(HostActionRequest(
                execution_id="exec-atom-flag",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="hello",
            ))
        assert result.ok is True
        assert result.atomic_replace_used is True
        assert result.write_mode == "overwrite"

    def test_overwrite_audit_result_contains_atomic(self):
        """Outcome audit for overwrite must contain 'atomic' in result string."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=True),
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("os.replace"),
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value.name = "/tmp/abc.tmp"
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ntf.return_value = mock_ctx
            execute_host_action(HostActionRequest(
                execution_id="exec-atom-audit",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="hello",
            ))
        events = HOST_AUDIT_LOG.all_dicts()
        outcome = next(
            (e for e in events if e.get("event_type") == "host_action_outcome"),
            None,
        )
        assert outcome is not None
        assert "atomic" in outcome.get("result", "")

    def test_atomic_replace_failure_returns_error(self):
        """os.replace failure -> ok=False, WRITE_NOT_ALLOWED, temp cleaned up."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=True),
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("os.replace", side_effect=OSError("disk full")),
            patch("os.unlink") as mock_unlink,
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value.name = "/tmp/abc.tmp"
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ntf.return_value = mock_ctx
            result = execute_host_action(HostActionRequest(
                execution_id="exec-atom-fail",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="hello",
            ))
        assert result.ok is False
        assert result.error_code == HostErrorCode.WRITE_NOT_ALLOWED
        assert "atomic replace failed" in result.error
        mock_unlink.assert_called()

    def test_atomic_replace_failure_audits_outcome(self):
        """os.replace failure must emit 'atomic_replace_failed' outcome."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=True),
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("os.replace", side_effect=OSError("disk full")),
            patch("os.unlink"),
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value.name = "/tmp/abc.tmp"
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ntf.return_value = mock_ctx
            execute_host_action(HostActionRequest(
                execution_id="exec-atom-fail-audit",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="hello",
            ))
        events = HOST_AUDIT_LOG.all_dicts()
        outcome = next(
            (e for e in events if e.get("event_type") == "host_action_outcome"),
            None,
        )
        assert outcome is not None
        assert outcome.get("result") == "atomic_replace_failed"

    def test_atomic_replace_failure_cleans_temp_even_if_unlink_raises(self):
        """If os.unlink also fails, the error is swallowed (best-effort cleanup)."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=True),
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("os.replace", side_effect=OSError("disk full")),
            patch("os.unlink", side_effect=OSError("gone")),
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value.name = "/tmp/abc.tmp"
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ntf.return_value = mock_ctx
            result = execute_host_action(HostActionRequest(
                execution_id="exec-atom-unlink-fail",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="hello",
            ))
        assert result.ok is False
        assert result.error_code == HostErrorCode.WRITE_NOT_ALLOWED

    def test_atomic_replace_used_true_propagated_in_failure_result(self):
        """atomic_replace_used=True even when replace fails."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=True),
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("os.replace", side_effect=OSError("disk full")),
            patch("os.unlink"),
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value.name = "/tmp/abc.tmp"
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ntf.return_value = mock_ctx
            result = execute_host_action(HostActionRequest(
                execution_id="exec-atom-flag-fail",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="hello",
            ))
        assert result.atomic_replace_used is True

    # --- create path ---

    def test_create_does_not_use_named_temp_file(self):
        """create mode uses open('x'), not NamedTemporaryFile."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=False),
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            execute_host_action(HostActionRequest(
                execution_id="exec-atom-create",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="hello",
            ))
        mock_ntf.assert_not_called()

    def test_create_atomic_replace_used_false(self):
        """atomic_replace_used=False for create mode."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-atom-create-flag",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="hello",
            ))
        assert result.ok is True
        assert result.atomic_replace_used is False
        assert result.write_mode == "create"

    def test_create_audit_result_starts_with_create(self):
        """Outcome audit for create must start with 'create:'."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            execute_host_action(HostActionRequest(
                execution_id="exec-atom-create-audit",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="hi",
            ))
        events = HOST_AUDIT_LOG.all_dicts()
        outcome = next(
            (e for e in events if e.get("event_type") == "host_action_outcome"),
            None,
        )
        assert outcome is not None
        assert outcome.get("result", "").startswith("create:")

    def test_bytes_written_correct_for_unicode_content(self):
        """bytes_written reflects UTF-8 encoded byte count, not char count."""
        activate_agent(HOST_AGENT_ID)
        content = "h\u00e9llo"  # 'e with acute' is 2 bytes in UTF-8 -> 6 total
        expected_bytes = len(content.encode("utf-8"))
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-bytes",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content=content,
            ))
        assert result.ok is True
        assert result.bytes_written == expected_bytes

    def test_audit_does_not_contain_content(self):
        """Content must NEVER appear in any audit event."""
        activate_agent(HOST_AGENT_ID)
        secret = "sensitive-data-must-not-appear-in-audit"
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            execute_host_action(HostActionRequest(
                execution_id="exec-audit-secret",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content=secret,
            ))
        import json as _json
        for event in HOST_AUDIT_LOG.all_dicts():
            serialized = _json.dumps(event)
            assert secret not in serialized, f"Secret found in audit event: {event}"


# ---------------------------------------------------------------------------
# TestLifecyclePhase5C
# ---------------------------------------------------------------------------

class TestLifecyclePhase5C:
    """Lifecycle enrichment: _IN_FLIGHT shape + stale-PID audit (Phase 5C)."""

    def test_in_flight_record_has_action_field(self):
        """register_in_flight with action= stores it in the record."""
        register_in_flight(HOST_AGENT_ID, 1234, "exec-lc-1", action="open_app")
        records = get_in_flight(HOST_AGENT_ID)
        assert len(records) == 1
        assert records[0]["action"] == "open_app"

    def test_in_flight_record_has_started_at(self):
        """register_in_flight stores a started_at float."""
        import time as _time
        before = _time.time()
        register_in_flight(HOST_AGENT_ID, 5678, "exec-lc-2", action="open_directory")
        after = _time.time()
        records = get_in_flight(HOST_AGENT_ID)
        assert len(records) == 1
        started = records[0]["started_at"]
        assert isinstance(started, float)
        assert before <= started <= after

    def test_in_flight_action_defaults_to_empty_string(self):
        """Backward compat: omitting action= still works."""
        register_in_flight(HOST_AGENT_ID, 9999, "exec-lc-compat")
        records = get_in_flight(HOST_AGENT_ID)
        assert records[0]["action"] == ""

    def test_stale_pid_cleanup_emits_audit_outcome(self):
        """close_pid emits stale_cleaned outcome for each PID reconcile removes."""
        activate_agent(HOST_AGENT_ID)
        # 7777 is dead; 8888 is the target we will close
        register_in_flight(HOST_AGENT_ID, 7777, "exec-stale", action="open_app")
        register_in_flight(HOST_AGENT_ID, 8888, "exec-target", action="open_app")

        def fake_kill(pid, sig):
            if sig == 0:
                if pid == 7777:
                    raise OSError("no such process")
                return   # 8888 is alive
            return       # SIGTERM for the actual close

        with patch("os.kill", side_effect=fake_kill):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-closepid",
                action="close_pid",
                confirmed=True,
                pid=8888,
            ))

        assert result.ok is True
        events = HOST_AUDIT_LOG.all_dicts()
        stale_events = [
            e for e in events
            if e.get("event_type") == "host_action_outcome"
            and e.get("result") == "stale_cleaned"
        ]
        assert len(stale_events) == 1
        assert stale_events[0]["target"] == "7777"

    def test_close_pid_no_stale_events_when_nothing_to_clean(self):
        """close_pid emits zero stale_cleaned events when all PIDs are alive."""
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 1111, "exec-alive", action="open_app")

        with patch("os.kill"):
            execute_host_action(HostActionRequest(
                execution_id="exec-closepid-clean",
                action="close_pid",
                confirmed=True,
                pid=1111,
            ))

        events = HOST_AUDIT_LOG.all_dicts()
        stale_events = [e for e in events if e.get("result") == "stale_cleaned"]
        assert len(stale_events) == 0

    def test_close_pid_deregisters_from_in_flight(self):
        """After a successful close_pid, the PID is no longer in _IN_FLIGHT."""
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 2222, "exec-dereg", action="open_app")

        with patch("os.kill"):
            execute_host_action(HostActionRequest(
                execution_id="exec-dereg-close",
                action="close_pid",
                confirmed=True,
                pid=2222,
            ))

        records = get_in_flight(HOST_AGENT_ID)
        assert not any(r["pid"] == 2222 for r in records)


# ---------------------------------------------------------------------------
# TestPhase5CContracts
# ---------------------------------------------------------------------------

class TestPhase5CContracts:
    """Contract shape for Phase 5C additions."""

    def test_host_action_result_has_atomic_replace_used_field(self):
        """HostActionResult has atomic_replace_used defaulting to None."""
        r = HostActionResult(ok=True)
        assert hasattr(r, "atomic_replace_used")
        assert r.atomic_replace_used is None

    def test_write_create_success_shape(self):
        """Successful create: ok, write_mode='create', atomic_replace_used=False, bytes_written>=0."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-shape-create",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="test",
            ))
        assert result.ok is True
        assert result.write_mode == "create"
        assert result.atomic_replace_used is False
        assert isinstance(result.bytes_written, int)
        assert result.bytes_written >= 0

    def test_write_overwrite_success_shape(self):
        """Successful overwrite: ok, write_mode='overwrite', atomic_replace_used=True."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.isfile", return_value=True),
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("os.replace"),
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value.name = "/tmp/x.tmp"
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ntf.return_value = mock_ctx
            result = execute_host_action(HostActionRequest(
                execution_id="exec-shape-overwrite",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5C_FILE,
                content="updated",
            ))
        assert result.ok is True
        assert result.write_mode == "overwrite"
        assert result.atomic_replace_used is True
        assert result.bytes_written == len("updated".encode("utf-8"))

    def test_windows_reserved_stems_contains_nul(self):
        """Sanity: NUL is in the reserved set."""
        assert "NUL" in _WINDOWS_RESERVED_STEMS

    def test_windows_reserved_stems_contains_com9(self):
        assert "COM9" in _WINDOWS_RESERVED_STEMS

    def test_windows_reserved_stems_does_not_contain_common_names(self):
        """Common names must not be blocked."""
        for name in ("README", "notes", "data", "output", "report"):
            assert name.upper() not in _WINDOWS_RESERVED_STEMS

    def test_in_flight_record_shape(self):
        """In-flight records have all four Phase 5C fields."""
        register_in_flight(HOST_AGENT_ID, 3333, "exec-shape", action="open_app")
        records = get_in_flight(HOST_AGENT_ID)
        assert len(records) == 1
        r = records[0]
        assert "pid" in r
        assert "execution_id" in r
        assert "action" in r
        assert "started_at" in r
        assert r["pid"] == 3333
        assert r["execution_id"] == "exec-shape"
        assert r["action"] == "open_app"
        assert isinstance(r["started_at"], float)


# ===========================================================================
# Phase 5D — Symlink / junction hardening
# ===========================================================================

_SANDBOX5D_FILE  = _SANDBOX5C_FILE
_SANDBOX5D_DIR   = _SANDBOX5C_SUBDIR


class TestCheckNoSymlinkInPath:
    """Unit tests for _check_no_symlink_in_path helper."""

    def test_returns_true_when_no_components_exist(self):
        """Non-existent path → vacuously safe (lexists=False on all parts)."""
        with patch("os.path.lexists", return_value=False):
            ok, reason = _check_no_symlink_in_path(r"C:\sandbox\notes.txt")
        assert ok is True
        assert reason == ""

    def test_returns_false_when_leaf_is_symlink(self):
        """Leaf component that lexists and islink → rejected."""
        def _lexists(p):
            return True
        def _islink(p):
            # Only the leaf triggers islink=True
            return p.endswith("notes.txt")
        with (
            patch("os.path.lexists", side_effect=_lexists),
            patch("os.path.islink", side_effect=_islink),
        ):
            ok, reason = _check_no_symlink_in_path(r"C:\sandbox\notes.txt")
        assert ok is False
        assert "symlink or junction" in reason

    def test_returns_false_when_intermediate_directory_is_junction(self):
        """Junction in an intermediate component → rejected."""
        def _lexists(p):
            return True
        def _islink(p):
            # Only the intermediate dir triggers islink=True
            return "sandbox" in p and not p.endswith("notes.txt")
        with (
            patch("os.path.lexists", side_effect=_lexists),
            patch("os.path.islink", side_effect=_islink),
        ):
            ok, reason = _check_no_symlink_in_path(r"C:\sandbox\notes.txt")
        assert ok is False
        assert "symlink or junction" in reason
        assert "sandbox" in reason

    def test_returns_true_when_components_exist_but_are_not_symlinks(self):
        """Real directory + real file (no symlink) → safe."""
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=False),
        ):
            ok, reason = _check_no_symlink_in_path(r"C:\sandbox\notes.txt")
        assert ok is True
        assert reason == ""

    def test_dangling_symlink_caught_via_lexists(self):
        """
        Dangling symlink: lexists=True (lexists follows no links), islink=True.
        Must be caught even though exists() would return False.
        """
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
        ):
            ok, reason = _check_no_symlink_in_path(r"C:\sandbox\dangling")
        assert ok is False
        assert "symlink or junction" in reason


class TestSymlinkHardening:
    """
    Integration tests: all three write handlers reject paths containing
    a symlink or junction via SYMLINK_NOT_ALLOWED error code.
    """

    def _symlink_patches(self):
        """Context managers: all existing path components are symlinks."""
        return (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
        )

    # --- write_text_file ---

    def test_write_text_file_rejects_symlink_in_path(self):
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
        ):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-sym-write",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5D_FILE,
                content="hello",
            ))
        assert result.ok is False
        assert result.error_code == HostErrorCode.SYMLINK_NOT_ALLOWED
        assert "symlink" in (result.error or "").lower()

    def test_write_text_file_symlink_rejection_does_not_write(self):
        """No filesystem write occurs when symlink is detected."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
            patch("builtins.open") as mock_open,
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
        ):
            execute_host_action(HostActionRequest(
                execution_id="exec-sym-write-nowrite",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5D_FILE,
                content="hello",
            ))
        mock_open.assert_not_called()
        mock_ntf.assert_not_called()

    def test_write_text_file_no_symlink_proceeds(self):
        """Without symlink, write proceeds normally (create path)."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.lexists", return_value=False),
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-sym-write-ok",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5D_FILE,
                content="hello",
            ))
        assert result.ok is True

    # --- append_text_file ---

    def test_append_text_file_rejects_symlink_in_path(self):
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
        ):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-sym-append",
                action="append_text_file",
                confirmed=True,
                path=_SANDBOX5D_FILE,
                content="more",
            ))
        assert result.ok is False
        assert result.error_code == HostErrorCode.SYMLINK_NOT_ALLOWED
        assert result.action == "append_text_file"

    def test_append_text_file_symlink_rejection_before_isfile_check(self):
        """
        Symlink check fires before the FILE_NOT_FOUND isfile() check.
        The error code must be SYMLINK_NOT_ALLOWED, not FILE_NOT_FOUND.
        """
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
            # isfile returns False — would cause FILE_NOT_FOUND if reached
            patch("os.path.isfile", return_value=False),
        ):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-sym-append-order",
                action="append_text_file",
                confirmed=True,
                path=_SANDBOX5D_FILE,
                content="x",
            ))
        assert result.error_code == HostErrorCode.SYMLINK_NOT_ALLOWED

    # --- create_directory ---

    def test_create_directory_rejects_symlink_in_path(self):
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
        ):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-sym-mkdir",
                action="create_directory",
                confirmed=True,
                path=_SANDBOX5D_DIR,
            ))
        assert result.ok is False
        assert result.error_code == HostErrorCode.SYMLINK_NOT_ALLOWED
        assert result.action == "create_directory"

    def test_create_directory_symlink_rejection_before_isfile_check(self):
        """Symlink check fires before PATH_CONFLICT (isfile) check."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
            # isfile=True would give PATH_CONFLICT if reached
            patch("os.path.isfile", return_value=True),
        ):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-sym-mkdir-order",
                action="create_directory",
                confirmed=True,
                path=_SANDBOX5D_DIR,
            ))
        assert result.error_code == HostErrorCode.SYMLINK_NOT_ALLOWED

    def test_create_directory_no_symlink_proceeds(self):
        """Without symlink, mkdir proceeds normally."""
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.lexists", return_value=False),
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=False),
            patch("os.mkdir"),
        ):
            result = execute_host_action(HostActionRequest(
                execution_id="exec-sym-mkdir-ok",
                action="create_directory",
                confirmed=True,
                path=_SANDBOX5D_DIR,
            ))
        assert result.ok is True

    def test_symlink_not_allowed_error_code_in_audit(self):
        """
        Symlink rejection for write_text_file does NOT emit an intent event —
        it is rejected before the intent audit.  No intent event in the log.
        """
        activate_agent(HOST_AGENT_ID)
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
        ):
            execute_host_action(HostActionRequest(
                execution_id="exec-sym-audit",
                action="write_text_file",
                confirmed=True,
                path=_SANDBOX5D_FILE,
                content="hi",
            ))
        # No intent event should have been emitted (rejection before audit gate)
        events = HOST_AUDIT_LOG.all_dicts()
        intent_events = [
            e for e in events
            if e.get("event_type") == "host_action_intent"
            and e.get("action") == "write_text_file"
        ]
        assert len(intent_events) == 0


# ===========================================================================
# Phase 5D — Kill-switch lifecycle: reconcile before abort
# ===========================================================================


class TestKillSwitchLifecycle5D:
    """kill_switch() must call reconcile_in_flight before abort_in_flight."""

    def test_kill_switch_with_only_dead_pid_produces_no_abort_attempts(self):
        """
        A PID that is already dead is pruned by reconcile_in_flight so
        abort_in_flight never tries to SIGTERM it — no AbortResult generated.
        """
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 99999, "exec-ks-dead")
        # Simulate dead process: _is_pid_alive → False
        with patch("assistant_os.core.control_plane._is_pid_alive", return_value=False):
            result = kill_switch(HOST_AGENT_ID)
        # Agent is quarantined
        assert get_agent_status(HOST_AGENT_ID) == AgentStatus.QUARANTINE
        # Dead PID was pruned by reconcile; abort_in_flight had nothing to do
        assert result.abort_results == []

    def test_kill_switch_with_live_pid_aborts_it(self):
        """Live PID survives reconcile and is terminated by abort_in_flight."""
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 77777, "exec-ks-live")
        with (
            patch("assistant_os.core.control_plane._is_pid_alive", return_value=True),
            patch("os.kill") as mock_kill,
        ):
            result = kill_switch(HOST_AGENT_ID)
        assert get_agent_status(HOST_AGENT_ID) == AgentStatus.QUARANTINE
        assert len(result.abort_results) == 1
        assert result.abort_results[0].pid == 77777
        assert result.abort_results[0].success is True
        mock_kill.assert_called_once_with(77777, signal.SIGTERM)

    def test_kill_switch_mixed_dead_and_live(self):
        """Dead PIDs pruned; live PIDs aborted; no error from dead PIDs."""
        activate_agent(HOST_AGENT_ID)
        register_in_flight(HOST_AGENT_ID, 11111, "exec-dead")
        register_in_flight(HOST_AGENT_ID, 22222, "exec-live")
        dead_pid = 11111
        live_pid = 22222

        def _is_alive(pid):
            return pid != dead_pid

        with (
            patch("assistant_os.core.control_plane._is_pid_alive", side_effect=_is_alive),
            patch("os.kill"),
        ):
            result = kill_switch(HOST_AGENT_ID)

        # Only live PID appears in abort_results
        aborted_pids = [r.pid for r in result.abort_results]
        assert live_pid in aborted_pids
        assert dead_pid not in aborted_pids

    def test_kill_switch_empty_registry_is_clean(self):
        """kill_switch with no in-flight PIDs returns empty results cleanly."""
        activate_agent(HOST_AGENT_ID)
        result = kill_switch(HOST_AGENT_ID)
        assert result.agent_id == HOST_AGENT_ID
        assert result.abort_results == []
        assert get_agent_status(HOST_AGENT_ID) == AgentStatus.QUARANTINE

    def test_kill_switch_quarantines_before_abort(self):
        """
        Quarantine is set before any kill attempt, so new launches are blocked
        even if abort takes time.
        """
        activate_agent(HOST_AGENT_ID)
        quarantine_seen_during_kill = []

        def _mock_kill(pid, sig):
            quarantine_seen_during_kill.append(
                get_agent_status(HOST_AGENT_ID) == AgentStatus.QUARANTINE
            )

        register_in_flight(HOST_AGENT_ID, 55555, "exec-order")
        with (
            patch("assistant_os.core.control_plane._is_pid_alive", return_value=True),
            patch("os.kill", side_effect=_mock_kill),
        ):
            kill_switch(HOST_AGENT_ID)
        # All kill calls saw QUARANTINE status
        assert quarantine_seen_during_kill
        assert all(quarantine_seen_during_kill)


# ===========================================================================
# Phase 5D — Contract consistency: all HOST actions
# ===========================================================================


class TestContractConsistency5D:
    """
    All HOST action results must have consistent shapes regardless of outcome.

    Invariants verified:
    - ok is always a bool
    - action is always a non-empty str matching the request
    - execution_id always echoes the request
    - On failure: error is a non-empty str; error_code is a HostErrorCode instance
    - On success: error is None; error_code is None
    """

    def _req(self, action: str, **kwargs) -> HostActionRequest:
        activate_agent(HOST_AGENT_ID)
        return HostActionRequest(
            execution_id="exec-contract",
            action=action,
            confirmed=True,
            **kwargs,
        )

    def _assert_base_contract(self, result: HostActionResult, action: str) -> None:
        assert isinstance(result.ok, bool)
        assert result.action == action
        assert result.execution_id == "exec-contract"

    def _assert_failure_contract(self, result: HostActionResult, action: str) -> None:
        self._assert_base_contract(result, action)
        assert result.ok is False
        assert result.error is not None and result.error != ""
        assert isinstance(result.error_code, HostErrorCode)

    def _assert_success_contract(self, result: HostActionResult, action: str) -> None:
        self._assert_base_contract(result, action)
        assert result.ok is True
        assert result.error is None
        assert result.error_code is None

    # Gate-level failure shape (applies to all actions)
    def test_confirmed_false_has_consistent_shape(self):
        activate_agent(HOST_AGENT_ID)
        result = execute_host_action(HostActionRequest(
            execution_id="exec-contract",
            action="open_app",
            confirmed=False,
            app_name="notepad",
        ))
        self._assert_failure_contract(result, "open_app")

    def test_unknown_action_has_consistent_shape(self):
        activate_agent(HOST_AGENT_ID)
        result = execute_host_action(HostActionRequest(
            execution_id="exec-contract",
            action="nonexistent_action",
            confirmed=True,
        ))
        self._assert_failure_contract(result, "nonexistent_action")

    # write_text_file success shape
    def test_write_text_file_success_shape(self):
        with (
            patch("os.path.lexists", return_value=False),
            patch("os.path.isfile", return_value=False),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            result = execute_host_action(self._req(
                "write_text_file", path=_SANDBOX5D_FILE, content="x"
            ))
        self._assert_success_contract(result, "write_text_file")
        assert result.bytes_written is not None
        assert result.write_mode in ("create", "overwrite")
        assert isinstance(result.atomic_replace_used, bool)

    # write_text_file failure shape (invalid path)
    def test_write_text_file_failure_shape_bad_path(self):
        result = execute_host_action(self._req(
            "write_text_file",
            path=r"C:\Windows\evil.txt",
            content="x",
        ))
        self._assert_failure_contract(result, "write_text_file")

    # append_text_file failure shape (file not found)
    def test_append_text_file_failure_shape_not_found(self):
        with (
            patch("os.path.lexists", return_value=False),
            patch("os.path.isfile", return_value=False),
        ):
            result = execute_host_action(self._req(
                "append_text_file", path=_SANDBOX5D_FILE, content="x"
            ))
        self._assert_failure_contract(result, "append_text_file")
        assert result.error_code == HostErrorCode.FILE_NOT_FOUND

    # create_directory success shape
    def test_create_directory_success_shape(self):
        with (
            patch("os.path.lexists", return_value=False),
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=False),
            patch("os.mkdir"),
        ):
            result = execute_host_action(self._req(
                "create_directory", path=_SANDBOX5D_DIR
            ))
        self._assert_success_contract(result, "create_directory")
        # Write-specific fields not set for create_directory
        assert result.bytes_written is None
        assert result.write_mode is None

    # create_directory failure shape (already exists)
    def test_create_directory_failure_already_exists_shape(self):
        with (
            patch("os.path.lexists", return_value=False),
            patch("os.path.isfile", return_value=False),
            patch("os.path.isdir", return_value=True),
        ):
            result = execute_host_action(self._req(
                "create_directory", path=_SANDBOX5D_DIR
            ))
        self._assert_failure_contract(result, "create_directory")
        assert result.error_code == HostErrorCode.DIRECTORY_ALREADY_EXISTS

    # Symlink rejection shape (all three write actions)
    def test_write_text_file_symlink_rejection_shape(self):
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
        ):
            result = execute_host_action(self._req(
                "write_text_file", path=_SANDBOX5D_FILE, content="x"
            ))
        self._assert_failure_contract(result, "write_text_file")
        assert result.error_code == HostErrorCode.SYMLINK_NOT_ALLOWED

    def test_append_text_file_symlink_rejection_shape(self):
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
        ):
            result = execute_host_action(self._req(
                "append_text_file", path=_SANDBOX5D_FILE, content="x"
            ))
        self._assert_failure_contract(result, "append_text_file")
        assert result.error_code == HostErrorCode.SYMLINK_NOT_ALLOWED

    def test_create_directory_symlink_rejection_shape(self):
        with (
            patch("os.path.lexists", return_value=True),
            patch("os.path.islink", return_value=True),
        ):
            result = execute_host_action(self._req(
                "create_directory", path=_SANDBOX5D_DIR
            ))
        self._assert_failure_contract(result, "create_directory")
        assert result.error_code == HostErrorCode.SYMLINK_NOT_ALLOWED
