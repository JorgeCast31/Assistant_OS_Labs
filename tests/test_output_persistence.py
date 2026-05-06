"""
Sprint 6.5 — Output Persistence Hardening

Test classes
------------
A  TestPersistenceDecisionModel    — PersistenceDecision construction + to_dict
B  TestDecidePersistenceSafe       — safe classification → raw mode, streams unchanged
C  TestDecidePersistenceWarning    — warning classification → raw mode, streams unchanged
D  TestDecidePersistenceSensitive  — sensitive classification → redacted mode, secrets gone
E  TestDecidePersistenceInvalid    — invalid classification → truncated mode, capped
F  TestDecidePersistenceNone       — None inspection_result → raw fallback
G  TestDecidePersistenceUnknown    — unknown classification → raw fallback (future-proof)
H  TestNoBypass                    — sensitive output never reaches to_dict() as raw
I  TestRunnerAPIPersistence        — RunnerAPI sets persisted fields on ExecutionResult
J  TestOutputRedactedAuditEvent    — OUTPUT_REDACTED event emitted for sensitive/invalid
K  TestNoLeakageInAuditEvent       — OutputRedactedEvent never contains output content
L  TestExecutionResultToDict       — to_dict() exposes governed streams + new fields
M  TestPersistencePolicyExports    — public API surface available from assistant_os.output
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest


# ===========================================================================
# A — TestPersistenceDecisionModel
# ===========================================================================

class TestPersistenceDecisionModel:
    def test_construction(self):
        from assistant_os.output.persistence_policy import PersistenceDecision
        d = PersistenceDecision(
            stdout="hello",
            stderr="world",
            mode="raw",
            was_redacted=False,
            was_truncated=False,
        )
        assert d.stdout == "hello"
        assert d.stderr == "world"
        assert d.mode == "raw"
        assert d.was_redacted is False
        assert d.was_truncated is False

    def test_to_dict_contains_mode_flags(self):
        from assistant_os.output.persistence_policy import PersistenceDecision
        d = PersistenceDecision(
            stdout="x", stderr="y", mode="redacted",
            was_redacted=True, was_truncated=False,
        )
        result = d.to_dict()
        assert result["mode"] == "redacted"
        assert result["was_redacted"] is True
        assert result["was_truncated"] is False

    def test_to_dict_does_not_include_streams(self):
        """to_dict() must not expose output content."""
        from assistant_os.output.persistence_policy import PersistenceDecision
        d = PersistenceDecision(
            stdout="secret_value", stderr="another_secret",
            mode="redacted", was_redacted=True, was_truncated=False,
        )
        result = d.to_dict()
        assert "stdout" not in result
        assert "stderr" not in result
        assert "secret_value" not in str(result)
        assert "another_secret" not in str(result)

    def test_frozen(self):
        from assistant_os.output.persistence_policy import PersistenceDecision
        d = PersistenceDecision(
            stdout="x", stderr="y", mode="raw",
            was_redacted=False, was_truncated=False,
        )
        with pytest.raises((AttributeError, TypeError)):
            d.stdout = "mutated"  # type: ignore[misc]


# ===========================================================================
# B — TestDecidePersistenceSafe
# ===========================================================================

class TestDecidePersistenceSafe:
    def _make_safe_inspection(self, stdout="hello", stderr="world"):
        from assistant_os.output.models import InspectionResult
        return InspectionResult(
            classification="safe",
            flags=[],
            inspected_at=time.time(),
            stdout_redacted=stdout,
            stderr_redacted=stderr,
        )

    def test_safe_mode_is_raw(self):
        from assistant_os.output.persistence_policy import decide_persistence, PERSIST_MODE_RAW
        insp = self._make_safe_inspection()
        d = decide_persistence("hello", "world", insp)
        assert d.mode == PERSIST_MODE_RAW

    def test_safe_streams_unchanged(self):
        from assistant_os.output.persistence_policy import decide_persistence
        insp = self._make_safe_inspection()
        d = decide_persistence("hello", "world", insp)
        assert d.stdout == "hello"
        assert d.stderr == "world"

    def test_safe_not_redacted(self):
        from assistant_os.output.persistence_policy import decide_persistence
        insp = self._make_safe_inspection()
        d = decide_persistence("hello", "world", insp)
        assert d.was_redacted is False
        assert d.was_truncated is False


# ===========================================================================
# C — TestDecidePersistenceWarning
# ===========================================================================

class TestDecidePersistenceWarning:
    def _make_warning_inspection(self, stdout="/etc/passwd was found", stderr=""):
        from assistant_os.output.models import InspectionResult, OutputFlag
        return InspectionResult(
            classification="warning",
            flags=[OutputFlag(flag_type="absolute_path", detail="Unix path", stream="stdout")],
            inspected_at=time.time(),
            stdout_redacted=stdout,
            stderr_redacted=stderr,
        )

    def test_warning_mode_is_raw(self):
        from assistant_os.output.persistence_policy import decide_persistence, PERSIST_MODE_RAW
        insp = self._make_warning_inspection()
        d = decide_persistence("/etc/passwd was found", "", insp)
        assert d.mode == PERSIST_MODE_RAW

    def test_warning_streams_unchanged(self):
        from assistant_os.output.persistence_policy import decide_persistence
        raw_stdout = "/etc/passwd was found"
        insp = self._make_warning_inspection(stdout=raw_stdout)
        d = decide_persistence(raw_stdout, "", insp)
        assert d.stdout == raw_stdout

    def test_warning_not_redacted(self):
        from assistant_os.output.persistence_policy import decide_persistence
        insp = self._make_warning_inspection()
        d = decide_persistence("/etc/passwd was found", "", insp)
        assert d.was_redacted is False
        assert d.was_truncated is False


# ===========================================================================
# D — TestDecidePersistenceSensitive
# ===========================================================================

class TestDecidePersistenceSensitive:
    def _make_sensitive_inspection(self, raw_stdout, raw_stderr=""):
        from assistant_os.output.inspector import OutputInspector
        return OutputInspector().inspect(raw_stdout, raw_stderr)

    def test_sensitive_mode_is_redacted(self):
        from assistant_os.output.persistence_policy import decide_persistence, PERSIST_MODE_REDACTED
        raw = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        insp = self._make_sensitive_inspection(raw)
        assert insp.classification == "sensitive"
        d = decide_persistence(raw, "", insp)
        assert d.mode == PERSIST_MODE_REDACTED

    def test_sensitive_was_redacted_true(self):
        from assistant_os.output.persistence_policy import decide_persistence
        raw = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        insp = self._make_sensitive_inspection(raw)
        d = decide_persistence(raw, "", insp)
        assert d.was_redacted is True

    def test_sensitive_secret_not_in_persisted_stdout(self):
        from assistant_os.output.persistence_policy import decide_persistence
        raw = "token: sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        insp = self._make_sensitive_inspection(raw)
        d = decide_persistence(raw, "", insp)
        # The secret value must not appear in the persisted stream
        assert "sk-ant-api03" not in d.stdout

    def test_sensitive_redacted_marker_present(self):
        from assistant_os.output.persistence_policy import decide_persistence
        raw = "token: sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        insp = self._make_sensitive_inspection(raw)
        d = decide_persistence(raw, "", insp)
        assert "[REDACTED]" in d.stdout

    def test_sensitive_stderr_also_redacted(self):
        from assistant_os.output.persistence_policy import decide_persistence
        raw_stderr = "error: api_key=sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        from assistant_os.output.inspector import OutputInspector
        insp = OutputInspector().inspect("", raw_stderr)
        assert insp.classification == "sensitive"
        d = decide_persistence("", raw_stderr, insp)
        assert "sk-ant-api03" not in d.stderr
        assert "[REDACTED]" in d.stderr

    def test_sensitive_was_truncated_false(self):
        from assistant_os.output.persistence_policy import decide_persistence
        raw = "key=sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        insp = self._make_sensitive_inspection(raw)
        d = decide_persistence(raw, "", insp)
        assert d.was_truncated is False


# ===========================================================================
# E — TestDecidePersistenceInvalid
# ===========================================================================

class TestDecidePersistenceInvalid:
    def _make_invalid_inspection(self, raw_stdout):
        from assistant_os.output.models import InspectionResult, OutputFlag
        # Binary data: redacted form is same as raw for non-sensitive binary
        return InspectionResult(
            classification="invalid",
            flags=[OutputFlag(flag_type="binary_content", detail="binary detected", stream="stdout")],
            inspected_at=time.time(),
            stdout_redacted=raw_stdout,
            stderr_redacted="",
        )

    def test_invalid_mode_is_truncated(self):
        from assistant_os.output.persistence_policy import decide_persistence, PERSIST_MODE_TRUNCATED
        raw = "x" * 5000
        insp = self._make_invalid_inspection(raw)
        d = decide_persistence(raw, "", insp)
        assert d.mode == PERSIST_MODE_TRUNCATED

    def test_invalid_output_capped_at_2048(self):
        from assistant_os.output.persistence_policy import decide_persistence, _TRUNCATION_LIMIT
        raw = "a" * 5000
        insp = self._make_invalid_inspection(raw)
        d = decide_persistence(raw, "", insp)
        assert len(d.stdout) <= _TRUNCATION_LIMIT

    def test_invalid_short_output_not_truncated_flag(self):
        from assistant_os.output.persistence_policy import decide_persistence
        raw = "x" * 100  # Well under 2048
        insp = self._make_invalid_inspection(raw)
        d = decide_persistence(raw, "", insp)
        assert d.was_truncated is False

    def test_invalid_long_output_truncated_flag(self):
        from assistant_os.output.persistence_policy import decide_persistence
        raw = "x" * 5000  # Over 2048
        insp = self._make_invalid_inspection(raw)
        d = decide_persistence(raw, "", insp)
        assert d.was_truncated is True

    def test_invalid_was_redacted_true(self):
        from assistant_os.output.persistence_policy import decide_persistence
        raw = "garbage"
        insp = self._make_invalid_inspection(raw)
        d = decide_persistence(raw, "", insp)
        # invalid always sets was_redacted=True (redaction applied before truncation)
        assert d.was_redacted is True


# ===========================================================================
# F — TestDecidePersistenceNone
# ===========================================================================

class TestDecidePersistenceNone:
    def test_none_inspection_raw_mode(self):
        from assistant_os.output.persistence_policy import decide_persistence, PERSIST_MODE_RAW
        d = decide_persistence("hello", "world", None)
        assert d.mode == PERSIST_MODE_RAW

    def test_none_inspection_streams_unchanged(self):
        from assistant_os.output.persistence_policy import decide_persistence
        d = decide_persistence("hello", "world", None)
        assert d.stdout == "hello"
        assert d.stderr == "world"

    def test_none_inspection_not_redacted(self):
        from assistant_os.output.persistence_policy import decide_persistence
        d = decide_persistence("hello", "world", None)
        assert d.was_redacted is False
        assert d.was_truncated is False


# ===========================================================================
# G — TestDecidePersistenceUnknown
# ===========================================================================

class TestDecidePersistenceUnknown:
    def test_unknown_classification_raw_fallback(self):
        """Unknown classification → raw mode (future-proofing)."""
        from assistant_os.output.persistence_policy import decide_persistence, PERSIST_MODE_RAW
        from assistant_os.output.models import InspectionResult
        insp = InspectionResult(
            classification="unknown_future_value",
            flags=[],
            inspected_at=time.time(),
            stdout_redacted="hello",
            stderr_redacted="world",
        )
        d = decide_persistence("hello", "world", insp)
        assert d.mode == PERSIST_MODE_RAW
        assert d.stdout == "hello"
        assert d.stderr == "world"


# ===========================================================================
# H — TestNoBypass
# ===========================================================================

class TestNoBypass:
    def test_sensitive_output_not_in_to_dict_stdout(self):
        """ExecutionResult.to_dict()['stdout'] must not contain raw secret after policy."""
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.output.persistence_policy import decide_persistence
        from assistant_os.output.inspector import OutputInspector

        raw = "key: sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        insp = OutputInspector().inspect(raw, "")

        result = ExecutionResult(
            exit_code=0, stdout=raw, stderr="", duration_ms=100, truncated=False,
        )
        decision = decide_persistence(raw, "", insp)
        result.persisted_stdout = decision.stdout
        result.persisted_stderr = decision.stderr
        result.persistence_mode = decision.mode
        result.was_redacted = decision.was_redacted

        d = result.to_dict()
        assert "sk-ant-api03" not in d["stdout"]
        assert "[REDACTED]" in d["stdout"]

    def test_to_dict_exposes_persistence_mode(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        result = ExecutionResult(
            exit_code=0, stdout="safe output", stderr="", duration_ms=50, truncated=False,
        )
        d = result.to_dict()
        assert "persistence_mode" in d
        assert d["persistence_mode"] == "raw"

    def test_to_dict_exposes_was_redacted(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        result = ExecutionResult(
            exit_code=0, stdout="safe", stderr="", duration_ms=10, truncated=False,
            was_redacted=True,
        )
        d = result.to_dict()
        assert "was_redacted" in d
        assert d["was_redacted"] is True


# ===========================================================================
# I — TestRunnerAPIPersistence
# ===========================================================================

class TestRunnerAPIPersistence:
    def _make_minimal_result(self, stdout="safe output", stderr=""):
        from assistant_os.sandbox.execution_result import ExecutionResult
        return ExecutionResult(
            exit_code=0, stdout=stdout, stderr=stderr,
            duration_ms=100, truncated=False,
        )

    def test_apply_persistence_policy_sets_persisted_stdout(self):
        from assistant_os.sandbox.runner_api import _apply_persistence_policy
        result = self._make_minimal_result("hello world")
        _apply_persistence_policy(result, None, "exec-1", "plan-1")
        assert result.persisted_stdout is not None

    def test_apply_persistence_policy_safe_raw_mode(self):
        from assistant_os.sandbox.runner_api import _apply_persistence_policy
        from assistant_os.output.models import InspectionResult
        result = self._make_minimal_result("safe output")
        result.inspection_result = InspectionResult(
            classification="safe", flags=[], inspected_at=time.time(),
            stdout_redacted="safe output", stderr_redacted="",
        )
        _apply_persistence_policy(result, None, "exec-1", "plan-1")
        assert result.persistence_mode == "raw"
        assert result.was_redacted is False
        assert result.persisted_stdout == "safe output"

    def test_apply_persistence_policy_sensitive_redacted(self):
        from assistant_os.sandbox.runner_api import _apply_persistence_policy
        from assistant_os.output.inspector import OutputInspector
        raw = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        result = self._make_minimal_result(stdout=raw)
        result.inspection_result = OutputInspector().inspect(raw, "")
        assert result.inspection_result.classification == "sensitive"

        _apply_persistence_policy(result, None, "exec-1", "plan-1")
        assert result.persistence_mode == "redacted"
        assert result.was_redacted is True
        assert "sk-ant-api03" not in (result.persisted_stdout or "")

    def test_apply_persistence_policy_emits_audit_for_sensitive(self):
        from assistant_os.sandbox.runner_api import _apply_persistence_policy
        from assistant_os.sandbox.audit import AuditLog, AuditEventType
        from assistant_os.output.inspector import OutputInspector
        raw = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        result = self._make_minimal_result(stdout=raw)
        result.inspection_result = OutputInspector().inspect(raw, "")

        audit = AuditLog()
        _apply_persistence_policy(result, audit, "exec-42", "plan-1")

        events = audit.events(AuditEventType.OUTPUT_REDACTED)
        assert len(events) == 1
        ev = events[0]
        assert ev.execution_id == "exec-42"
        assert ev.persistence_mode == "redacted"
        assert ev.was_redacted is True

    def test_apply_persistence_policy_no_audit_for_safe(self):
        from assistant_os.sandbox.runner_api import _apply_persistence_policy
        from assistant_os.sandbox.audit import AuditLog, AuditEventType
        from assistant_os.output.models import InspectionResult
        result = self._make_minimal_result("safe output")
        result.inspection_result = InspectionResult(
            classification="safe", flags=[], inspected_at=time.time(),
            stdout_redacted="safe output", stderr_redacted="",
        )
        audit = AuditLog()
        _apply_persistence_policy(result, audit, "exec-1", "plan-1")
        assert audit.count(AuditEventType.OUTPUT_REDACTED) == 0

    def test_apply_persistence_policy_no_audit_for_warning(self):
        from assistant_os.sandbox.runner_api import _apply_persistence_policy
        from assistant_os.sandbox.audit import AuditLog, AuditEventType
        from assistant_os.output.models import InspectionResult, OutputFlag
        result = self._make_minimal_result("/etc/passwd listed")
        result.inspection_result = InspectionResult(
            classification="warning",
            flags=[OutputFlag(flag_type="absolute_path", detail="path", stream="stdout")],
            inspected_at=time.time(),
            stdout_redacted="/etc/passwd listed",
            stderr_redacted="",
        )
        audit = AuditLog()
        _apply_persistence_policy(result, audit, "exec-1", "plan-1")
        assert audit.count(AuditEventType.OUTPUT_REDACTED) == 0

    def test_apply_persistence_policy_never_raises(self):
        """Policy failures must never surface to callers."""
        from assistant_os.sandbox.runner_api import _apply_persistence_policy
        from assistant_os.sandbox.execution_result import ExecutionResult
        result = ExecutionResult(
            exit_code=0, stdout=None, stderr=None,  # type: ignore[arg-type]
            duration_ms=0, truncated=False,
        )
        # Should not raise even with None streams
        _apply_persistence_policy(result, None, "", "")


# ===========================================================================
# J — TestOutputRedactedAuditEvent
# ===========================================================================

class TestOutputRedactedAuditEvent:
    def test_event_construction(self):
        from assistant_os.sandbox.audit import OutputRedactedEvent, AuditEventType
        ev = OutputRedactedEvent(
            event_type=AuditEventType.OUTPUT_REDACTED,
            execution_id="exec-1",
            plan_id="plan-1",
            timestamp=1234567890.0,
            persistence_mode="redacted",
            was_redacted=True,
            was_truncated=False,
            original_stdout_bytes=500,
            persisted_stdout_bytes=200,
        )
        assert ev.event_type == "output_redacted"
        assert ev.persistence_mode == "redacted"
        assert ev.was_redacted is True

    def test_event_type_constant(self):
        from assistant_os.sandbox.audit import AuditEventType
        assert AuditEventType.OUTPUT_REDACTED == "output_redacted"

    def test_to_dict_fields(self):
        from assistant_os.sandbox.audit import OutputRedactedEvent, AuditEventType
        ev = OutputRedactedEvent(
            event_type=AuditEventType.OUTPUT_REDACTED,
            execution_id="exec-1",
            plan_id="plan-1",
            timestamp=1234567890.0,
            persistence_mode="truncated",
            was_redacted=True,
            was_truncated=True,
            original_stdout_bytes=9000,
            persisted_stdout_bytes=2048,
        )
        d = ev.to_dict()
        assert d["event_type"] == "output_redacted"
        assert d["persistence_mode"] == "truncated"
        assert d["was_truncated"] is True
        assert d["original_stdout_bytes"] == 9000
        assert d["persisted_stdout_bytes"] == 2048

    def test_audit_log_records_redacted_event(self):
        from assistant_os.sandbox.audit import AuditLog, AuditEventType, OutputRedactedEvent
        log = AuditLog()
        ev = OutputRedactedEvent(
            event_type=AuditEventType.OUTPUT_REDACTED,
            execution_id="exec-99",
            plan_id="plan-1",
            timestamp=time.time(),
            persistence_mode="redacted",
            was_redacted=True,
            was_truncated=False,
        )
        log.emit(ev)
        events = log.events(AuditEventType.OUTPUT_REDACTED)
        assert len(events) == 1
        assert events[0].execution_id == "exec-99"


# ===========================================================================
# K — TestNoLeakageInAuditEvent
# ===========================================================================

class TestNoLeakageInAuditEvent:
    def test_redacted_event_no_output_content(self):
        """OutputRedactedEvent.to_dict() must never include output content."""
        from assistant_os.sandbox.audit import OutputRedactedEvent, AuditEventType
        secret = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        ev = OutputRedactedEvent(
            event_type=AuditEventType.OUTPUT_REDACTED,
            execution_id="exec-1",
            plan_id="plan-1",
            timestamp=time.time(),
            persistence_mode="redacted",
            was_redacted=True,
            was_truncated=False,
        )
        d = ev.to_dict()
        dumped = str(d)
        assert secret not in dumped
        assert "stdout" not in d
        assert "stderr" not in d

    def test_runner_api_audit_event_no_output_content(self):
        """The audit event emitted by _apply_persistence_policy contains no output."""
        from assistant_os.sandbox.runner_api import _apply_persistence_policy
        from assistant_os.sandbox.audit import AuditLog, AuditEventType
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.output.inspector import OutputInspector

        secret = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghij"
        result = ExecutionResult(
            exit_code=0, stdout=f"output: {secret}", stderr="",
            duration_ms=100, truncated=False,
        )
        result.inspection_result = OutputInspector().inspect(result.stdout, "")
        audit = AuditLog()
        _apply_persistence_policy(result, audit, "exec-1", "plan-1")

        events = audit.events(AuditEventType.OUTPUT_REDACTED)
        assert len(events) == 1
        ev_dict = events[0].to_dict()
        dumped = str(ev_dict)
        assert secret not in dumped
        assert "[REDACTED]" not in dumped  # redacted content not in event either


# ===========================================================================
# L — TestExecutionResultToDict
# ===========================================================================

class TestExecutionResultToDict:
    def test_to_dict_stdout_uses_persisted_when_set(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        result = ExecutionResult(
            exit_code=0, stdout="raw secret", stderr="", duration_ms=10, truncated=False,
            persisted_stdout="[REDACTED] safe version",
            persisted_stderr="",
            persistence_mode="redacted",
            was_redacted=True,
        )
        d = result.to_dict()
        assert d["stdout"] == "[REDACTED] safe version"
        assert "raw secret" not in d["stdout"]

    def test_to_dict_stdout_falls_back_to_raw_when_persisted_none(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        result = ExecutionResult(
            exit_code=0, stdout="safe output", stderr="", duration_ms=10, truncated=False,
        )
        d = result.to_dict()
        assert d["stdout"] == "safe output"

    def test_to_dict_includes_persistence_mode(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        result = ExecutionResult(
            exit_code=0, stdout="x", stderr="", duration_ms=0, truncated=False,
            persistence_mode="redacted",
        )
        d = result.to_dict()
        assert d["persistence_mode"] == "redacted"

    def test_to_dict_includes_was_redacted(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        result = ExecutionResult(
            exit_code=0, stdout="x", stderr="", duration_ms=0, truncated=False,
            was_redacted=True,
        )
        d = result.to_dict()
        assert d["was_redacted"] is True

    def test_to_dict_default_persistence_mode_raw(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        result = ExecutionResult(
            exit_code=0, stdout="safe", stderr="", duration_ms=0, truncated=False,
        )
        d = result.to_dict()
        assert d["persistence_mode"] == "raw"
        assert d["was_redacted"] is False

    def test_to_dict_safe_output_unchanged(self):
        """Safe output must reach to_dict() exactly as produced."""
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.sandbox.runner_api import _apply_output_inspection, _apply_persistence_policy
        from assistant_os.sandbox.audit import AuditLog

        result = ExecutionResult(
            exit_code=0, stdout="print('hello world')\nhello world\n",
            stderr="", duration_ms=100, truncated=False,
        )
        audit = AuditLog()
        _apply_output_inspection(result, audit, "exec-1", "plan-1")
        _apply_persistence_policy(result, audit, "exec-1", "plan-1")

        d = result.to_dict()
        assert d["stdout"] == "print('hello world')\nhello world\n"
        assert d["persistence_mode"] == "raw"


# ===========================================================================
# M — TestPersistencePolicyExports
# ===========================================================================

class TestPersistencePolicyExports:
    def test_persistence_decision_importable(self):
        from assistant_os.output import PersistenceDecision
        assert PersistenceDecision is not None

    def test_decide_persistence_importable(self):
        from assistant_os.output import decide_persistence
        assert callable(decide_persistence)

    def test_persist_mode_constants_importable(self):
        from assistant_os.output import PERSIST_MODE_RAW, PERSIST_MODE_REDACTED, PERSIST_MODE_TRUNCATED
        assert PERSIST_MODE_RAW == "raw"
        assert PERSIST_MODE_REDACTED == "redacted"
        assert PERSIST_MODE_TRUNCATED == "truncated"

    def test_output_redacted_event_importable(self):
        from assistant_os.sandbox.audit import OutputRedactedEvent, AuditEventType
        assert AuditEventType.OUTPUT_REDACTED == "output_redacted"
        assert OutputRedactedEvent is not None
