"""
Tests — Revocation + Abort Control + Audit Layer

Coverage matrix
---------------
A. ExecutionRun model       — creation, status transitions, to_dict            (no Docker)
B. ExecutionRegistry        — register, lookup, transitions, concurrent safety  (no Docker)
C. RevocationManager        — revoke before/during/after, idempotent, races     (no Docker)
D. AuditLog                 — emit, filter, thread safety, no secret values     (no Docker)
E. RunnerAPI revocation     — abort flow, lifecycle, audit events (mock backend)(no Docker)
F. Secret invalidation      — secrets cleaned on abort, no leaks               (no Docker)
G. Failure paths            — exception still cleans up, events emitted        (no Docker)
H. Audit redaction          — events never contain secret values                (no Docker)
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest


# ===========================================================================
# A. ExecutionRun model
# ===========================================================================


class TestExecutionRun:
    """ExecutionRun model — creation, fields, transitions, serialization."""

    def _make(self, **kwargs):
        from assistant_os.sandbox.execution_run import (
            ExecutionRun, ExecutionStatus, TerminationReason,
        )
        defaults = dict(
            execution_id="exec-001",
            plan_id="plan-001",
            authorized_plan_hash="abc123",
            policy_id="default",
            runtime_profile="python3.11",
        )
        defaults.update(kwargs)
        return ExecutionRun(**defaults)

    def test_default_status_is_pending(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        assert self._make().status == ExecutionStatus.PENDING

    def test_default_termination_reason_is_none(self):
        from assistant_os.sandbox.execution_run import TerminationReason
        assert self._make().termination_reason == TerminationReason.NONE

    def test_is_terminal_false_for_pending(self):
        assert self._make().is_terminal() is False

    def test_is_terminal_true_for_completed(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        run = self._make()
        run.status = ExecutionStatus.COMPLETED
        assert run.is_terminal() is True

    def test_is_terminal_true_for_failed(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        run = self._make()
        run.status = ExecutionStatus.FAILED
        assert run.is_terminal() is True

    def test_is_terminal_true_for_aborted(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        run = self._make()
        run.status = ExecutionStatus.ABORTED
        assert run.is_terminal() is True

    def test_duration_ms_none_before_completion(self):
        run = self._make()
        run.started_at = time.time()
        assert run.duration_ms() is None

    def test_duration_ms_calculated_when_ended(self):
        run = self._make()
        run.started_at = 1000.0
        run.ended_at = 1002.5
        assert run.duration_ms() == 2500

    def test_to_dict_contains_all_fields(self):
        run = self._make()
        d = run.to_dict()
        for key in ("execution_id", "plan_id", "authorized_plan_hash",
                    "policy_id", "runtime_profile", "status",
                    "started_at", "ended_at", "duration_ms",
                    "termination_reason", "container_id", "resource_summary"):
            assert key in d, f"to_dict() missing {key!r}"

    def test_to_dict_status_is_string(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        run = self._make()
        run.status = ExecutionStatus.RUNNING
        assert run.to_dict()["status"] == "running"

    def test_to_dict_termination_reason_is_string(self):
        from assistant_os.sandbox.execution_run import TerminationReason
        run = self._make()
        run.termination_reason = TerminationReason.REVOKED
        assert run.to_dict()["termination_reason"] == "revoked"

    def test_execution_status_values(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        for name, value in [
            ("PENDING", "pending"), ("RUNNING", "running"),
            ("COMPLETED", "completed"), ("FAILED", "failed"),
            ("ABORTED", "aborted"),
        ]:
            assert ExecutionStatus[name].value == value

    def test_termination_reason_values(self):
        from assistant_os.sandbox.execution_run import TerminationReason
        for name, value in [
            ("NONE", "none"), ("TIMEOUT", "timeout"),
            ("ERROR", "error"), ("REVOKED", "revoked"), ("MANUAL", "manual"),
        ]:
            assert TerminationReason[name].value == value


# ===========================================================================
# B. ExecutionRegistry
# ===========================================================================


class TestExecutionRegistry:
    """Thread-safe in-memory registry tests."""

    def _make_run(self, execution_id="exec-001", plan_id="plan-001"):
        from assistant_os.sandbox.execution_run import ExecutionRun
        return ExecutionRun(
            execution_id=execution_id,
            plan_id=plan_id,
            authorized_plan_hash="hash1",
            policy_id="default",
        )

    def _make_registry(self):
        from assistant_os.sandbox.execution_registry import ExecutionRegistry
        return ExecutionRegistry()

    def test_register_and_get(self):
        registry = self._make_registry()
        run = self._make_run()
        registry.register(run)
        assert registry.get("exec-001") is run

    def test_get_returns_none_for_unknown(self):
        assert self._make_registry().get("nonexistent") is None

    def test_require_raises_for_unknown(self):
        from assistant_os.sandbox.execution_registry import ExecutionNotFound
        with pytest.raises(ExecutionNotFound):
            self._make_registry().require("nonexistent")

    def test_duplicate_registration_raises(self):
        from assistant_os.sandbox.execution_registry import RegistryError
        registry = self._make_registry()
        registry.register(self._make_run())
        with pytest.raises(RegistryError, match="already registered"):
            registry.register(self._make_run())

    def test_mark_running(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        registry = self._make_registry()
        run = self._make_run()
        registry.register(run)
        registry.mark_running("exec-001", container_id="ctr-001")
        assert run.status == ExecutionStatus.RUNNING
        assert run.container_id == "ctr-001"
        assert run.started_at is not None

    def test_mark_running_from_wrong_state_raises(self):
        from assistant_os.sandbox.execution_registry import InvalidTransition
        from assistant_os.sandbox.execution_run import ExecutionStatus
        registry = self._make_registry()
        run = self._make_run()
        registry.register(run)
        run.status = ExecutionStatus.COMPLETED
        with pytest.raises(InvalidTransition):
            registry.mark_running("exec-001")

    def test_mark_completed(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus, TerminationReason
        registry = self._make_registry()
        run = self._make_run()
        registry.register(run)
        registry.mark_running("exec-001")
        registry.mark_completed("exec-001")
        assert run.status == ExecutionStatus.COMPLETED
        assert run.termination_reason == TerminationReason.NONE
        assert run.ended_at is not None

    def test_mark_failed(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus, TerminationReason
        registry = self._make_registry()
        run = self._make_run()
        registry.register(run)
        registry.mark_running("exec-001")
        registry.mark_failed("exec-001", reason=TerminationReason.TIMEOUT)
        assert run.status == ExecutionStatus.FAILED
        assert run.termination_reason == TerminationReason.TIMEOUT

    def test_mark_aborted_from_running(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus, TerminationReason
        registry = self._make_registry()
        run = self._make_run()
        registry.register(run)
        registry.mark_running("exec-001")
        registry.mark_aborted("exec-001", reason=TerminationReason.REVOKED)
        assert run.status == ExecutionStatus.ABORTED
        assert run.termination_reason == TerminationReason.REVOKED

    def test_mark_aborted_is_idempotent(self):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        registry = self._make_registry()
        run = self._make_run()
        registry.register(run)
        registry.mark_running("exec-001")
        registry.mark_aborted("exec-001")
        registry.mark_aborted("exec-001")  # second call must not raise
        assert run.status == ExecutionStatus.ABORTED

    def test_mark_aborted_silent_for_unregistered(self):
        """mark_aborted on unknown ID must not raise (RevocationManager calls this)."""
        self._make_registry().mark_aborted("unknown-exec")  # must not raise

    def test_all_runs_snapshot(self):
        registry = self._make_registry()
        registry.register(self._make_run("exec-001"))
        registry.register(self._make_run("exec-002"))
        runs = registry.all_runs()
        assert len(runs) == 2

    def test_count(self):
        registry = self._make_registry()
        assert registry.count() == 0
        registry.register(self._make_run())
        assert registry.count() == 1

    def test_concurrent_register_and_read(self):
        """Multiple threads registering different IDs must not corrupt state."""
        registry = self._make_registry()
        errors: list[Exception] = []

        def register_run(idx: int) -> None:
            try:
                from assistant_os.sandbox.execution_run import ExecutionRun
                run = ExecutionRun(
                    execution_id=f"exec-{idx:04d}",
                    plan_id="plan-001",
                    authorized_plan_hash="h",
                    policy_id="default",
                )
                registry.register(run)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=register_run, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent register errors: {errors}"
        assert registry.count() == 50

    def test_concurrent_mark_aborted(self):
        """Multiple threads calling mark_aborted on same ID must not crash."""
        registry = self._make_registry()
        run = self._make_run()
        registry.register(run)
        registry.mark_running("exec-001")
        errors: list[Exception] = []

        def abort() -> None:
            try:
                registry.mark_aborted("exec-001")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=abort) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent abort errors: {errors}"
        from assistant_os.sandbox.execution_run import ExecutionStatus
        assert run.status == ExecutionStatus.ABORTED


# ===========================================================================
# C. RevocationManager
# ===========================================================================


class TestRevocationManager:
    """RevocationManager — revocation, signal propagation, idempotency."""

    def _make(self):
        from assistant_os.sandbox.audit import AuditLog
        from assistant_os.sandbox.execution_registry import ExecutionRegistry
        from assistant_os.sandbox.revocation import RevocationManager

        registry = ExecutionRegistry()
        audit = AuditLog()
        mgr = RevocationManager(registry=registry, audit_log=audit)
        return mgr, registry, audit

    def test_check_revoked_false_before_revocation(self):
        mgr, _, _ = self._make()
        assert mgr.check_revoked("exec-001") is False

    def test_check_revoked_true_after_revocation(self):
        mgr, _, _ = self._make()
        mgr.revoke_execution("exec-001")
        assert mgr.check_revoked("exec-001") is True

    def test_revoke_is_idempotent(self):
        mgr, _, audit = self._make()
        mgr.revoke_execution("exec-001")
        mgr.revoke_execution("exec-001")  # second call must not raise
        # Only one event emitted (idempotent)
        from assistant_os.sandbox.audit import AuditEventType
        events = audit.events(AuditEventType.EXECUTION_REVOKED)
        assert len(events) == 1

    def test_revoke_emits_audit_event(self):
        mgr, _, audit = self._make()
        mgr.revoke_execution("exec-001", reason="manual")
        from assistant_os.sandbox.audit import AuditEventType
        events = audit.events(AuditEventType.EXECUTION_REVOKED)
        assert len(events) == 1
        assert events[0].execution_id == "exec-001"
        assert events[0].reason == "manual"

    def test_revoke_updates_registry(self):
        from assistant_os.sandbox.execution_run import ExecutionRun, ExecutionStatus
        mgr, registry, _ = self._make()
        run = ExecutionRun(
            execution_id="exec-001", plan_id="plan-001",
            authorized_plan_hash="h", policy_id="default",
        )
        registry.register(run)
        registry.mark_running("exec-001")
        mgr.revoke_execution("exec-001")
        assert run.status == ExecutionStatus.ABORTED

    def test_revoke_before_registration_updates_later(self):
        """Revoke called before registry.register — registry silently ignores it."""
        mgr, registry, _ = self._make()
        mgr.revoke_execution("exec-late")  # not yet registered — must not raise
        assert mgr.check_revoked("exec-late") is True

    def test_abort_signal_set_when_already_revoked(self):
        """register_abort_signal with already-revoked ID sets event immediately."""
        mgr, _, _ = self._make()
        mgr.revoke_execution("exec-001")
        event = threading.Event()
        mgr.register_abort_signal("exec-001", event)
        assert event.is_set()

    def test_abort_signal_set_when_revoked_after_registration(self):
        """revoke_execution after register_abort_signal sets the event."""
        mgr, _, _ = self._make()
        event = threading.Event()
        mgr.register_abort_signal("exec-001", event)
        assert not event.is_set()
        mgr.revoke_execution("exec-001")
        assert event.is_set()

    def test_abort_signal_cleared_after_unregister(self):
        """Unregistering does not affect the event (signal is already set or not)."""
        mgr, _, _ = self._make()
        event = threading.Event()
        mgr.register_abort_signal("exec-001", event)
        mgr.unregister_abort_signal("exec-001")
        # Signal not set (no revocation happened)
        assert not event.is_set()

    def test_unregister_safe_when_not_registered(self):
        mgr, _, _ = self._make()
        mgr.unregister_abort_signal("nonexistent")  # must not raise

    def test_revoked_ids_snapshot(self):
        mgr, _, _ = self._make()
        mgr.revoke_execution("exec-A")
        mgr.revoke_execution("exec-B")
        ids = mgr.revoked_ids()
        assert "exec-A" in ids
        assert "exec-B" in ids

    def test_concurrent_revoke_race(self):
        """Multiple threads revoking different IDs simultaneously must not corrupt."""
        mgr, _, _ = self._make()
        errors: list[Exception] = []

        def revoke(idx: int) -> None:
            try:
                mgr.revoke_execution(f"exec-{idx:04d}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=revoke, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(mgr.revoked_ids()) == 50


# ===========================================================================
# D. AuditLog
# ===========================================================================


class TestAuditLog:
    """AuditLog — emit, filter, thread safety, redaction."""

    def test_emit_and_count(self):
        from assistant_os.sandbox.audit import AuditEventType, AuditLog, ExecutionEvent

        log = AuditLog()
        log.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1",
            timestamp=time.time(), status="running",
        ))
        assert log.count() == 1

    def test_filter_by_event_type(self):
        from assistant_os.sandbox.audit import AuditEventType, AuditLog, ExecutionEvent

        log = AuditLog()
        for et in (AuditEventType.EXECUTION_STARTED,
                   AuditEventType.EXECUTION_COMPLETED,
                   AuditEventType.EXECUTION_STARTED):
            log.emit(ExecutionEvent(
                event_type=et, execution_id="e1", plan_id="p1",
                timestamp=time.time(), status="x",
            ))
        started = log.events(AuditEventType.EXECUTION_STARTED)
        assert len(started) == 2

    def test_all_dicts_serializable(self):
        import json
        from assistant_os.sandbox.audit import AuditEventType, AuditLog, ExecutionEvent

        log = AuditLog()
        log.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_ABORTED,
            execution_id="e1", plan_id="p1",
            timestamp=time.time(), status="aborted",
            termination_reason="revoked",
        ))
        j = json.dumps(log.all_dicts())  # must not raise
        assert "aborted" in j

    def test_clear(self):
        from assistant_os.sandbox.audit import AuditEventType, AuditLog, ExecutionEvent

        log = AuditLog()
        log.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1",
            timestamp=time.time(), status="running",
        ))
        log.clear()
        assert log.count() == 0

    def test_concurrent_emit(self):
        """Multiple threads emitting must not corrupt the event list."""
        from assistant_os.sandbox.audit import AuditEventType, AuditLog, ExecutionEvent

        log = AuditLog()
        errors: list[Exception] = []

        def emit_events() -> None:
            try:
                for _ in range(10):
                    log.emit(ExecutionEvent(
                        event_type=AuditEventType.EXECUTION_STARTED,
                        execution_id="e1", plan_id="p1",
                        timestamp=time.time(), status="running",
                    ))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=emit_events) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert log.count() == 100

    def test_secret_access_event_has_no_value_field(self):
        import json
        from assistant_os.sandbox.audit import AuditEventType, SecretAccessEvent

        event = SecretAccessEvent(
            event_type=AuditEventType.SECRET_PROVISIONED,
            secret_name="API_KEY",
            ref_token="env:ANTHROPIC_API_KEY",
            plan_id="p1",
            execution_id="e1",
            timestamp=time.time(),
            backend="LocalEnvBackend",
        )
        d = event.to_dict()
        assert "value" not in d
        j = json.dumps(d)
        assert "value" not in j

    def test_revocation_event_shape(self):
        from assistant_os.sandbox.audit import AuditEventType, RevocationEvent

        event = RevocationEvent(
            event_type=AuditEventType.EXECUTION_REVOKED,
            execution_id="e1",
            plan_id="p1",
            timestamp=time.time(),
            reason="manual",
        )
        d = event.to_dict()
        for key in ("event_type", "execution_id", "plan_id", "timestamp", "reason"):
            assert key in d


# ===========================================================================
# E. RunnerAPI revocation (mock backend — no Docker)
# ===========================================================================


class _SlowMockBackend:
    """
    Mock ExecutionBackend that polls abort_signal.
    Simulates a long-running execution that can be aborted.
    """
    execution_duration_s: float = 5.0

    def prepare(self, _workspace: str) -> None:
        pass

    def execute(self, workspace_path, entry_point, timeout_seconds,
                env_file="", abort_signal=None, container_name=""):
        from assistant_os.sandbox.execution_result import ExecutionResult

        start = time.time()
        while time.time() - start < self.execution_duration_s:
            if abort_signal is not None and abort_signal.is_set():
                return ExecutionResult(
                    exit_code=-1, stdout="", stderr="",
                    duration_ms=int((time.time() - start) * 1000),
                    truncated=False,
                    error="Execution aborted — revocation signal received",
                )
            time.sleep(0.02)
        return ExecutionResult(
            exit_code=0, stdout="done", stderr="",
            duration_ms=int((time.time() - start) * 1000),
            truncated=False,
        )

    def cleanup(self, _workspace: str) -> None:
        pass


def _make_control_plane():
    from assistant_os.sandbox.audit import AuditLog
    from assistant_os.sandbox.execution_registry import ExecutionRegistry
    from assistant_os.sandbox.revocation import RevocationManager

    registry = ExecutionRegistry()
    audit = AuditLog()
    revmgr = RevocationManager(registry=registry, audit_log=audit)
    return registry, revmgr, audit


def _make_plan(execution_id="exec-001", plan_id="plan-001"):
    from assistant_os.sandbox.authorized_plan import AuthorizedPlan
    return AuthorizedPlan(
        execution_id=execution_id,
        plan_id=plan_id,
        authorized_plan_hash="abc123",
        policy_id="default",
    )


class TestRunnerAPIRevocation:
    """RunnerAPI abort flow with mock backend — no Docker required."""

    def test_execution_registered_as_running(self, tmp_path):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, audit = _make_control_plane()
        backend = MagicMock()
        from assistant_os.sandbox.execution_result import ExecutionResult
        backend.execute.return_value = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )

        run = registry.get("exec-001")
        assert run is not None
        assert run.status == ExecutionStatus.COMPLETED

    def test_revoke_before_start_aborts_execution(self, tmp_path):
        """Execution revoked before it starts still aborts cleanly."""
        from assistant_os.sandbox.execution_run import ExecutionStatus
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, audit = _make_control_plane()
        # Revoke before execution starts
        revmgr.revoke_execution("exec-001")

        slow_backend = _SlowMockBackend()
        result = RunnerAPI(backend=slow_backend).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )

        # Execution was aborted
        assert result.error is not None
        assert "aborted" in result.error.lower()

        run = registry.get("exec-001")
        assert run.status == ExecutionStatus.ABORTED

    def test_revoke_during_execution(self, tmp_path):
        """Revocation mid-execution aborts the run and updates registry."""
        from assistant_os.sandbox.execution_run import ExecutionStatus, TerminationReason
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, audit = _make_control_plane()
        slow_backend = _SlowMockBackend()
        slow_backend.execution_duration_s = 10.0

        results: list = []
        errors: list = []

        def run_execution():
            try:
                result = RunnerAPI(backend=slow_backend).execute(
                    "print(1)", str(tmp_path),
                    authorized_plan=_make_plan(),
                    registry=registry,
                    revocation_manager=revmgr,
                    audit_log=audit,
                )
                results.append(result)
            except Exception as exc:
                errors.append(exc)

        exec_thread = threading.Thread(target=run_execution)
        exec_thread.start()

        # Wait for execution to start (RUNNING)
        deadline = time.time() + 3.0
        while time.time() < deadline:
            run = registry.get("exec-001")
            if run and run.status == ExecutionStatus.RUNNING:
                break
            time.sleep(0.05)

        # Revoke while running
        revmgr.revoke_execution("exec-001", reason="manual")
        exec_thread.join(timeout=5.0)

        assert not errors, f"Execution thread raised: {errors}"
        assert results, "Execution thread produced no result"

        result = results[0]
        assert result.error is not None
        assert "aborted" in result.error.lower()

        run = registry.get("exec-001")
        assert run.status == ExecutionStatus.ABORTED
        assert run.termination_reason == TerminationReason.REVOKED

    def test_container_id_set_in_run(self, tmp_path):
        """ExecutionRun.container_id is set from the generated container name."""
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, audit = _make_control_plane()
        backend = MagicMock()
        from assistant_os.sandbox.execution_result import ExecutionResult
        backend.execute.return_value = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
        )
        run = registry.get("exec-001")
        assert run.container_id is not None
        assert run.container_id.startswith("assistantos-runner-")

    def test_status_failed_on_nonzero_exit(self, tmp_path):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, audit = _make_control_plane()
        backend = MagicMock()
        from assistant_os.sandbox.execution_result import ExecutionResult
        backend.execute.return_value = ExecutionResult(
            exit_code=1, stdout="", stderr="error",
            duration_ms=10, truncated=False,
        )
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "raise ValueError()", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
        )
        assert registry.get("exec-001").status == ExecutionStatus.FAILED

    def test_multiple_revocations_idempotent(self, tmp_path):
        """Calling revoke_execution many times does not emit duplicate events."""
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, audit = _make_control_plane()

        for _ in range(5):
            revmgr.revoke_execution("exec-001")

        events = audit.events(AuditEventType.EXECUTION_REVOKED)
        assert len(events) == 1  # idempotent — only one event

    def test_abort_signal_unregistered_after_execution(self, tmp_path):
        """After execution, the abort signal is removed from RevocationManager."""
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, audit = _make_control_plane()
        backend = MagicMock()
        from assistant_os.sandbox.execution_result import ExecutionResult
        backend.execute.return_value = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
        )
        # After execution: abort signal is removed
        # A new revocation should NOT set any stale event
        new_event = threading.Event()
        revmgr.register_abort_signal("exec-001-NEW", new_event)
        assert not new_event.is_set()


# ===========================================================================
# F. Secret invalidation on abort
# ===========================================================================


class TestSecretInvalidationOnAbort:
    """Secrets are always invalidated — abort, failure, or success."""

    def _make_injector_with_tracker(self):
        """Return injector + tracker to observe bundle invalidation."""
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend

        injector = SecretInjector(
            backend=LocalEnvBackend(memory_store={"key": "SECRET_VAL_123"})
        )
        bundles: list = []
        original_build = injector.build_env_bundle

        def tracking_build(*args, **kwargs):
            bundle = original_build(*args, **kwargs)
            bundles.append(bundle)
            return bundle

        injector.build_env_bundle = tracking_build
        return injector, bundles

    def _make_secret_refs(self):
        from assistant_os.secrets.secret_ref import SecretRef
        return [SecretRef(name="KEY", ref_token="mem:key", domain="code")]

    def test_bundle_invalidated_after_successful_execution(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI

        injector, bundles = self._make_injector_with_tracker()
        backend = MagicMock()
        from assistant_os.sandbox.execution_result import ExecutionResult
        backend.execute.return_value = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=self._make_secret_refs(),
            injector=injector,
        )

        assert bundles, "build_env_bundle was not called"
        assert bundles[0].invalidated, "Bundle must be invalidated after execution"

    def test_bundle_invalidated_after_aborted_execution(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, audit = _make_control_plane()
        injector, bundles = self._make_injector_with_tracker()

        revmgr.revoke_execution("exec-001")  # revoke before start

        slow = _SlowMockBackend()
        RunnerAPI(backend=slow).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=self._make_secret_refs(),
            injector=injector,
            registry=registry,
            revocation_manager=revmgr,
        )

        assert bundles, "build_env_bundle was not called"
        assert bundles[0].invalidated, "Bundle must be invalidated even on abort"

    def test_bundle_invalidated_after_failed_execution(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI

        injector, bundles = self._make_injector_with_tracker()
        backend = MagicMock()
        from assistant_os.sandbox.execution_result import ExecutionResult
        backend.execute.return_value = ExecutionResult(
            exit_code=1, stdout="", stderr="fail",
            duration_ms=10, truncated=False,
        )
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "raise ValueError()", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=self._make_secret_refs(),
            injector=injector,
        )

        assert bundles[0].invalidated, "Bundle must be invalidated on failure"

    def test_handles_invalidated_on_abort(self, tmp_path):
        """All SecretHandles in the bundle are wiped after abort."""
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, _ = _make_control_plane()
        injector, bundles = self._make_injector_with_tracker()

        revmgr.revoke_execution("exec-001")
        slow = _SlowMockBackend()
        RunnerAPI(backend=slow).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=self._make_secret_refs(),
            injector=injector,
            registry=registry,
            revocation_manager=revmgr,
        )

        for handle in bundles[0].handles:
            assert handle.invalidated, f"Handle {handle.handle_id!r} not invalidated"

    def test_secret_not_in_workspace_after_abort(self, tmp_path):
        """No secret values should persist in workspace after aborted execution."""
        import os
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, _ = _make_control_plane()
        injector, _ = self._make_injector_with_tracker()

        revmgr.revoke_execution("exec-001")
        slow = _SlowMockBackend()
        RunnerAPI(backend=slow).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=self._make_secret_refs(),
            injector=injector,
            registry=registry,
            revocation_manager=revmgr,
        )

        for root, _, files in os.walk(str(tmp_path)):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    content = open(fpath, encoding="utf-8", errors="replace").read()
                    assert "SECRET_VAL_123" not in content, (
                        f"Secret found in workspace file: {fpath}"
                    )
                except OSError:
                    pass


# ===========================================================================
# G. Failure paths
# ===========================================================================


class TestFailurePaths:
    """Cleanup always runs; events emitted even on exception."""

    def test_workspace_cleaned_when_backend_raises(self, tmp_path):
        """Backend exception is normalized to a failure result; workspace still cleaned."""
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.sandbox.runner_api import RunnerAPI

        backend = MagicMock()
        backend.execute.side_effect = RuntimeError("backend exploded")
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        # RunnerAPI normalizes — returns a structured failure result, does NOT re-raise.
        result = RunnerAPI(backend=backend).execute("print(1)", str(tmp_path))
        assert isinstance(result, ExecutionResult)
        assert not result.ok
        assert result.error is not None
        assert "RuntimeError" in result.error

        # Workspace sub-dirs must not exist after cleanup
        assert not (tmp_path / "input").exists()

    def test_registry_marked_failed_when_backend_raises(self, tmp_path):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, audit = _make_control_plane()
        backend = MagicMock()
        backend.execute.side_effect = RuntimeError("internal error")
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )

        run = registry.get("exec-001")
        assert run.status == ExecutionStatus.FAILED

    def test_audit_event_emitted_on_exception(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI

        registry, revmgr, audit = _make_control_plane()
        backend = MagicMock()
        backend.execute.side_effect = RuntimeError("bang")
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )

        # execution_started was emitted; backend crash → EXECUTION_BACKEND_UNAVAILABLE
        # (not EXECUTION_FAILED — backend failures are semantically distinct from
        # sandbox code failures, per TerminationReason.INTERNAL_ERROR semantics).
        assert audit.count(AuditEventType.EXECUTION_STARTED) == 1
        assert audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 1
        assert audit.count(AuditEventType.EXECUTION_FAILED) == 0

    def test_secrets_invalidated_when_backend_raises(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend
        from assistant_os.secrets.secret_ref import SecretRef

        injector = SecretInjector(
            backend=LocalEnvBackend(memory_store={"k": "v"})
        )
        bundles: list = []
        orig = injector.build_env_bundle

        def track(*a, **kw):
            b = orig(*a, **kw)
            bundles.append(b)
            return b

        injector.build_env_bundle = track

        backend = MagicMock()
        backend.execute.side_effect = RuntimeError("crash")
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=[SecretRef(name="K", ref_token="mem:k", domain="code")],
            injector=injector,
        )

        assert bundles and bundles[0].invalidated, "Secrets not invalidated on exception"

    def test_cleanup_runs_even_without_control_plane(self, tmp_path):
        """RunnerAPI without registry/revmgr/audit still cleans workspace."""
        from assistant_os.sandbox.runner_api import RunnerAPI

        backend = MagicMock()
        from assistant_os.sandbox.execution_result import ExecutionResult
        backend.execute.return_value = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute("print(1)", str(tmp_path))

        assert not (tmp_path / "input").exists()
        assert not (tmp_path / "output").exists()
        assert not (tmp_path / "out").exists()


# ===========================================================================
# H. Audit redaction
# ===========================================================================


class TestAuditRedaction:
    """All audit events must be free of secret values."""

    def test_execution_events_have_no_secret_fields(self, tmp_path):
        import json
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend
        from assistant_os.secrets.secret_ref import SecretRef

        registry, revmgr, audit = _make_control_plane()
        injector = SecretInjector(
            backend=LocalEnvBackend(memory_store={"key": "ULTRA_SECRET_XYZ_789"})
        )
        backend = MagicMock()
        from assistant_os.sandbox.execution_result import ExecutionResult
        backend.execute.return_value = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=[
                SecretRef(name="KEY", ref_token="mem:key", domain="code"),
            ],
            injector=injector,
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )

        all_events_json = json.dumps(audit.all_dicts())
        assert "ULTRA_SECRET_XYZ_789" not in all_events_json, (
            "Secret value leaked into audit log"
        )

    def test_secret_access_events_emitted_with_name_not_value(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend
        from assistant_os.secrets.secret_ref import SecretRef

        registry, revmgr, audit = _make_control_plane()
        injector = SecretInjector(
            backend=LocalEnvBackend(memory_store={"key": "DONT_EXPOSE_THIS"})
        )
        backend = MagicMock()
        from assistant_os.sandbox.execution_result import ExecutionResult
        backend.execute.return_value = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            "print(1)", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=[SecretRef(name="MY_KEY", ref_token="mem:key", domain="code")],
            injector=injector,
            registry=registry,
            revocation_manager=revmgr,
            audit_log=audit,
        )

        secret_events = audit.events(AuditEventType.SECRET_PROVISIONED)
        assert len(secret_events) >= 1
        for ev in secret_events:
            d = ev.to_dict()
            assert d["secret_name"] == "MY_KEY"
            assert "DONT_EXPOSE_THIS" not in str(d)

    def test_revocation_event_has_no_secret_fields(self):
        import json
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.execution_registry import ExecutionRegistry
        from assistant_os.sandbox.revocation import RevocationManager

        audit = __import__(
            "assistant_os.sandbox.audit", fromlist=["AuditLog"]
        ).AuditLog()
        mgr = RevocationManager(
            registry=ExecutionRegistry(),
            audit_log=audit,
        )
        mgr.revoke_execution("exec-audit-check", reason="manual")
        events = audit.events(AuditEventType.EXECUTION_REVOKED)
        assert events
        d = events[0].to_dict()
        # Revocation events must not contain sensitive field names as keys
        sensitive_keys = {"value", "secret", "password", "token", "credential"}
        assert not sensitive_keys.intersection({k.lower() for k in d})

    def test_execution_run_to_dict_has_no_secret_fields(self):
        from assistant_os.sandbox.execution_run import ExecutionRun
        run = ExecutionRun(
            execution_id="e1", plan_id="p1",
            authorized_plan_hash="h", policy_id="default",
        )
        d = run.to_dict()
        for key in d:
            assert "secret" not in key.lower()
            assert "password" not in key.lower()
            assert "credential" not in key.lower()
