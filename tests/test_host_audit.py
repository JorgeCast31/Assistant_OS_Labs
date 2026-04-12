"""
Tests — host_audit.py

Coverage
--------
A. HostIntentEvent — structure, to_dict, frozen
B. HostOutcomeEvent — structure, to_dict, includes pid
C. emit_host_intent — writes to HOST_AUDIT_LOG, raises HostAuditError on failure
D. emit_host_outcome — writes to HOST_AUDIT_LOG with pid
E. HOST_AUDIT_LOG — thread-safe, filterable by event_type
F. HostActionIntentEvent (Fase 2)
G. HostActionOutcomeEvent (Fase 2)
H. emit_action_intent (Fase 2)
I. emit_action_outcome (Fase 2)
J. HostErrorCode taxonomy (Phase 2.5)
K. HostRejectionEvent + emit_host_rejection (Phase 2.5)
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from assistant_os.agents.host_audit import (
    HOST_AUDIT_LOG,
    HostAuditError,
    HostAuditEventType,
    HostActionIntentEvent,
    HostActionOutcomeEvent,
    HostErrorCode,
    HostIntentEvent,
    HostOutcomeEvent,
    HostRejectionEvent,
    emit_action_intent,
    emit_action_outcome,
    emit_host_intent,
    emit_host_outcome,
    emit_host_rejection,
)


@pytest.fixture(autouse=True)
def clear_log():
    """Clear HOST_AUDIT_LOG before and after every test."""
    HOST_AUDIT_LOG.clear()
    yield
    HOST_AUDIT_LOG.clear()


# ===========================================================================
# A. HostIntentEvent
# ===========================================================================


class TestHostIntentEvent:
    def _make(self, **kwargs):
        defaults = dict(
            event_type=HostAuditEventType.HOST_INTENT,
            agent_id="agent-1",
            execution_id="exec-001",
            app_name="notepad",
            executable="notepad.exe",
            timestamp=1000.0,
        )
        defaults.update(kwargs)
        return HostIntentEvent(**defaults)

    def test_event_type_is_host_intent(self):
        assert self._make().event_type == "host_intent"

    def test_to_dict_has_all_fields(self):
        event = self._make()
        d = event.to_dict()
        for key in ("event_type", "agent_id", "execution_id", "app_name", "executable", "timestamp"):
            assert key in d, f"missing key: {key!r}"

    def test_to_dict_values_correct(self):
        event = self._make(agent_id="ag1", execution_id="ex1", app_name="calc", executable="calc.exe")
        d = event.to_dict()
        assert d["agent_id"]     == "ag1"
        assert d["execution_id"] == "ex1"
        assert d["app_name"]     == "calc"
        assert d["executable"]   == "calc.exe"

    def test_event_is_frozen(self):
        event = self._make()
        with pytest.raises((AttributeError, TypeError)):
            event.agent_id = "changed"  # type: ignore[misc]

    def test_to_dict_no_pid_field(self):
        """Intent events do not carry a pid — pid is only in outcome events."""
        d = self._make().to_dict()
        assert "pid" not in d


# ===========================================================================
# B. HostOutcomeEvent
# ===========================================================================


class TestHostOutcomeEvent:
    def _make(self, **kwargs):
        defaults = dict(
            event_type=HostAuditEventType.HOST_OUTCOME,
            agent_id="agent-1",
            execution_id="exec-001",
            app_name="notepad",
            executable="notepad.exe",
            pid=12345,
            timestamp=2000.0,
        )
        defaults.update(kwargs)
        return HostOutcomeEvent(**defaults)

    def test_event_type_is_host_outcome(self):
        assert self._make().event_type == "host_outcome"

    def test_to_dict_has_all_fields(self):
        d = self._make().to_dict()
        for key in ("event_type", "agent_id", "execution_id", "app_name", "executable", "pid", "timestamp"):
            assert key in d, f"missing key: {key!r}"

    def test_pid_in_to_dict(self):
        d = self._make(pid=9876).to_dict()
        assert d["pid"] == 9876

    def test_event_is_frozen(self):
        event = self._make()
        with pytest.raises((AttributeError, TypeError)):
            event.pid = 0  # type: ignore[misc]

    def test_to_dict_values_correct(self):
        event = self._make(app_name="calc", executable="calc.exe", pid=111)
        d = event.to_dict()
        assert d["app_name"]   == "calc"
        assert d["executable"] == "calc.exe"
        assert d["pid"]        == 111


# ===========================================================================
# C. emit_host_intent
# ===========================================================================


class TestEmitHostIntent:
    def test_emits_event_to_log(self):
        emit_host_intent(
            agent_id="agent-1",
            app_name="notepad",
            execution_id="exec-001",
            executable="notepad.exe",
        )
        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_INTENT)
        assert len(events) == 1

    def test_emitted_event_fields(self):
        emit_host_intent(
            agent_id="agent-x",
            app_name="calc",
            execution_id="exec-calc-1",
            executable="calc.exe",
        )
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_INTENT)[0]
        assert event.agent_id     == "agent-x"
        assert event.app_name     == "calc"
        assert event.execution_id == "exec-calc-1"
        assert event.executable   == "calc.exe"

    def test_emitted_event_has_timestamp(self):
        before = time.time()
        emit_host_intent(
            agent_id="a", app_name="notepad", execution_id="e1", executable="notepad.exe"
        )
        after = time.time()
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_INTENT)[0]
        assert before <= event.timestamp <= after

    def test_raises_host_audit_error_on_log_failure(self):
        with patch.object(HOST_AUDIT_LOG, "emit", side_effect=RuntimeError("disk full")):
            with pytest.raises(HostAuditError, match="failed to emit host intent"):
                emit_host_intent(
                    agent_id="a", app_name="notepad", execution_id="e1", executable="notepad.exe"
                )

    def test_host_audit_error_wraps_original_exception(self):
        with patch.object(HOST_AUDIT_LOG, "emit", side_effect=ValueError("bad state")):
            with pytest.raises(HostAuditError) as exc_info:
                emit_host_intent(
                    agent_id="a", app_name="notepad", execution_id="e1", executable="notepad.exe"
                )
        assert exc_info.value.__cause__ is not None

    def test_multiple_intent_events_accumulate(self):
        for i in range(3):
            emit_host_intent(
                agent_id="a", app_name="notepad", execution_id=f"exec-{i}", executable="notepad.exe"
            )
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_INTENT) == 3


# ===========================================================================
# D. emit_host_outcome
# ===========================================================================


class TestEmitHostOutcome:
    def test_emits_event_to_log(self):
        emit_host_outcome(
            agent_id="agent-1",
            app_name="notepad",
            execution_id="exec-001",
            executable="notepad.exe",
            pid=5555,
        )
        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_OUTCOME)
        assert len(events) == 1

    def test_emitted_event_has_pid(self):
        emit_host_outcome(
            agent_id="a", app_name="calc", execution_id="e1", executable="calc.exe", pid=9999
        )
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_OUTCOME)[0]
        assert event.pid == 9999

    def test_emitted_event_fields(self):
        emit_host_outcome(
            agent_id="ag2",
            app_name="notepad",
            execution_id="exec-np-1",
            executable="notepad.exe",
            pid=1234,
        )
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_OUTCOME)[0]
        assert event.agent_id     == "ag2"
        assert event.app_name     == "notepad"
        assert event.execution_id == "exec-np-1"
        assert event.executable   == "notepad.exe"

    def test_emitted_outcome_has_timestamp(self):
        before = time.time()
        emit_host_outcome(
            agent_id="a", app_name="calc", execution_id="e1", executable="calc.exe", pid=1
        )
        after = time.time()
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_OUTCOME)[0]
        assert before <= event.timestamp <= after


# ===========================================================================
# E. HOST_AUDIT_LOG — filtering and isolation
# ===========================================================================


class TestHostAuditLog:
    def test_intent_and_outcome_events_are_separate(self):
        emit_host_intent(
            agent_id="a", app_name="notepad", execution_id="e1", executable="notepad.exe"
        )
        emit_host_outcome(
            agent_id="a", app_name="notepad", execution_id="e1", executable="notepad.exe", pid=100
        )
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_INTENT)  == 1
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_OUTCOME) == 1
        assert HOST_AUDIT_LOG.count() == 2

    def test_all_dicts_is_safe_for_logging(self):
        emit_host_intent(
            agent_id="a", app_name="notepad", execution_id="e1", executable="notepad.exe"
        )
        dicts = HOST_AUDIT_LOG.all_dicts()
        assert len(dicts) == 1
        assert isinstance(dicts[0], dict)
        assert "event_type" in dicts[0]


# ===========================================================================
# F. HostActionIntentEvent (Fase 2)
# ===========================================================================


class TestHostActionIntentEvent:
    def _make(self, **kwargs):
        defaults = dict(
            event_type=HostAuditEventType.HOST_ACTION_INTENT,
            agent_id="host_launcher",
            execution_id="exec-001",
            action="close_pid",
            target="1234",
            timestamp=3000.0,
        )
        defaults.update(kwargs)
        return HostActionIntentEvent(**defaults)

    def test_event_type_is_host_action_intent(self):
        assert self._make().event_type == "host_action_intent"

    def test_to_dict_has_all_fields(self):
        d = self._make().to_dict()
        for key in ("event_type", "agent_id", "execution_id", "action", "target", "timestamp"):
            assert key in d, f"missing key: {key!r}"

    def test_to_dict_values_correct(self):
        event = self._make(action="open_url", target="https://github.com")
        d = event.to_dict()
        assert d["action"]  == "open_url"
        assert d["target"]  == "https://github.com"
        assert d["agent_id"] == "host_launcher"

    def test_event_is_frozen(self):
        event = self._make()
        with pytest.raises((AttributeError, TypeError)):
            event.action = "changed"  # type: ignore[misc]

    def test_no_pid_or_result_field(self):
        d = self._make().to_dict()
        assert "pid" not in d
        assert "result" not in d


# ===========================================================================
# G. HostActionOutcomeEvent (Fase 2)
# ===========================================================================


class TestHostActionOutcomeEvent:
    def _make(self, **kwargs):
        defaults = dict(
            event_type=HostAuditEventType.HOST_ACTION_OUTCOME,
            agent_id="host_launcher",
            execution_id="exec-001",
            action="open_directory",
            target=r"C:\Users\Jorge\Documents",
            result="opened",
            pid=7777,
            timestamp=4000.0,
        )
        defaults.update(kwargs)
        return HostActionOutcomeEvent(**defaults)

    def test_event_type_is_host_action_outcome(self):
        assert self._make().event_type == "host_action_outcome"

    def test_to_dict_has_all_fields(self):
        d = self._make().to_dict()
        for key in ("event_type", "agent_id", "execution_id", "action", "target", "result", "pid", "timestamp"):
            assert key in d, f"missing key: {key!r}"

    def test_pid_can_be_none(self):
        event = self._make(pid=None)
        assert event.pid is None
        assert event.to_dict()["pid"] is None

    def test_to_dict_values_correct(self):
        event = self._make(action="close_pid", target="9090", result="terminated", pid=None)
        d = event.to_dict()
        assert d["action"]  == "close_pid"
        assert d["result"]  == "terminated"
        assert d["pid"]     is None

    def test_event_is_frozen(self):
        event = self._make()
        with pytest.raises((AttributeError, TypeError)):
            event.result = "failed"  # type: ignore[misc]


# ===========================================================================
# H. emit_action_intent (Fase 2)
# ===========================================================================


class TestEmitActionIntent:
    def test_emits_event_to_log(self):
        emit_action_intent(
            agent_id="host_launcher",
            execution_id="exec-001",
            action="close_pid",
            target="1234",
        )
        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_INTENT)
        assert len(events) == 1

    def test_emitted_event_fields(self):
        emit_action_intent(
            agent_id="host_launcher",
            execution_id="exec-dir-1",
            action="open_directory",
            target=r"C:\Users\Jorge\Documents",
        )
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_INTENT)[0]
        assert event.agent_id     == "host_launcher"
        assert event.execution_id == "exec-dir-1"
        assert event.action       == "open_directory"
        assert event.target       == r"C:\Users\Jorge\Documents"

    def test_emitted_event_has_timestamp(self):
        before = time.time()
        emit_action_intent(
            agent_id="host_launcher", execution_id="e1",
            action="open_url", target="https://github.com",
        )
        after = time.time()
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_INTENT)[0]
        assert before <= event.timestamp <= after

    def test_raises_host_audit_error_on_log_failure(self):
        with patch.object(HOST_AUDIT_LOG, "emit", side_effect=RuntimeError("disk full")):
            with pytest.raises(HostAuditError, match="failed to emit action intent"):
                emit_action_intent(
                    agent_id="host_launcher", execution_id="e1",
                    action="close_pid", target="999",
                )

    def test_host_audit_error_wraps_cause(self):
        with patch.object(HOST_AUDIT_LOG, "emit", side_effect=ValueError("bad")):
            with pytest.raises(HostAuditError) as exc_info:
                emit_action_intent(
                    agent_id="host_launcher", execution_id="e1",
                    action="open_url", target="https://github.com",
                )
        assert exc_info.value.__cause__ is not None

    def test_multiple_intents_accumulate(self):
        for action in ("close_pid", "open_directory", "open_url"):
            emit_action_intent(
                agent_id="host_launcher", execution_id=f"exec-{action}",
                action=action, target="x",
            )
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_ACTION_INTENT) == 3


# ===========================================================================
# I. emit_action_outcome (Fase 2)
# ===========================================================================


class TestEmitActionOutcome:
    def test_emits_event_to_log(self):
        emit_action_outcome(
            agent_id="host_launcher",
            execution_id="exec-001",
            action="close_pid",
            target="1234",
            result="terminated",
        )
        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_OUTCOME)
        assert len(events) == 1

    def test_emitted_event_fields(self):
        emit_action_outcome(
            agent_id="host_launcher",
            execution_id="exec-od-1",
            action="open_directory",
            target=r"C:\Users\Jorge\Downloads",
            result="opened",
            pid=5555,
        )
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_OUTCOME)[0]
        assert event.agent_id     == "host_launcher"
        assert event.execution_id == "exec-od-1"
        assert event.action       == "open_directory"
        assert event.result       == "opened"
        assert event.pid          == 5555

    def test_pid_defaults_to_none(self):
        emit_action_outcome(
            agent_id="host_launcher",
            execution_id="exec-url-1",
            action="open_url",
            target="https://github.com",
            result="opened",
        )
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_OUTCOME)[0]
        assert event.pid is None

    def test_emitted_event_has_timestamp(self):
        before = time.time()
        emit_action_outcome(
            agent_id="host_launcher", execution_id="e1",
            action="close_pid", target="1", result="terminated",
        )
        after = time.time()
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_ACTION_OUTCOME)[0]
        assert before <= event.timestamp <= after

    def test_intent_and_outcome_coexist_in_log(self):
        emit_action_intent(
            agent_id="host_launcher", execution_id="e1", action="open_url", target="https://github.com"
        )
        emit_action_outcome(
            agent_id="host_launcher", execution_id="e1", action="open_url",
            target="https://github.com", result="opened",
        )
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_ACTION_INTENT)  == 1
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_ACTION_OUTCOME) == 1
        assert HOST_AUDIT_LOG.count() == 2


# ===========================================================================
# J. HostErrorCode taxonomy (Phase 2.5)
# ===========================================================================


class TestHostErrorCode:
    def test_all_expected_codes_exist(self):
        expected = {
            "confirmed_required", "control_plane_blocked", "audit_failure",
            "unknown_action", "rate_limit_exceeded",
            "invalid_app_name",
            "invalid_pid", "pid_not_owned", "process_already_exited",
            "directory_not_allowed",
            "url_invalid", "url_scheme_not_allowed", "url_domain_not_allowed",
        }
        actual = {code.value for code in HostErrorCode}
        assert expected.issubset(actual), f"missing codes: {expected - actual}"

    def test_codes_are_strings(self):
        for code in HostErrorCode:
            assert isinstance(code.value, str)

    def test_codes_are_lowercase(self):
        for code in HostErrorCode:
            assert code.value == code.value.lower(), f"{code.value!r} is not lowercase"

    def test_codes_are_unique(self):
        values = [code.value for code in HostErrorCode]
        assert len(values) == len(set(values))


# ===========================================================================
# K. HostRejectionEvent + emit_host_rejection (Phase 2.5)
# ===========================================================================


class TestHostRejectionEvent:
    def _make(self, **kwargs):
        defaults = dict(
            event_type=HostAuditEventType.HOST_REJECTION,
            agent_id="host_launcher",
            execution_id="exec-001",
            action="open_app",
            reason="not confirmed",
            error_code=HostErrorCode.CONFIRMED_REQUIRED,
            timestamp=9000.0,
        )
        defaults.update(kwargs)
        return HostRejectionEvent(**defaults)

    def test_event_type_is_host_rejection(self):
        assert self._make().event_type == "host_rejection"

    def test_to_dict_has_all_fields(self):
        d = self._make().to_dict()
        for key in ("event_type", "agent_id", "execution_id", "action", "reason", "error_code", "timestamp"):
            assert key in d, f"missing key: {key!r}"

    def test_to_dict_error_code_is_string(self):
        d = self._make(error_code=HostErrorCode.CONFIRMED_REQUIRED).to_dict()
        assert d["error_code"] == "confirmed_required"

    def test_to_dict_values_correct(self):
        event = self._make(action="open_url", reason="scheme not allowed",
                           error_code=HostErrorCode.URL_SCHEME_NOT_ALLOWED)
        d = event.to_dict()
        assert d["action"]     == "open_url"
        assert d["reason"]     == "scheme not allowed"
        assert d["error_code"] == "url_scheme_not_allowed"

    def test_event_is_frozen(self):
        event = self._make()
        with pytest.raises((AttributeError, TypeError)):
            event.reason = "changed"  # type: ignore[misc]


class TestEmitHostRejection:
    def test_emits_event_to_log(self):
        emit_host_rejection(
            agent_id="host_launcher",
            execution_id="exec-001",
            action="open_app",
            reason="not confirmed",
            error_code=HostErrorCode.CONFIRMED_REQUIRED,
        )
        events = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_REJECTION)
        assert len(events) == 1

    def test_emitted_event_fields(self):
        emit_host_rejection(
            agent_id="host_launcher",
            execution_id="exec-rej-1",
            action="open_url",
            reason="agent is paused",
            error_code=HostErrorCode.CONTROL_PLANE_BLOCKED,
        )
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_REJECTION)[0]
        assert event.agent_id     == "host_launcher"
        assert event.execution_id == "exec-rej-1"
        assert event.action       == "open_url"
        assert event.reason       == "agent is paused"
        assert event.error_code   == HostErrorCode.CONTROL_PLANE_BLOCKED

    def test_emitted_event_has_timestamp(self):
        before = time.time()
        emit_host_rejection(
            agent_id="host_launcher", execution_id="e1", action="open_app",
            reason="r", error_code=HostErrorCode.CONFIRMED_REQUIRED,
        )
        after = time.time()
        event = HOST_AUDIT_LOG.events(HostAuditEventType.HOST_REJECTION)[0]
        assert before <= event.timestamp <= after

    def test_does_not_raise_on_log_failure(self):
        """emit_host_rejection is best-effort — must never raise."""
        with patch.object(HOST_AUDIT_LOG, "emit", side_effect=RuntimeError("disk full")):
            emit_host_rejection(
                agent_id="host_launcher", execution_id="e1", action="open_app",
                reason="r", error_code=HostErrorCode.CONFIRMED_REQUIRED,
            )
        # No exception raised — test passes if we get here

    def test_multiple_rejections_accumulate(self):
        for code in (HostErrorCode.CONFIRMED_REQUIRED,
                     HostErrorCode.CONTROL_PLANE_BLOCKED,
                     HostErrorCode.RATE_LIMIT_EXCEEDED):
            emit_host_rejection(
                agent_id="host_launcher", execution_id="e1", action="open_app",
                reason="r", error_code=code,
            )
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_REJECTION) == 3

    def test_rejection_does_not_pollute_intent_or_outcome_counts(self):
        emit_host_rejection(
            agent_id="host_launcher", execution_id="e1", action="open_app",
            reason="r", error_code=HostErrorCode.CONFIRMED_REQUIRED,
        )
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_INTENT)  == 0
        assert HOST_AUDIT_LOG.count(HostAuditEventType.HOST_OUTCOME) == 0
