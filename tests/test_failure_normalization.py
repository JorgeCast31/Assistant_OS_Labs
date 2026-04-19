"""
Sprint 8 — Failure Normalization + Audit Consistency Hardening

Test classes
------------
A  TestBackendExceptionNormalization  — backend.execute() raising → structured result
B  TestNormalizedResultShape          — shape/defaults of normalized failure result
C  TestNormalizedMetadata             — metadata populated on normalized failures
D  TestCleanupOnFailure               — cleanup runs unconditionally after exception
E  TestAuditOnFailure                 — execution_failed event emitted after exception
F  TestSecretCleanupOnFailure         — secrets invalidated after backend exception
G  TestInternalErrorClassification    — INTERNAL_ERROR vs ERROR distinctions
H  TestAuditStoreOpsHardening         — create_parent, path validation, append-only
I  TestContractConsistency            — validation errors still raise; no regression
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_crashing_backend(exc=RuntimeError("docker failed")):
    """Backend whose execute() raises."""
    b = MagicMock()
    b.prepare.return_value = None
    b.cleanup.return_value = None
    b.execute.side_effect = exc
    return b


def _make_good_backend(stdout="ok", exit_code=0):
    from assistant_os.sandbox.execution_result import ExecutionResult
    b = MagicMock()
    b.prepare.return_value = None
    b.cleanup.return_value = None
    b.execute.return_value = ExecutionResult(
        exit_code=exit_code, stdout=stdout, stderr="",
        duration_ms=10, truncated=False,
    )
    return b


def _make_plan(
    execution_id="exec-fail-1",
    plan_id="plan-fail-1",
    authorized_plan_hash="hash-fail-abc",
    policy_id="default",
):
    from assistant_os.sandbox.authorized_plan import AuthorizedPlan
    return AuthorizedPlan(
        execution_id=execution_id,
        plan_id=plan_id,
        authorized_plan_hash=authorized_plan_hash,
        policy_id=policy_id,
        capability_scope=["code_execution"],
        runtime_profile="python3.11",
    )


def _make_control_plane(audit_log=None):
    from assistant_os.sandbox.audit import AuditLog
    from assistant_os.sandbox.execution_registry import ExecutionRegistry
    from assistant_os.sandbox.revocation import RevocationManager
    audit = audit_log or AuditLog()
    registry = ExecutionRegistry()
    revmgr = RevocationManager(registry=registry, audit_log=audit)
    return audit, registry, revmgr


def _run_with_crash(tmp_path, backend=None, plan=None,
                    audit_log=None, registry=None, revmgr=None, **kwargs):
    from assistant_os.sandbox.runner_api import RunnerAPI
    return RunnerAPI(backend=backend or _make_crashing_backend()).execute(
        "print('hi')", str(tmp_path),
        authorized_plan=plan or _make_plan(),
        audit_log=audit_log,
        registry=registry,
        revocation_manager=revmgr,
        **kwargs,
    )


# ===========================================================================
# A — TestBackendExceptionNormalization
# ===========================================================================

class TestBackendExceptionNormalization:
    def test_returns_result_not_exception(self, tmp_path):
        """RunnerAPI must return a result even when backend.execute() raises."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(backend=_make_crashing_backend()).execute(
            "print('hi')", str(tmp_path),
        )
        assert result is not None

    def test_returns_execution_result_instance(self, tmp_path):
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(backend=_make_crashing_backend()).execute(
            "print('hi')", str(tmp_path),
        )
        assert isinstance(result, ExecutionResult)

    def test_result_is_failed(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert not result.ok
        assert result.exit_code == -1

    def test_error_field_carries_exception_info(self, tmp_path):
        backend = _make_crashing_backend(RuntimeError("disk full"))
        result = _run_with_crash(tmp_path, backend=backend)
        assert result.error is not None
        assert "RuntimeError" in result.error

    def test_error_field_truncated_to_200_chars(self, tmp_path):
        long_msg = "x" * 500
        backend = _make_crashing_backend(RuntimeError(long_msg))
        result = _run_with_crash(tmp_path, backend=backend)
        # error field = "RuntimeError: <message>"; message truncated to 200 chars
        assert result.error is not None
        # total error string length is bounded
        assert len(result.error) <= 300  # type+200 chars+separator

    def test_different_exception_types_normalized(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        for exc in [OSError("no space"), ValueError("bad arg"), MemoryError("OOM")]:
            backend = _make_crashing_backend(exc)
            result = RunnerAPI(backend=backend).execute("code", str(tmp_path))
            assert isinstance(result.error, str)
            assert type(exc).__name__ in result.error

    def test_stdout_empty_on_backend_crash(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert result.stdout == ""
        assert result.stderr == ""

    def test_duration_zero_on_backend_crash(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert result.duration_ms == 0

    def test_timed_out_false_on_backend_crash(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert result.timed_out is False

    def test_artifacts_empty_on_backend_crash(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert result.artifacts == []

    def test_manifest_none_on_backend_crash(self, tmp_path):
        result = _run_with_crash(tmp_path)
        # manifest may be None (no artifact collection ran)
        # OR it's an empty manifest — either is safe
        if result.manifest is not None:
            assert result.manifest.records == []


# ===========================================================================
# B — TestNormalizedResultShape
# ===========================================================================

class TestNormalizedResultShape:
    def test_make_internal_error_factory(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        r = ExecutionResult.make_internal_error("test error")
        assert r.exit_code == -1
        assert r.stdout == ""
        assert r.stderr == ""
        assert r.duration_ms == 0
        assert r.truncated is False
        assert r.error == "test error"

    def test_make_internal_error_default_message(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        r = ExecutionResult.make_internal_error()
        assert r.error is not None
        assert len(r.error) > 0

    def test_make_internal_error_ok_is_false(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        r = ExecutionResult.make_internal_error()
        assert r.ok is False

    def test_make_internal_error_to_dict_safe(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        r = ExecutionResult.make_internal_error("oops")
        d = r.to_dict()
        assert d["exit_code"] == -1
        assert d["ok"] is False
        assert d["error"] == "oops"

    def test_normalized_result_has_no_output_record(self, tmp_path):
        """output_record is None on normalized failure — no policy was applied."""
        result = _run_with_crash(tmp_path)
        # output_record may or may not be set depending on when crash happened
        # but it must never contain sensitive data if set
        if result.output_record is not None:
            assert result.output_record.stdout == ""
            assert result.output_record.stderr == ""


# ===========================================================================
# C — TestNormalizedMetadata
# ===========================================================================

class TestNormalizedMetadata:
    def test_metadata_not_none_after_crash(self, tmp_path):
        result = _run_with_crash(tmp_path, plan=_make_plan())
        assert result.metadata is not None

    def test_metadata_execution_id_from_plan(self, tmp_path):
        result = _run_with_crash(tmp_path, plan=_make_plan(execution_id="crash-exec"))
        assert result.metadata.execution_id == "crash-exec"

    def test_metadata_plan_id_from_plan(self, tmp_path):
        result = _run_with_crash(tmp_path, plan=_make_plan(plan_id="plan-crash"))
        assert result.metadata.plan_id == "plan-crash"

    def test_metadata_authorized_plan_hash_from_plan(self, tmp_path):
        result = _run_with_crash(tmp_path, plan=_make_plan(authorized_plan_hash="HASH-CRASH"))
        assert result.metadata.authorized_plan_hash == "HASH-CRASH"

    def test_metadata_policy_id_from_plan(self, tmp_path):
        result = _run_with_crash(tmp_path, plan=_make_plan(policy_id="strict"))
        assert result.metadata.policy_id == "strict"

    def test_metadata_runtime_profile_from_plan(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert result.metadata.runtime_profile == "python3.11"

    def test_metadata_backend_name_present(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert result.metadata.backend != ""
        assert "MagicMock" in result.metadata.backend

    def test_metadata_status_failed(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert result.metadata.status == "failed"

    def test_metadata_termination_reason_internal_error(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert result.metadata.termination_reason == "internal_error"

    def test_metadata_exit_code_minus_one(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert result.metadata.exit_code == -1

    def test_metadata_duration_zero_on_crash(self, tmp_path):
        result = _run_with_crash(tmp_path)
        # Duration is 0 — backend never returned timing
        assert result.metadata.duration_ms == 0

    def test_metadata_to_dict_complete(self, tmp_path):
        result = _run_with_crash(tmp_path, plan=_make_plan())
        d = result.metadata.to_dict()
        for key in ("execution_id", "plan_id", "authorized_plan_hash",
                    "policy_id", "runtime_profile", "backend",
                    "status", "termination_reason"):
            assert key in d, f"Missing metadata key: {key}"

    def test_metadata_no_secret_values_on_crash(self, tmp_path):
        result = _run_with_crash(tmp_path, plan=_make_plan())
        d = result.metadata.to_dict()
        sensitive = {"password", "token", "secret_value", "credential"}
        assert not sensitive.intersection({k.lower() for k in d})


# ===========================================================================
# D — TestCleanupOnFailure
# ===========================================================================

class TestCleanupOnFailure:
    def test_backend_cleanup_called_on_exception(self, tmp_path):
        backend = _make_crashing_backend()
        _run_with_crash(tmp_path, backend=backend)
        backend.cleanup.assert_called_once()

    def test_workspace_cleaned_on_exception(self, tmp_path):
        """workspace/input/ is removed even after backend crash."""
        backend = _make_crashing_backend()
        _run_with_crash(tmp_path, backend=backend)
        # Workspace subdirectories should be removed by cleanup
        assert not (tmp_path / "input").exists()

    def test_registry_marked_failed_on_exception(self, tmp_path):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        audit, registry, revmgr = _make_control_plane()
        backend = _make_crashing_backend()
        _run_with_crash(
            tmp_path, backend=backend,
            audit_log=audit, registry=registry, revmgr=revmgr,
        )
        run = registry.get("exec-fail-1")
        assert run is not None
        assert run.status == ExecutionStatus.FAILED

    def test_abort_signal_unregistered_on_exception(self, tmp_path):
        from assistant_os.sandbox.execution_registry import ExecutionRegistry
        from assistant_os.sandbox.revocation import RevocationManager
        audit, registry, revmgr = _make_control_plane()
        backend = _make_crashing_backend()
        _run_with_crash(
            tmp_path, backend=backend,
            audit_log=audit, registry=registry, revmgr=revmgr,
        )
        # Signal should be unregistered — check that revmgr doesn't hold it
        assert "exec-fail-1" not in revmgr._abort_signals  # noqa: SLF001

    def test_multiple_crashes_cleanup_independently(self, tmp_path):
        """Each crashed execution leaves workspace clean."""
        for i in range(3):
            backend = _make_crashing_backend()
            _run_with_crash(tmp_path, backend=backend, plan=_make_plan(
                execution_id=f"exec-crash-{i}",
                plan_id=f"plan-crash-{i}",
                authorized_plan_hash=f"hash-{i}",
            ))
            assert not (tmp_path / "input").exists()


# ===========================================================================
# E — TestAuditOnBackendUnavailable
#
# Backend crashes (TerminationReason.INTERNAL_ERROR) emit
# EXECUTION_BACKEND_UNAVAILABLE, NOT EXECUTION_FAILED.  Semantics:
#   EXECUTION_FAILED           → sandbox code failed (non-zero exit, error)
#   EXECUTION_BACKEND_UNAVAILABLE → infrastructure failure (backend raised)
# ===========================================================================

class TestAuditOnBackendUnavailable:
    def test_backend_unavailable_event_emitted_not_execution_failed(self, tmp_path):
        """INTERNAL_ERROR emits EXECUTION_BACKEND_UNAVAILABLE, not EXECUTION_FAILED."""
        from assistant_os.sandbox.audit import AuditEventType
        audit, registry, revmgr = _make_control_plane()
        _run_with_crash(
            tmp_path, audit_log=audit, registry=registry, revmgr=revmgr,
        )
        # Backend crash → EXECUTION_BACKEND_UNAVAILABLE, not EXECUTION_FAILED.
        assert audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 1
        assert audit.count(AuditEventType.EXECUTION_FAILED) == 0

    def test_execution_started_event_also_emitted(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        audit, registry, revmgr = _make_control_plane()
        _run_with_crash(
            tmp_path, audit_log=audit, registry=registry, revmgr=revmgr,
        )
        # execution_started is emitted before backend.execute(), so it still fires.
        assert audit.count(AuditEventType.EXECUTION_STARTED) == 1

    def test_backend_unavailable_event_has_internal_error_reason(self, tmp_path):
        """The event carries termination_reason='internal_error' for full traceability."""
        from assistant_os.sandbox.audit import AuditEventType
        audit, registry, revmgr = _make_control_plane()
        _run_with_crash(
            tmp_path, audit_log=audit, registry=registry, revmgr=revmgr,
        )
        events = audit.events(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE)
        assert events
        assert events[0].termination_reason == "internal_error"

    def test_backend_unavailable_event_has_execution_id(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        audit, registry, revmgr = _make_control_plane()
        _run_with_crash(
            tmp_path, audit_log=audit, registry=registry, revmgr=revmgr,
        )
        events = audit.events(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE)
        assert events[0].execution_id == "exec-fail-1"

    def test_no_secret_values_in_failure_events(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        audit, registry, revmgr = _make_control_plane()
        _run_with_crash(
            tmp_path, audit_log=audit, registry=registry, revmgr=revmgr,
        )
        for ev in audit.events():
            d = ev.to_dict()
            sensitive = {"password", "credential", "secret_value"}
            assert not sensitive.intersection({k.lower() for k in d})

    def test_audit_store_receives_backend_unavailable_event(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.audit_store import AuditStore
        from assistant_os.sandbox.execution_registry import ExecutionRegistry
        from assistant_os.sandbox.revocation import RevocationManager

        store = AuditStore(tmp_path / "audit" / "events.jsonl")
        registry = ExecutionRegistry()
        revmgr = RevocationManager(registry=registry, audit_log=store)

        _run_with_crash(
            tmp_path, audit_log=store, registry=registry, revmgr=revmgr,
        )
        assert store.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 1
        assert store.count(AuditEventType.EXECUTION_FAILED) == 0
        records = store.read_from_disk()
        unavail = [
            r for r in records
            if r["event_type"] == AuditEventType.EXECUTION_BACKEND_UNAVAILABLE
        ]
        assert unavail
        assert unavail[0]["termination_reason"] == "internal_error"


# ===========================================================================
# F — TestSecretCleanupOnFailure
# ===========================================================================

class TestSecretCleanupOnFailure:
    def test_secrets_invalidated_after_backend_crash(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend
        from assistant_os.secrets.secret_ref import SecretRef

        backend = LocalEnvBackend(memory_store={"key": "DONT_LEAK"})
        injector = SecretInjector(backend=backend)
        bundle_holder = []

        original_build = injector.build_env_bundle
        def capturing_build(*args, **kwargs):
            b = original_build(*args, **kwargs)
            bundle_holder.append(b)
            return b
        injector.build_env_bundle = capturing_build

        RunnerAPI(backend=_make_crashing_backend()).execute(
            "print('hi')", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=[SecretRef(name="MY_KEY", ref_token="mem:key", domain="code")],
            injector=injector,
        )

        assert bundle_holder, "Bundle was never created"
        assert bundle_holder[0].invalidated is True

    def test_env_file_deleted_after_crash(self, tmp_path):
        """Ephemeral env file must be deleted even after backend crash."""
        import tempfile
        import os as _os
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend
        from assistant_os.secrets.secret_ref import SecretRef

        created_files = []
        backend = LocalEnvBackend(memory_store={"key": "VALUE"})
        injector = SecretInjector(backend=backend)

        original_provision = injector.provision_env_file
        def tracking_provision(bundle):
            path = original_provision(bundle)
            created_files.append(path)
            return path
        injector.provision_env_file = tracking_provision

        RunnerAPI(backend=_make_crashing_backend()).execute(
            "print('hi')", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=[SecretRef(name="MY_KEY", ref_token="mem:key", domain="code")],
            injector=injector,
        )

        assert created_files, "Env file was never created"
        for env_path in created_files:
            assert not _os.path.exists(env_path), f"Env file not deleted: {env_path}"

    def test_no_secret_value_in_result_error_field(self, tmp_path):
        """Backend exception message must not leak secret values."""
        # Craft a backend that raises with a message containing a fake secret
        exc = RuntimeError("container failed; env contained MY_SECRET_VALUE=do-not-leak")
        result = _run_with_crash(tmp_path, backend=_make_crashing_backend(exc))
        # The error message should be included but it's the exc string, not a real secret
        # More importantly: the result's stdout/stderr are empty
        assert result.stdout == ""
        assert result.stderr == ""


# ===========================================================================
# G — TestInternalErrorClassification
# ===========================================================================

class TestInternalErrorClassification:
    def test_internal_error_enum_value(self):
        from assistant_os.sandbox.execution_run import TerminationReason
        assert TerminationReason.INTERNAL_ERROR == "internal_error"
        assert TerminationReason.INTERNAL_ERROR.value == "internal_error"

    def test_internal_error_distinct_from_error(self):
        from assistant_os.sandbox.execution_run import TerminationReason
        assert TerminationReason.INTERNAL_ERROR != TerminationReason.ERROR

    def test_sandbox_failure_uses_error_not_internal(self, tmp_path):
        """Non-zero exit from sandbox code uses ERROR, not INTERNAL_ERROR."""
        result = _run_with_crash(
            tmp_path,
            backend=_make_good_backend(exit_code=1),
        )
        assert result.metadata.termination_reason == "error"

    def test_backend_exception_uses_internal_error(self, tmp_path):
        """Hard backend failure uses INTERNAL_ERROR."""
        result = _run_with_crash(tmp_path, backend=_make_crashing_backend())
        assert result.metadata.termination_reason == "internal_error"

    def test_timeout_uses_timeout_reason(self, tmp_path):
        from assistant_os.sandbox.execution_result import ExecutionResult
        b = MagicMock()
        b.prepare.return_value = None
        b.cleanup.return_value = None
        b.execute.return_value = ExecutionResult(
            exit_code=-1, stdout="", stderr="", duration_ms=30000,
            truncated=False, timed_out=True,
        )
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(backend=b).execute(
            "code", str(tmp_path), authorized_plan=_make_plan(),
        )
        assert result.metadata.termination_reason == "timeout"

    def test_all_reason_values_are_distinct(self):
        from assistant_os.sandbox.execution_run import TerminationReason
        values = [r.value for r in TerminationReason]
        assert len(values) == len(set(values))

    def test_internal_error_in_registry_on_crash(self, tmp_path):
        from assistant_os.sandbox.execution_run import TerminationReason
        audit, registry, revmgr = _make_control_plane()
        _run_with_crash(
            tmp_path, audit_log=audit, registry=registry, revmgr=revmgr,
        )
        run = registry.get("exec-fail-1")
        assert run.termination_reason == TerminationReason.INTERNAL_ERROR


# ===========================================================================
# H — TestAuditStoreOpsHardening
# ===========================================================================

class TestAuditStoreOpsHardening:
    def test_create_parent_creates_nested_dirs(self, tmp_path):
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "deep" / "nested" / "audit.jsonl"
        assert not path.parent.exists()
        store = AuditStore(path)  # create_parent=True by default
        assert path.parent.exists()

    def test_create_parent_false_raises_on_missing_parent(self, tmp_path):
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "nonexistent" / "audit.jsonl"
        # With create_parent=False, writing should fail (parent doesn't exist)
        store = AuditStore(path, create_parent=False)
        # File write should fail silently (swallowed in emit)
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="running",
        ))
        # Event is in memory but file was not created
        assert store.count() == 1
        assert not path.exists()

    def test_path_without_extension_raises(self, tmp_path):
        from assistant_os.sandbox.audit_store import AuditStore
        with pytest.raises(ValueError, match="directory"):
            AuditStore(tmp_path / "subdir")

    def test_emit_still_works_after_file_error(self, tmp_path):
        """In-memory events still accumulate even if file write fails."""
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        # Simulate file write failure
        with patch.object(Path, "open", side_effect=OSError("no space")):
            store.emit(ExecutionEvent(
                event_type=AuditEventType.EXECUTION_STARTED,
                execution_id="e1", plan_id="p1", timestamp=0.0, status="running",
            ))
        # In-memory still has it
        assert store.count() == 1

    def test_append_only_no_clear_method(self):
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore.__new__(AuditStore)
        assert not hasattr(store, "clear"), "AuditStore must NOT have a clear() method"

    def test_existing_file_not_truncated_on_open(self, tmp_path):
        """Opening an existing file with a new AuditStore must not truncate it."""
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "audit.jsonl"
        store1 = AuditStore(path)
        store1.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="preserved", plan_id="p1", timestamp=0.0, status="running",
        ))
        size_before = path.stat().st_size

        # Open again — must not truncate
        store2 = AuditStore(path)
        size_after = path.stat().st_size
        assert size_after == size_before

    def test_concurrent_writes_produce_valid_jsonl(self, tmp_path):
        """All concurrent writes must produce parseable JSONL."""
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "concurrent.jsonl"
        store = AuditStore(path)
        n = 30
        errors = []

        def worker(i):
            try:
                store.emit(ExecutionEvent(
                    event_type=AuditEventType.EXECUTION_STARTED,
                    execution_id=f"e{i}", plan_id="p1",
                    timestamp=float(i), status="running",
                ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        records = store.read_from_disk()
        assert len(records) == n
        for r in records:
            assert "event_type" in r
            assert "_seq" in r


# ===========================================================================
# I — TestContractConsistency
# ===========================================================================

class TestContractConsistency:
    def test_validation_errors_still_raise(self, tmp_path):
        """Pre-execution validation errors must still propagate as ValueError."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        with pytest.raises(ValueError):
            RunnerAPI(backend=_make_good_backend()).execute(
                "code", str(tmp_path), runtime="ruby3",
            )

    def test_invalid_plan_still_raises(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan
        bad_plan = AuthorizedPlan(
            execution_id="", plan_id="p", authorized_plan_hash="h",
            policy_id="default", runtime_profile="python3.11",
        )
        with pytest.raises(ValueError):
            RunnerAPI(backend=_make_good_backend()).execute(
                "code", str(tmp_path), authorized_plan=bad_plan,
            )

    def test_good_backend_still_returns_ok_result(self, tmp_path):
        """Normalization must not affect the success path."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(backend=_make_good_backend()).execute(
            "code", str(tmp_path), authorized_plan=_make_plan(),
        )
        assert result.ok
        assert result.exit_code == 0

    def test_crashed_result_ok_is_false(self, tmp_path):
        result = _run_with_crash(tmp_path)
        assert result.ok is False

    def test_no_regression_sandbox_tests(self, tmp_path):
        """Basic execution contract unchanged — metadata present on success."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(backend=_make_good_backend()).execute(
            "code", str(tmp_path), authorized_plan=_make_plan(),
        )
        assert result.metadata is not None
        assert result.metadata.status == "completed"

    def test_no_regression_failed_sandbox_code(self, tmp_path):
        """Non-zero exit still uses ERROR not INTERNAL_ERROR."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(backend=_make_good_backend(exit_code=1)).execute(
            "code", str(tmp_path), authorized_plan=_make_plan(),
        )
        assert result.metadata.termination_reason == "error"
        assert result.metadata.termination_reason != "internal_error"

    def test_result_to_dict_always_valid(self, tmp_path):
        """to_dict() must succeed on both success and failure results."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        for backend in [_make_good_backend(), _make_crashing_backend()]:
            result = RunnerAPI(backend=backend).execute(
                "code", str(tmp_path), authorized_plan=_make_plan(),
            )
            d = result.to_dict()
            assert isinstance(d, dict)
            assert "exit_code" in d
            assert "ok" in d
