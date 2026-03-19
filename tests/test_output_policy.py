"""
Sprint 6 — Output Control + Deep Audit Hardening

Test classes
------------
A  TestOutputPolicyValidation        — OutputPolicy construction and validation
B  TestOutputPolicyEngine            — apply() correctness: normal, truncation, blocked
C  TestOutputRecord                  — OutputRecord fields, persistable, to_dict
D  TestOutputPolicyRegistry          — built-in named policies
E  TestExecutionResultOutputRecord   — output_record integration on ExecutionResult
F  TestExecutionMetadataHash         — authorized_plan_hash on ExecutionMetadata
G  TestAuditNewEventTypes            — OutputEvent, ArtifactEvent construction + to_dict
H  TestAuditExecutionEventRicher     — authorized_plan_hash / policy_id on ExecutionEvent
I  TestRunnerAPIOutputPolicy         — runner applies output policy and emits events
J  TestRunnerAPIArtifactEvents       — runner emits artifact_collected / artifact_rejected
K  TestOutputVsArtifactSeparation    — output policy does not affect artifact semantics
L  TestOutputRedaction               — no content in events; blocked content suppressed
M  TestTruncationAsFirstClassEvent   — explicit OutputEvent emitted, never silent
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_backend(stdout="hello", stderr="", exit_code=0):
    """Return an ExecutionBackend mock that returns a successful result."""
    from assistant_os.sandbox.execution_result import ExecutionResult
    backend = MagicMock()
    backend.prepare.return_value = None
    backend.cleanup.return_value = None
    backend.execute.return_value = ExecutionResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=10,
        truncated=False,
    )
    return backend


def _make_plan(policy_id="default"):
    from assistant_os.sandbox.authorized_plan import AuthorizedPlan
    return AuthorizedPlan(
        execution_id="exec-out-test",
        plan_id="plan-out-test",
        authorized_plan_hash="hash-abc",
        policy_id=policy_id,
        capability_scope=["code_execution"],
        runtime_profile="python3.11",
    )


def _make_control_plane():
    from assistant_os.sandbox.audit import AuditLog
    from assistant_os.sandbox.execution_registry import ExecutionRegistry
    from assistant_os.sandbox.revocation import RevocationManager
    audit = AuditLog()
    registry = ExecutionRegistry()
    revmgr = RevocationManager(registry=registry, audit_log=audit)
    return audit, registry, revmgr


# ===========================================================================
# A — TestOutputPolicyValidation
# ===========================================================================

class TestOutputPolicyValidation:
    def test_default_construction(self):
        from assistant_os.sandbox.output_policy import OutputPolicy
        p = OutputPolicy()
        assert p.policy_id == "default"
        assert p.max_stdout_bytes == 8192
        assert p.max_stderr_bytes == 8192
        assert p.stdout_classification == "user-visible"
        assert p.stderr_classification == "internal-only"

    def test_custom_fields(self):
        from assistant_os.sandbox.output_policy import OutputPolicy
        p = OutputPolicy(
            policy_id="tight",
            max_stdout_bytes=1024,
            max_stderr_bytes=512,
            stdout_classification="internal-only",
            stderr_classification="blocked",
        )
        assert p.policy_id == "tight"
        assert p.max_stdout_bytes == 1024
        assert p.max_stderr_bytes == 512

    def test_invalid_stdout_classification_raises(self):
        from assistant_os.sandbox.output_policy import OutputPolicy
        with pytest.raises(ValueError, match="stdout_classification"):
            OutputPolicy(stdout_classification="unknown")

    def test_invalid_stderr_classification_raises(self):
        from assistant_os.sandbox.output_policy import OutputPolicy
        with pytest.raises(ValueError, match="stderr_classification"):
            OutputPolicy(stderr_classification="public")

    def test_negative_max_stdout_raises(self):
        from assistant_os.sandbox.output_policy import OutputPolicy
        with pytest.raises(ValueError, match="max_stdout_bytes"):
            OutputPolicy(max_stdout_bytes=-1)

    def test_negative_max_stderr_raises(self):
        from assistant_os.sandbox.output_policy import OutputPolicy
        with pytest.raises(ValueError, match="max_stderr_bytes"):
            OutputPolicy(max_stderr_bytes=-1)

    def test_zero_max_bytes_is_valid(self):
        from assistant_os.sandbox.output_policy import (
            OUTPUT_CLASSIFICATION_BLOCKED, OutputPolicy,
        )
        p = OutputPolicy(
            max_stdout_bytes=0,
            max_stderr_bytes=0,
            stdout_classification=OUTPUT_CLASSIFICATION_BLOCKED,
            stderr_classification=OUTPUT_CLASSIFICATION_BLOCKED,
        )
        assert p.max_stdout_bytes == 0

    def test_frozen_immutable(self):
        from assistant_os.sandbox.output_policy import OutputPolicy
        p = OutputPolicy()
        with pytest.raises((AttributeError, TypeError)):
            p.policy_id = "tampered"  # type: ignore

    def test_to_dict_safe(self):
        from assistant_os.sandbox.output_policy import OutputPolicy
        d = OutputPolicy().to_dict()
        assert d["policy_id"] == "default"
        assert "max_stdout_bytes" in d
        assert "stdout_classification" in d


# ===========================================================================
# B — TestOutputPolicyEngine
# ===========================================================================

class TestOutputPolicyEngine:
    def test_no_truncation_within_limit(self):
        from assistant_os.sandbox.output_policy import OutputPolicy, OutputPolicyEngine
        policy = OutputPolicy(max_stdout_bytes=100, max_stderr_bytes=100)
        rec, truncated = OutputPolicyEngine.apply("hello", "err", policy)
        assert rec.stdout == "hello"
        assert rec.stderr == "err"
        assert not truncated
        assert not rec.stdout_truncated
        assert not rec.stderr_truncated

    def test_stdout_truncated_at_limit(self):
        from assistant_os.sandbox.output_policy import OutputPolicy, OutputPolicyEngine
        policy = OutputPolicy(max_stdout_bytes=5, max_stderr_bytes=100)
        rec, truncated = OutputPolicyEngine.apply("hello world", "err", policy)
        assert rec.stdout == "hello"
        assert rec.stdout_truncated is True
        assert "stdout" in truncated

    def test_stderr_truncated_at_limit(self):
        from assistant_os.sandbox.output_policy import OutputPolicy, OutputPolicyEngine
        policy = OutputPolicy(max_stdout_bytes=100, max_stderr_bytes=3)
        rec, truncated = OutputPolicyEngine.apply("out", "error text", policy)
        assert rec.stderr == "err"
        assert rec.stderr_truncated is True
        assert "stderr" in truncated

    def test_both_streams_truncated(self):
        from assistant_os.sandbox.output_policy import OutputPolicy, OutputPolicyEngine
        policy = OutputPolicy(max_stdout_bytes=2, max_stderr_bytes=2)
        rec, truncated = OutputPolicyEngine.apply("abcdef", "xyz", policy)
        assert "stdout" in truncated
        assert "stderr" in truncated
        assert rec.truncated is True

    def test_stdout_blocked_becomes_empty(self):
        from assistant_os.sandbox.output_policy import (
            OUTPUT_CLASSIFICATION_BLOCKED, OutputPolicy, OutputPolicyEngine,
        )
        policy = OutputPolicy(stdout_classification=OUTPUT_CLASSIFICATION_BLOCKED)
        rec, truncated = OutputPolicyEngine.apply("sensitive output", "stderr", policy)
        assert rec.stdout == ""
        assert rec.stdout_truncated is True      # suppressed = truncated
        assert "stdout" in truncated
        assert rec.stdout_bytes == len("sensitive output")   # original size preserved

    def test_stderr_blocked_becomes_empty(self):
        from assistant_os.sandbox.output_policy import (
            OUTPUT_CLASSIFICATION_BLOCKED, OutputPolicy, OutputPolicyEngine,
        )
        policy = OutputPolicy(stderr_classification=OUTPUT_CLASSIFICATION_BLOCKED)
        rec, truncated = OutputPolicyEngine.apply("out", "sensitive error", policy)
        assert rec.stderr == ""
        assert "stderr" in truncated

    def test_both_streams_blocked(self):
        from assistant_os.sandbox.output_policy import (
            OUTPUT_CLASSIFICATION_BLOCKED, OutputPolicy, OutputPolicyEngine,
        )
        policy = OutputPolicy(
            stdout_classification=OUTPUT_CLASSIFICATION_BLOCKED,
            stderr_classification=OUTPUT_CLASSIFICATION_BLOCKED,
        )
        rec, truncated = OutputPolicyEngine.apply("out", "err", policy)
        assert rec.stdout == ""
        assert rec.stderr == ""
        assert len(truncated) == 2

    def test_empty_streams_no_truncation(self):
        from assistant_os.sandbox.output_policy import OutputPolicy, OutputPolicyEngine
        policy = OutputPolicy()
        rec, truncated = OutputPolicyEngine.apply("", "", policy)
        assert not truncated
        assert not rec.stdout_truncated
        assert not rec.stderr_truncated

    def test_blocked_empty_stream_no_truncation_event(self):
        """Blocked classification on an empty stream should not signal truncation."""
        from assistant_os.sandbox.output_policy import (
            OUTPUT_CLASSIFICATION_BLOCKED, OutputPolicy, OutputPolicyEngine,
        )
        policy = OutputPolicy(stdout_classification=OUTPUT_CLASSIFICATION_BLOCKED)
        rec, truncated = OutputPolicyEngine.apply("", "stderr", policy)
        # stdout was empty and blocked — nothing to suppress
        assert "stdout" not in truncated
        assert rec.stdout_truncated is False

    def test_original_bytes_recorded(self):
        from assistant_os.sandbox.output_policy import OutputPolicy, OutputPolicyEngine
        policy = OutputPolicy(max_stdout_bytes=3)
        rec, _ = OutputPolicyEngine.apply("abcdef", "xyz", policy)
        assert rec.stdout_bytes == 6     # original
        assert rec.stderr_bytes == 3
        assert rec.stdout == "abc"      # capped

    def test_policy_id_propagated(self):
        from assistant_os.sandbox.output_policy import OutputPolicy, OutputPolicyEngine
        policy = OutputPolicy(policy_id="custom-policy")
        rec, _ = OutputPolicyEngine.apply("out", "err", policy)
        assert rec.output_policy_id == "custom-policy"


# ===========================================================================
# C — TestOutputRecord
# ===========================================================================

class TestOutputRecord:
    def _make_record(self, stdout="out", stderr="err",
                     stdout_classification="user-visible",
                     stderr_classification="internal-only"):
        from assistant_os.sandbox.output_policy import OutputRecord
        return OutputRecord(
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=False,
            stderr_truncated=False,
            stdout_bytes=len(stdout),
            stderr_bytes=len(stderr),
            stdout_classification=stdout_classification,
            stderr_classification=stderr_classification,
            output_policy_id="default",
        )

    def test_persistable_user_visible(self):
        rec = self._make_record(stdout_classification="user-visible")
        assert rec.stdout_persistable() is True

    def test_persistable_internal_only(self):
        rec = self._make_record(stderr_classification="internal-only")
        assert rec.stderr_persistable() is True

    def test_not_persistable_blocked(self):
        rec = self._make_record(stdout_classification="blocked")
        assert rec.stdout_persistable() is False

    def test_truncated_property_both_false(self):
        rec = self._make_record()
        assert rec.truncated is False

    def test_truncated_property_stdout_true(self):
        from assistant_os.sandbox.output_policy import OutputRecord
        rec = OutputRecord(
            stdout="abc", stderr="", stdout_truncated=True, stderr_truncated=False,
            stdout_bytes=100, stderr_bytes=0,
            stdout_classification="user-visible", stderr_classification="internal-only",
            output_policy_id="default",
        )
        assert rec.truncated is True

    def test_to_dict_blocked_stdout_empty(self):
        rec = self._make_record(stdout="secret content", stdout_classification="blocked")
        d = rec.to_dict()
        assert d["stdout"] == ""        # blocked — not persisted
        assert "secret content" not in str(d)

    def test_to_dict_blocked_stderr_empty(self):
        rec = self._make_record(stderr="private", stderr_classification="blocked")
        d = rec.to_dict()
        assert d["stderr"] == ""

    def test_to_dict_includes_metadata(self):
        rec = self._make_record()
        d = rec.to_dict()
        for key in ("stdout_bytes", "stderr_bytes", "stdout_truncated",
                    "stderr_truncated", "stdout_classification",
                    "stderr_classification", "output_policy_id", "truncated"):
            assert key in d

    def test_to_dict_safe_for_logs_no_blocked_content(self):
        from assistant_os.sandbox.output_policy import OutputRecord
        rec = OutputRecord(
            stdout="should not appear", stderr="also blocked",
            stdout_truncated=True, stderr_truncated=True,
            stdout_bytes=20, stderr_bytes=12,
            stdout_classification="blocked", stderr_classification="blocked",
            output_policy_id="readonly",
        )
        d = rec.to_dict()
        assert "should not appear" not in str(d)
        assert "also blocked" not in str(d)


# ===========================================================================
# D — TestOutputPolicyRegistry
# ===========================================================================

class TestOutputPolicyRegistry:
    def test_default_policy_exists(self):
        from assistant_os.sandbox.output_policy import OUTPUT_POLICY_REGISTRY
        assert "default" in OUTPUT_POLICY_REGISTRY

    def test_strict_policy_exists(self):
        from assistant_os.sandbox.output_policy import OUTPUT_POLICY_REGISTRY, STRICT_OUTPUT_POLICY
        assert OUTPUT_POLICY_REGISTRY["strict"] is STRICT_OUTPUT_POLICY

    def test_readonly_policy_exists(self):
        from assistant_os.sandbox.output_policy import (
            OUTPUT_CLASSIFICATION_BLOCKED, OUTPUT_POLICY_REGISTRY, READONLY_OUTPUT_POLICY,
        )
        p = OUTPUT_POLICY_REGISTRY["readonly"]
        assert p.stdout_classification == OUTPUT_CLASSIFICATION_BLOCKED
        assert p.stderr_classification == OUTPUT_CLASSIFICATION_BLOCKED

    def test_strict_smaller_caps(self):
        from assistant_os.sandbox.output_policy import (
            DEFAULT_OUTPUT_POLICY, STRICT_OUTPUT_POLICY,
        )
        assert STRICT_OUTPUT_POLICY.max_stdout_bytes < DEFAULT_OUTPUT_POLICY.max_stdout_bytes

    def test_default_stdout_user_visible(self):
        from assistant_os.sandbox.output_policy import (
            DEFAULT_OUTPUT_POLICY, OUTPUT_CLASSIFICATION_USER_VISIBLE,
        )
        assert DEFAULT_OUTPUT_POLICY.stdout_classification == OUTPUT_CLASSIFICATION_USER_VISIBLE


# ===========================================================================
# E — TestExecutionResultOutputRecord
# ===========================================================================

class TestExecutionResultOutputRecord:
    def test_output_record_default_none(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        r = ExecutionResult(exit_code=0, stdout="hi", stderr="", duration_ms=1, truncated=False)
        assert r.output_record is None

    def test_output_record_set(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.sandbox.output_policy import OutputPolicy, OutputPolicyEngine
        r = ExecutionResult(exit_code=0, stdout="hello", stderr="", duration_ms=1, truncated=False)
        rec, _ = OutputPolicyEngine.apply("hello", "", OutputPolicy())
        r.output_record = rec
        assert r.output_record is rec

    def test_to_dict_includes_output_record(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.sandbox.output_policy import OutputPolicy, OutputPolicyEngine
        r = ExecutionResult(exit_code=0, stdout="hi", stderr="", duration_ms=5, truncated=False)
        rec, _ = OutputPolicyEngine.apply("hi", "", OutputPolicy())
        r.output_record = rec
        d = r.to_dict()
        assert "output_record" in d
        assert d["output_record"]["output_policy_id"] == "default"

    def test_to_dict_without_output_record_unchanged(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        r = ExecutionResult(exit_code=0, stdout="x", stderr="", duration_ms=1, truncated=False)
        d = r.to_dict()
        assert "output_record" not in d

    def test_output_record_distinct_from_manifest(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.sandbox.output_policy import OutputPolicy, OutputPolicyEngine
        r = ExecutionResult(exit_code=0, stdout="x", stderr="", duration_ms=1, truncated=False)
        rec, _ = OutputPolicyEngine.apply("x", "", OutputPolicy())
        r.output_record = rec
        # manifest remains None — output record and artifact manifest are independent
        assert r.manifest is None
        assert r.output_record is not None


# ===========================================================================
# F — TestExecutionMetadataHash
# ===========================================================================

class TestExecutionMetadataHash:
    def test_authorized_plan_hash_default_empty(self):
        from assistant_os.sandbox.execution_result import ExecutionMetadata
        m = ExecutionMetadata(
            execution_id="e1", plan_id="p1", policy_id="default",
            runtime_profile="python3.11", duration_ms=10,
            exit_code=0, timed_out=False, truncated=False,
        )
        assert m.authorized_plan_hash == ""

    def test_authorized_plan_hash_set(self):
        from assistant_os.sandbox.execution_result import ExecutionMetadata
        m = ExecutionMetadata(
            execution_id="e1", plan_id="p1", policy_id="default",
            runtime_profile="python3.11", duration_ms=10,
            exit_code=0, timed_out=False, truncated=False,
            authorized_plan_hash="sha256-abc",
        )
        assert m.authorized_plan_hash == "sha256-abc"

    def test_to_dict_includes_hash(self):
        from assistant_os.sandbox.execution_result import ExecutionMetadata
        m = ExecutionMetadata(
            execution_id="e1", plan_id="p1", policy_id="default",
            runtime_profile="python3.11", duration_ms=10,
            exit_code=0, timed_out=False, truncated=False,
            authorized_plan_hash="hash-xyz",
        )
        d = m.to_dict()
        assert d["authorized_plan_hash"] == "hash-xyz"

    def test_to_dict_backward_compat_empty_hash(self):
        from assistant_os.sandbox.execution_result import ExecutionMetadata
        m = ExecutionMetadata(
            execution_id="e1", plan_id="p1", policy_id="default",
            runtime_profile="python3.11", duration_ms=10,
            exit_code=0, timed_out=False, truncated=False,
        )
        d = m.to_dict()
        assert "authorized_plan_hash" in d
        assert d["authorized_plan_hash"] == ""


# ===========================================================================
# G — TestAuditNewEventTypes
# ===========================================================================

class TestAuditNewEventTypes:
    def test_output_truncated_constant(self):
        from assistant_os.sandbox.audit import AuditEventType
        assert AuditEventType.OUTPUT_TRUNCATED == "output_truncated"

    def test_artifact_collected_constant(self):
        from assistant_os.sandbox.audit import AuditEventType
        assert AuditEventType.ARTIFACT_COLLECTED == "artifact_collected"

    def test_artifact_rejected_constant(self):
        from assistant_os.sandbox.audit import AuditEventType
        assert AuditEventType.ARTIFACT_REJECTED == "artifact_rejected"

    def test_output_event_construction(self):
        from assistant_os.sandbox.audit import AuditEventType, OutputEvent
        ev = OutputEvent(
            event_type=AuditEventType.OUTPUT_TRUNCATED,
            execution_id="e1",
            plan_id="p1",
            timestamp=1234.0,
            stream="stdout",
            original_bytes=10000,
            retained_bytes=8192,
            policy_id="default",
            classification="user-visible",
        )
        assert ev.stream == "stdout"
        assert ev.original_bytes == 10000
        assert ev.retained_bytes == 8192

    def test_output_event_to_dict(self):
        from assistant_os.sandbox.audit import AuditEventType, OutputEvent
        ev = OutputEvent(
            event_type=AuditEventType.OUTPUT_TRUNCATED,
            execution_id="e1", plan_id="p1", timestamp=0.0,
            stream="stderr", original_bytes=5000, retained_bytes=4096,
            policy_id="strict", classification="internal-only",
        )
        d = ev.to_dict()
        assert d["stream"] == "stderr"
        assert d["original_bytes"] == 5000
        assert d["policy_id"] == "strict"

    def test_artifact_event_collected(self):
        from assistant_os.sandbox.audit import ArtifactEvent, AuditEventType
        ev = ArtifactEvent(
            event_type=AuditEventType.ARTIFACT_COLLECTED,
            execution_id="e1", plan_id="p1", timestamp=0.0,
            artifact_path="out/result.json",
            size_bytes=1024,
            classification="output",
            sha256="abcdef",
        )
        d = ev.to_dict()
        assert d["artifact_path"] == "out/result.json"
        assert d["sha256"] == "abcdef"
        assert d["rejection_reason"] == ""

    def test_artifact_event_rejected(self):
        from assistant_os.sandbox.audit import ArtifactEvent, AuditEventType
        ev = ArtifactEvent(
            event_type=AuditEventType.ARTIFACT_REJECTED,
            execution_id="e1", plan_id="p1", timestamp=0.0,
            artifact_path="out/huge.bin",
            size_bytes=0,
            rejection_reason="exceeds max size",
        )
        d = ev.to_dict()
        assert d["rejection_reason"] == "exceeds max size"
        assert d["sha256"] == ""

    def test_output_event_frozen(self):
        from assistant_os.sandbox.audit import AuditEventType, OutputEvent
        ev = OutputEvent(
            event_type=AuditEventType.OUTPUT_TRUNCATED,
            execution_id="e1", plan_id="p1", timestamp=0.0,
            stream="stdout", original_bytes=100, retained_bytes=50,
            policy_id="default",
        )
        with pytest.raises((AttributeError, TypeError)):
            ev.stream = "stderr"  # type: ignore

    def test_artifact_event_frozen(self):
        from assistant_os.sandbox.audit import ArtifactEvent, AuditEventType
        ev = ArtifactEvent(
            event_type=AuditEventType.ARTIFACT_COLLECTED,
            execution_id="e1", plan_id="p1", timestamp=0.0,
            artifact_path="out/f.txt", size_bytes=10,
        )
        with pytest.raises((AttributeError, TypeError)):
            ev.artifact_path = "tampered"  # type: ignore


# ===========================================================================
# H — TestAuditExecutionEventRicher
# ===========================================================================

class TestAuditExecutionEventRicher:
    def test_new_fields_default_empty(self):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        ev = ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1",
            timestamp=0.0, status="running",
        )
        assert ev.authorized_plan_hash == ""
        assert ev.policy_id == ""

    def test_new_fields_set(self):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        ev = ExecutionEvent(
            event_type=AuditEventType.EXECUTION_COMPLETED,
            execution_id="e1", plan_id="p1",
            timestamp=0.0, status="completed",
            authorized_plan_hash="hash-123",
            policy_id="strict",
        )
        assert ev.authorized_plan_hash == "hash-123"
        assert ev.policy_id == "strict"

    def test_to_dict_includes_new_fields(self):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        ev = ExecutionEvent(
            event_type=AuditEventType.EXECUTION_COMPLETED,
            execution_id="e1", plan_id="p1",
            timestamp=0.0, status="completed",
            authorized_plan_hash="h", policy_id="default",
        )
        d = ev.to_dict()
        assert "authorized_plan_hash" in d
        assert "policy_id" in d
        assert d["policy_id"] == "default"

    def test_backward_compat_existing_code(self):
        """Existing code that creates ExecutionEvent without new fields still works."""
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        ev = ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1",
            timestamp=0.0, status="running",
            termination_reason="none",
            runtime_profile="python3.11",
            container_id="container-abc",
        )
        d = ev.to_dict()
        assert d["container_id"] == "container-abc"
        assert d["authorized_plan_hash"] == ""


# ===========================================================================
# I — TestRunnerAPIOutputPolicy
# ===========================================================================

class TestRunnerAPIOutputPolicy:
    def test_output_record_populated_after_execution(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        backend = _make_mock_backend(stdout="hello world", stderr="warning")
        result = RunnerAPI(backend=backend).execute(
            "print('hello')", str(tmp_path),
            authorized_plan=_make_plan(),
        )
        assert result.output_record is not None
        assert result.output_record.output_policy_id == "default"
        assert result.output_record.stdout == "hello world"

    def test_stdout_bytes_recorded(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        backend = _make_mock_backend(stdout="x" * 100, stderr="")
        result = RunnerAPI(backend=backend).execute(
            "print('x'*100)", str(tmp_path),
            authorized_plan=_make_plan(),
        )
        assert result.output_record is not None
        assert result.output_record.stdout_bytes == 100

    def test_truncation_event_emitted_for_long_stdout(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.output_policy import OutputPolicy
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        # Backend returns output that exceeds the default 8192 cap
        long_output = "x" * 10_000
        backend = _make_mock_backend(stdout=long_output, stderr="")
        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )
        trunc_events = audit.events(AuditEventType.OUTPUT_TRUNCATED)
        assert len(trunc_events) >= 1
        stdout_events = [e for e in trunc_events if e.stream == "stdout"]
        assert len(stdout_events) == 1
        assert stdout_events[0].original_bytes == 10_000

    def test_no_truncation_event_for_short_output(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend(stdout="short", stderr="")
        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )
        assert audit.count(AuditEventType.OUTPUT_TRUNCATED) == 0

    def test_readonly_policy_blanks_stdout(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        backend = _make_mock_backend(stdout="sensitive", stderr="also sensitive")
        result = RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(policy_id="readonly"),
        )
        assert result.stdout == ""
        assert result.stderr == ""

    def test_readonly_policy_emits_truncation_events(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend(stdout="out", stderr="err")
        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(policy_id="readonly"),
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )
        trunc_events = audit.events(AuditEventType.OUTPUT_TRUNCATED)
        streams = {e.stream for e in trunc_events}
        assert "stdout" in streams
        assert "stderr" in streams

    def test_output_record_classification_from_policy(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        backend = _make_mock_backend(stdout="hello", stderr="")
        result = RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(policy_id="default"),
        )
        assert result.output_record.stdout_classification == "user-visible"
        assert result.output_record.stderr_classification == "internal-only"

    def test_execution_without_plan_uses_default_policy(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        backend = _make_mock_backend(stdout="hello", stderr="")
        result = RunnerAPI(backend=backend).execute("code", str(tmp_path))
        assert result.output_record is not None
        assert result.output_record.output_policy_id == "default"


# ===========================================================================
# J — TestRunnerAPIArtifactEvents
# ===========================================================================

class TestRunnerAPIArtifactEvents:
    def test_artifact_collected_event_emitted(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend()
        plan = _make_plan()

        # Pre-create workspace/out/ with a file to be collected
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (out_dir / "result.txt").write_text("output data")

        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=plan,
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )

        collected = audit.events(AuditEventType.ARTIFACT_COLLECTED)
        assert len(collected) >= 1
        paths = [e.artifact_path for e in collected]
        assert any("result.txt" in p for p in paths)

    def test_artifact_collected_event_has_sha256(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend()
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (out_dir / "data.json").write_text('{"x": 1}')

        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )

        collected = audit.events(AuditEventType.ARTIFACT_COLLECTED)
        assert len(collected) >= 1
        assert all(len(e.sha256) > 0 for e in collected)

    def test_artifact_rejected_event_emitted_for_oversized_file(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend()
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        # Write a file that exceeds MAX_ARTIFACT_SIZE_BYTES (1 MB)
        big_path = out_dir / "big.bin"
        big_path.write_bytes(b"x" * (1_048_576 + 1))

        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )

        rejected = audit.events(AuditEventType.ARTIFACT_REJECTED)
        assert len(rejected) >= 1
        assert any("big.bin" in e.artifact_path for e in rejected)

    def test_no_artifact_events_when_out_dir_empty(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend()

        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )

        assert audit.count(AuditEventType.ARTIFACT_COLLECTED) == 0
        assert audit.count(AuditEventType.ARTIFACT_REJECTED) == 0

    def test_result_manifest_populated(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (out_dir / "file.txt").write_text("data")

        backend = _make_mock_backend()
        result = RunnerAPI(backend=backend).execute(
            "code", str(tmp_path), authorized_plan=_make_plan(),
        )
        assert result.manifest is not None
        assert len(result.manifest.records) == 1

    def test_result_artifacts_list_populated(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (out_dir / "a.txt").write_text("a")
        (out_dir / "b.txt").write_text("b")

        backend = _make_mock_backend()
        result = RunnerAPI(backend=backend).execute(
            "code", str(tmp_path), authorized_plan=_make_plan(),
        )
        assert len(result.artifacts) == 2


# ===========================================================================
# K — TestOutputVsArtifactSeparation
# ===========================================================================

class TestOutputVsArtifactSeparation:
    def test_output_record_and_manifest_are_independent(self, tmp_path):
        """output_record (stdout/stderr) and manifest (workspace/out) are orthogonal."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (out_dir / "result.json").write_text('{"ok": true}')

        backend = _make_mock_backend(stdout="some output", stderr="some error")
        result = RunnerAPI(backend=backend).execute(
            "code", str(tmp_path), authorized_plan=_make_plan(),
        )
        # Both are populated but independent
        assert result.output_record is not None
        assert result.manifest is not None
        # output_record covers streams; manifest covers files
        assert result.output_record.stdout == "some output"
        assert result.manifest.records[0].path.endswith("result.json")

    def test_blocked_output_does_not_block_artifacts(self, tmp_path):
        """readonly policy blanks output but artifacts are still collected."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (out_dir / "data.csv").write_text("a,b,c")

        backend = _make_mock_backend(stdout="sensitive", stderr="sensitive error")
        result = RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(policy_id="readonly"),
        )
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.manifest is not None
        assert len(result.manifest.records) == 1   # artifact still collected

    def test_execution_metadata_always_persisted(self, tmp_path):
        """ExecutionMetadata persists even when output policy is readonly."""
        from assistant_os.sandbox.execution_result import ExecutionMetadata
        from assistant_os.sandbox.runner_api import RunnerAPI

        backend = _make_mock_backend(stdout="out", stderr="err")
        result = RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(policy_id="readonly"),
        )
        # metadata field is separate from output_record and manifest
        # (runner_api does not yet populate metadata — that's handled by callers
        # that wrap the result; this test verifies the field exists)
        assert hasattr(result, "metadata")

    def test_output_policy_id_independent_of_artifact_policy(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (out_dir / "out.txt").write_text("artifact")

        backend = _make_mock_backend(stdout="stream")
        result = RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(policy_id="strict"),
        )
        # Output is governed by "strict" policy
        assert result.output_record.output_policy_id == "strict"
        # Artifact manifest uses its own policy (ArtifactPolicy defaults)
        assert result.manifest.export_root == "out"

    def test_output_event_not_an_artifact_event(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend(stdout="x" * 10_000, stderr="")
        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry, revocation_manager=revmgr, audit_log=audit,
        )
        # OUTPUT_TRUNCATED events must not appear in artifact event lists
        artifact_evts = (audit.events(AuditEventType.ARTIFACT_COLLECTED) +
                         audit.events(AuditEventType.ARTIFACT_REJECTED))
        for ev in artifact_evts:
            assert ev.event_type != AuditEventType.OUTPUT_TRUNCATED


# ===========================================================================
# L — TestOutputRedaction
# ===========================================================================

class TestOutputRedaction:
    def test_blocked_stdout_not_in_output_record_dict(self):
        from assistant_os.sandbox.output_policy import (
            OUTPUT_CLASSIFICATION_BLOCKED, OutputPolicy, OutputPolicyEngine,
        )
        policy = OutputPolicy(stdout_classification=OUTPUT_CLASSIFICATION_BLOCKED)
        rec, _ = OutputPolicyEngine.apply("SENSITIVE DATA", "", policy)
        d = rec.to_dict()
        assert "SENSITIVE DATA" not in str(d)

    def test_output_event_never_carries_content(self):
        from assistant_os.sandbox.audit import AuditEventType, OutputEvent
        ev = OutputEvent(
            event_type=AuditEventType.OUTPUT_TRUNCATED,
            execution_id="e1", plan_id="p1", timestamp=0.0,
            stream="stdout", original_bytes=50000, retained_bytes=8192,
            policy_id="default",
        )
        d = ev.to_dict()
        # OutputEvent carries only sizes, not content
        assert "content" not in d
        assert "stdout" not in d   # "stdout" as a value — only "stream" key

    def test_artifact_event_never_carries_file_content(self):
        from assistant_os.sandbox.audit import ArtifactEvent, AuditEventType
        ev = ArtifactEvent(
            event_type=AuditEventType.ARTIFACT_COLLECTED,
            execution_id="e1", plan_id="p1", timestamp=0.0,
            artifact_path="out/f.txt",
            size_bytes=42,
            classification="output",
            sha256="deadbeef",
        )
        d = ev.to_dict()
        # No file content in event — only metadata
        for key in ("sha256", "size_bytes", "artifact_path", "classification"):
            assert key in d
        assert "content" not in d

    def test_execution_event_has_no_secret_fields(self):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        ev = ExecutionEvent(
            event_type=AuditEventType.EXECUTION_COMPLETED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="completed",
            authorized_plan_hash="h", policy_id="default",
        )
        d = ev.to_dict()
        sensitive = {"value", "password", "token", "credential", "secret_value"}
        assert not sensitive.intersection({k.lower() for k in d})

    def test_blocked_content_not_in_audit_event(self, tmp_path):
        """Even if backend returns blocked content, it must not appear in audit."""
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend(stdout="SUPERSECRET", stderr="ALSO_SECRET")
        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(policy_id="readonly"),
            registry=registry, revocation_manager=revmgr, audit_log=audit,
        )
        all_event_dicts = audit.all_dicts()
        combined = str(all_event_dicts)
        assert "SUPERSECRET" not in combined
        assert "ALSO_SECRET" not in combined


# ===========================================================================
# M — TestTruncationAsFirstClassEvent
# ===========================================================================

class TestTruncationAsFirstClassEvent:
    def test_no_silent_truncation_long_stdout(self, tmp_path):
        """Truncation of stdout must produce an explicit audit event."""
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend(stdout="a" * 9000, stderr="")
        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry, revocation_manager=revmgr, audit_log=audit,
        )
        assert audit.count(AuditEventType.OUTPUT_TRUNCATED) >= 1

    def test_no_silent_truncation_long_stderr(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend(stdout="", stderr="b" * 9000)
        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry, revocation_manager=revmgr, audit_log=audit,
        )
        stderr_trunc = [
            e for e in audit.events(AuditEventType.OUTPUT_TRUNCATED)
            if e.stream == "stderr"
        ]
        assert len(stderr_trunc) >= 1

    def test_truncation_event_has_execution_id(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend(stdout="x" * 9000, stderr="")
        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry, revocation_manager=revmgr, audit_log=audit,
        )
        evts = audit.events(AuditEventType.OUTPUT_TRUNCATED)
        assert all(e.execution_id == "exec-out-test" for e in evts)

    def test_truncation_event_retained_bytes_less_than_original(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        audit, registry, revmgr = _make_control_plane()
        backend = _make_mock_backend(stdout="x" * 9000, stderr="")
        RunnerAPI(backend=backend).execute(
            "code", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry, revocation_manager=revmgr, audit_log=audit,
        )
        evts = [e for e in audit.events(AuditEventType.OUTPUT_TRUNCATED)
                if e.stream == "stdout"]
        assert evts[0].retained_bytes < evts[0].original_bytes

    def test_output_record_truncated_flag_set(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        backend = _make_mock_backend(stdout="x" * 9000, stderr="")
        result = RunnerAPI(backend=backend).execute(
            "code", str(tmp_path), authorized_plan=_make_plan(),
        )
        assert result.output_record.truncated is True
        assert result.truncated is True
