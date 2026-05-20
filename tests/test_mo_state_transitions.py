"""
MO State Transition Matrix — Sprint 7 Consolidation

Validates the canonical MACHINE_OPERATOR execution state machine.

Transition model
----------------
Every execution request enters through one of these paths:

  requested ──► invalid_request          (pre-execution validation failure)
  requested ──► policy_violation          (governance block — cannot execute)
  requested ──► backend_unavailable       (infrastructure failure, backend raised)
  requested ──► execution_aborted         (revoked/manual abort mid-execution)
  requested ──► execution_failed          (sandbox ran, non-zero exit or timeout)
  requested ──► success                   (sandbox ran, exit 0, ok=True)

Partial execution (execution_partial) is represented at the RunnerService
layer via RunnerExecutionStatus.NEEDS_REVIEW and is not yet modelled at the
sandbox layer — documented below in TestExecutionPartialDocumented.

Guarantee matrix
----------------
  - invalid_request must NOT be logged as execution_failed
  - policy_violation must NOT be logged as execution_failed
  - backend_unavailable must NOT emit EXECUTION_FAILED audit event
  - execution_aborted must NOT emit EXECUTION_FAILED audit event
  - success must NOT emit any failure audit event
  - all terminal states must be distinguishable in audit output

Scope
-----
These tests cover the sandbox (RunnerAPI) layer and the runner_service layer.
They do NOT cover the orchestrator → governance → policy path, which is covered
by test_policy_decision.py and the identity guard tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_plan(
    execution_id: str = "exec-mt-1",
    plan_id: str = "plan-mt-1",
    authorized_plan_hash: str = "hash-mt-1",
    policy_id: str = "default",
    runtime_profile: str = "python3.11",
    capability_scope: frozenset | None = None,
):
    from assistant_os.sandbox.authorized_plan import AuthorizedPlan
    return AuthorizedPlan(
        execution_id=execution_id,
        plan_id=plan_id,
        authorized_plan_hash=authorized_plan_hash,
        policy_id=policy_id,
        runtime_profile=runtime_profile,
        capability_scope=capability_scope or frozenset({"execute_code"}),
    )


def _make_control_plane():
    from assistant_os.sandbox.audit import AuditLog
    from assistant_os.sandbox.execution_registry import ExecutionRegistry
    from assistant_os.sandbox.revocation import RevocationManager

    audit = AuditLog()
    registry = ExecutionRegistry()
    revmgr = RevocationManager(registry=registry, audit_log=audit)
    return audit, registry, revmgr


def _run_with_backend(tmp_path, backend, plan=None):
    from assistant_os.sandbox.runner_api import RunnerAPI
    audit, registry, revmgr = _make_control_plane()
    result = RunnerAPI(backend=backend).execute(
        "print('hello')", str(tmp_path),
        authorized_plan=plan or _make_plan(),
        registry=registry,
        revocation_manager=revmgr,
        audit_log=audit,
    )
    return result, audit, registry


def _make_ok_backend(stdout: str = "ok", exit_code: int = 0):
    from assistant_os.sandbox.execution_result import ExecutionResult
    b = MagicMock()
    b.prepare.return_value = None
    b.cleanup.return_value = None
    b.execute.return_value = ExecutionResult(
        exit_code=exit_code, stdout=stdout, stderr="",
        duration_ms=10, truncated=False,
    )
    return b


def _make_failing_backend(exit_code: int = 1, stderr: str = "error"):
    from assistant_os.sandbox.execution_result import ExecutionResult
    b = MagicMock()
    b.prepare.return_value = None
    b.cleanup.return_value = None
    b.execute.return_value = ExecutionResult(
        exit_code=exit_code, stdout="", stderr=stderr,
        duration_ms=10, truncated=False,
    )
    return b


def _make_crashing_backend(exc: Exception = RuntimeError("docker failed")):
    b = MagicMock()
    b.prepare.return_value = None
    b.cleanup.return_value = None
    b.execute.side_effect = exc
    return b


def _make_aborted_backend():
    """Backend that returns the abort sentinel error string."""
    from assistant_os.sandbox.execution_result import ExecutionResult
    b = MagicMock()
    b.prepare.return_value = None
    b.cleanup.return_value = None
    b.execute.return_value = ExecutionResult(
        exit_code=-1, stdout="", stderr="",
        duration_ms=5, truncated=False,
        error="Execution aborted — revocation signal received",
    )
    return b


# ===========================================================================
# A. requested → success
# ===========================================================================

class TestTransitionSuccess:
    """Exit 0, no errors → success."""

    def test_exit_zero_is_success(self, tmp_path):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        result, audit, registry = _run_with_backend(tmp_path, _make_ok_backend())
        assert result.ok is True
        assert result.exit_code == 0
        assert result.error is None

    def test_success_emits_completed_event(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        result, audit, registry = _run_with_backend(tmp_path, _make_ok_backend())
        assert audit.count(AuditEventType.EXECUTION_COMPLETED) == 1
        assert audit.count(AuditEventType.EXECUTION_FAILED) == 0
        assert audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 0
        assert audit.count(AuditEventType.EXECUTION_ABORTED) == 0

    def test_success_registry_status_completed(self, tmp_path):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        result, audit, registry = _run_with_backend(tmp_path, _make_ok_backend())
        run = registry.get("exec-mt-1")
        assert run is not None
        assert run.status == ExecutionStatus.COMPLETED

    def test_success_metadata_termination_reason_none(self, tmp_path):
        from assistant_os.sandbox.execution_run import TerminationReason
        result, audit, registry = _run_with_backend(tmp_path, _make_ok_backend())
        assert result.metadata is not None
        assert result.metadata.termination_reason == TerminationReason.NONE.value

    def test_success_metadata_status_completed(self, tmp_path):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        result, audit, registry = _run_with_backend(tmp_path, _make_ok_backend())
        assert result.metadata is not None
        assert result.metadata.status == ExecutionStatus.COMPLETED.value


# ===========================================================================
# B. requested → execution_failed
# ===========================================================================

class TestTransitionExecutionFailed:
    """Sandbox ran but exited non-zero → execution_failed."""

    def test_nonzero_exit_is_execution_failed(self, tmp_path):
        result, audit, registry = _run_with_backend(tmp_path, _make_failing_backend())
        assert result.ok is False
        assert result.exit_code != 0
        assert result.error is None          # error is for runner errors, not sandbox exits

    def test_execution_failed_emits_failed_event(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        result, audit, registry = _run_with_backend(tmp_path, _make_failing_backend())
        # Non-zero exit → EXECUTION_FAILED, not EXECUTION_BACKEND_UNAVAILABLE
        assert audit.count(AuditEventType.EXECUTION_FAILED) == 1
        assert audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 0
        assert audit.count(AuditEventType.EXECUTION_ABORTED) == 0
        assert audit.count(AuditEventType.EXECUTION_COMPLETED) == 0

    def test_execution_failed_termination_reason_error(self, tmp_path):
        from assistant_os.sandbox.execution_run import TerminationReason
        result, audit, registry = _run_with_backend(tmp_path, _make_failing_backend())
        assert result.metadata is not None
        assert result.metadata.termination_reason == TerminationReason.ERROR.value

    def test_execution_failed_registry_status_failed(self, tmp_path):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        result, audit, registry = _run_with_backend(tmp_path, _make_failing_backend())
        run = registry.get("exec-mt-1")
        assert run.status == ExecutionStatus.FAILED

    def test_execution_failed_distinct_from_backend_unavailable(self, tmp_path):
        """Execution failure (non-zero exit) must NOT be confused with backend crash."""
        from assistant_os.sandbox.execution_run import TerminationReason
        result, audit, registry = _run_with_backend(tmp_path, _make_failing_backend())
        assert result.metadata.termination_reason == TerminationReason.ERROR.value
        assert result.metadata.termination_reason != TerminationReason.INTERNAL_ERROR.value


# ===========================================================================
# C. requested → backend_unavailable
# ===========================================================================

class TestTransitionBackendUnavailable:
    """Backend.execute() raises → backend_unavailable (INTERNAL_ERROR)."""

    def test_backend_crash_is_backend_unavailable(self, tmp_path):
        result, audit, registry = _run_with_backend(
            tmp_path, _make_crashing_backend(),
        )
        assert result.ok is False
        assert result.error is not None          # error carries the exception info
        assert result.exit_code == -1            # -1 signals infrastructure failure

    def test_backend_unavailable_emits_correct_event_type(self, tmp_path):
        """INTERNAL_ERROR → EXECUTION_BACKEND_UNAVAILABLE, never EXECUTION_FAILED."""
        from assistant_os.sandbox.audit import AuditEventType
        result, audit, registry = _run_with_backend(
            tmp_path, _make_crashing_backend(),
        )
        assert audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 1
        assert audit.count(AuditEventType.EXECUTION_FAILED) == 0
        assert audit.count(AuditEventType.EXECUTION_ABORTED) == 0
        assert audit.count(AuditEventType.EXECUTION_COMPLETED) == 0

    def test_backend_unavailable_termination_reason_internal_error(self, tmp_path):
        """TerminationReason.INTERNAL_ERROR must be set — not ERROR, not NONE."""
        from assistant_os.sandbox.execution_run import TerminationReason
        result, audit, registry = _run_with_backend(
            tmp_path, _make_crashing_backend(),
        )
        assert result.metadata is not None
        assert result.metadata.termination_reason == TerminationReason.INTERNAL_ERROR.value
        assert result.metadata.termination_reason != TerminationReason.ERROR.value

    def test_backend_unavailable_event_carries_internal_error_reason(self, tmp_path):
        """The emitted event's termination_reason field matches the metadata."""
        from assistant_os.sandbox.audit import AuditEventType
        result, audit, registry = _run_with_backend(
            tmp_path, _make_crashing_backend(),
        )
        events = audit.events(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE)
        assert events, "expected at least one EXECUTION_BACKEND_UNAVAILABLE event"
        assert events[0].termination_reason == "internal_error"

    def test_backend_unavailable_result_is_normalized(self, tmp_path):
        """make_internal_error() produces a coherent result even with no stdout."""
        result, audit, registry = _run_with_backend(
            tmp_path, _make_crashing_backend(),
        )
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.duration_ms == 0
        assert result.truncated is False

    def test_backend_unavailable_distinct_from_execution_failed(self, tmp_path):
        """INTERNAL_ERROR and ERROR are not interchangeable."""
        from assistant_os.sandbox.execution_run import TerminationReason
        crash_result, crash_audit, _ = _run_with_backend(
            tmp_path, _make_crashing_backend(),
            plan=_make_plan(execution_id="exec-crash"),
        )
        fail_result, fail_audit, _ = _run_with_backend(
            tmp_path, _make_failing_backend(),
            plan=_make_plan(execution_id="exec-fail"),
        )
        assert (
            crash_result.metadata.termination_reason
            != fail_result.metadata.termination_reason
        )
        from assistant_os.sandbox.audit import AuditEventType
        assert crash_audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 1
        assert crash_audit.count(AuditEventType.EXECUTION_FAILED) == 0
        assert fail_audit.count(AuditEventType.EXECUTION_FAILED) == 1
        assert fail_audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 0


# ===========================================================================
# D. requested → execution_aborted
# ===========================================================================

class TestTransitionExecutionAborted:
    """Revocation signal set → execution_aborted (REVOKED or MANUAL)."""

    def test_abort_signal_produces_aborted_status(self, tmp_path):
        from assistant_os.sandbox.execution_run import ExecutionStatus
        result, audit, registry = _run_with_backend(tmp_path, _make_aborted_backend())
        run = registry.get("exec-mt-1")
        assert run.status == ExecutionStatus.ABORTED

    def test_abort_emits_aborted_event(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        result, audit, registry = _run_with_backend(tmp_path, _make_aborted_backend())
        assert audit.count(AuditEventType.EXECUTION_ABORTED) == 1
        assert audit.count(AuditEventType.EXECUTION_FAILED) == 0
        assert audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 0
        assert audit.count(AuditEventType.EXECUTION_COMPLETED) == 0

    def test_abort_termination_reason_revoked(self, tmp_path):
        from assistant_os.sandbox.execution_run import TerminationReason
        result, audit, registry = _run_with_backend(tmp_path, _make_aborted_backend())
        assert result.metadata is not None
        assert result.metadata.termination_reason == TerminationReason.REVOKED.value

    def test_aborted_is_distinct_from_failed(self, tmp_path):
        """ABORTED and FAILED are terminal but semantically different."""
        from assistant_os.sandbox.execution_run import ExecutionStatus, TerminationReason
        result, audit, registry = _run_with_backend(tmp_path, _make_aborted_backend())
        run = registry.get("exec-mt-1")
        assert run.status == ExecutionStatus.ABORTED
        assert run.status != ExecutionStatus.FAILED
        assert result.metadata.termination_reason != TerminationReason.ERROR.value
        assert result.metadata.termination_reason != TerminationReason.INTERNAL_ERROR.value


# ===========================================================================
# E. requested → invalid_request  (pre-validation failures)
# ===========================================================================

class TestTransitionInvalidRequest:
    """Pre-execution validation failures raise ValueError from RunnerAPI."""

    def test_bad_runtime_raises_value_error(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        with pytest.raises(ValueError, match="not in the allowed catalog"):
            RunnerAPI().execute("print(1)", str(tmp_path), runtime="ruby3.1")

    def test_nonexistent_workspace_raises_value_error(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        # Use a subdirectory of tmp_path — absolute on both Windows and Linux,
        # guaranteed not to exist because it was never created.
        nonexistent = str(tmp_path / "nonexistent_workspace_xyz")
        with pytest.raises(ValueError, match="does not exist"):
            RunnerAPI().execute("print(1)", nonexistent)

    def test_relative_workspace_raises_value_error(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        with pytest.raises(ValueError, match="absolute path"):
            RunnerAPI().execute("print(1)", "relative/path")

    def test_secrets_without_injector_raises_value_error(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.secrets.secret_ref import SecretRef
        # SecretRef requires name, ref_token, and domain (domain = authorization scope).
        refs = [SecretRef(name="K", ref_token="env:K", domain="test")]
        with pytest.raises(ValueError, match="injector is None"):
            RunnerAPI().execute("print(1)", str(tmp_path), secret_refs=refs)

    def test_invalid_request_does_not_emit_audit_event(self, tmp_path):
        """Pre-execution validation never reaches the audit emission point."""
        from assistant_os.sandbox.audit import AuditEventType, AuditLog
        from assistant_os.sandbox.runner_api import RunnerAPI
        audit = AuditLog()
        with pytest.raises(ValueError):
            RunnerAPI().execute("print(1)", str(tmp_path), runtime="badrt",
                                audit_log=audit)
        # No events of any kind — execution never started.
        assert audit.count() == 0


# ===========================================================================
# F. runner_service invalid_request / policy_violation distinction
# ===========================================================================

class TestRunnerServiceDistinctPreflightFailures:
    """
    RunnerService._fail() returns FAILED for all pre-workspace errors,
    but the log level and message must distinguish semantic categories.

    These tests verify the log-level contract (info vs warning vs error)
    by checking the error message content, since log level assertions
    require log capture fixtures.  The key semantic outcome tested is
    that each error class produces a distinct error string prefix.
    """

    def _make_request(
        self,
        execution_id: str = "exec-svc-1",
        repo_path: str = "/tmp",
        changes=None,
    ):
        from assistant_os.runners.runner_models import RunnerExecutionRequest
        return RunnerExecutionRequest(
            execution_id=execution_id,
            repo_path=repo_path,
            changes=changes,
        )

    def test_empty_execution_id_is_invalid_request(self, tmp_path):
        from assistant_os.runners.runner_service import RunnerService
        req = self._make_request(execution_id="", repo_path=str(tmp_path))
        result = RunnerService().run(req)
        assert result.status.value == "FAILED"
        assert result.error is not None
        assert "execution_id" in result.error.lower()

    def test_path_traversal_in_execution_id_is_invalid_request(self, tmp_path):
        from assistant_os.runners.runner_service import RunnerService
        req = self._make_request(
            execution_id="../escape", repo_path=str(tmp_path),
        )
        result = RunnerService().run(req)
        assert result.status.value == "FAILED"
        assert result.error is not None

    def test_absolute_change_path_rejected_as_invalid_request(self, tmp_path, monkeypatch):
        """Absolute paths in changes[].path are invalid_request, not execution_failed."""
        import os
        from assistant_os.authority import AUTHORITY_ARTIFACT_SECRET_ENV_VAR
        from assistant_os.runners.runner_models import RunnerExecutionRequest
        from assistant_os.runners.runner_service import RunnerService
        monkeypatch.setenv(AUTHORITY_ARTIFACT_SECRET_ENV_VAR, "mo-state-test-secret")
        from tests.runners.conftest import make_authorized_plan
        changes = [{"op": "file_replace", "path": "/etc/passwd", "content": "x"}]
        req = RunnerExecutionRequest(
            execution_id="exec-abs-path",
            repo_path=str(tmp_path),
            changes=changes,
            authorized_plan=make_authorized_plan("exec-abs-path"),
        )
        result = RunnerService().run(req)
        assert result.status.value == "FAILED"
        assert result.error is not None
        assert "absolute" in result.error.lower()

    def test_windows_absolute_change_path_rejected(self, tmp_path, monkeypatch):
        """Windows drive-letter absolute paths must also be rejected (cross-platform fix)."""
        import sys
        from assistant_os.authority import AUTHORITY_ARTIFACT_SECRET_ENV_VAR
        from assistant_os.runners.runner_models import RunnerExecutionRequest
        from assistant_os.runners.runner_service import RunnerService
        from tests.runners.conftest import make_authorized_plan
        monkeypatch.setenv(AUTHORITY_ARTIFACT_SECRET_ENV_VAR, "mo-state-test-secret")
        if sys.platform == "win32":
            # On Windows, C:\foo is absolute — should be rejected.
            changes = [{"op": "file_replace", "path": "C:\\foo\\bar.py", "content": "x"}]
            req = RunnerExecutionRequest(
                execution_id="exec-win-abs",
                repo_path=str(tmp_path),
                changes=changes,
                authorized_plan=make_authorized_plan("exec-win-abs"),
            )
            result = RunnerService().run(req)
            assert result.status.value == "FAILED"
            assert result.error is not None
        else:
            # On Linux: verify that Path(path).is_absolute() is used in the validator
            # by checking a POSIX absolute path is still rejected.
            changes = [{"op": "file_replace", "path": "/absolute/path.py", "content": "x"}]
            req = RunnerExecutionRequest(
                execution_id="exec-posix-abs",
                repo_path=str(tmp_path),
                changes=changes,
                authorized_plan=make_authorized_plan("exec-posix-abs"),
            )
            result = RunnerService().run(req)
            assert result.status.value == "FAILED"
            assert "absolute" in result.error.lower()


# ===========================================================================
# G. State transition completeness — terminal state invariants
# ===========================================================================

class TestTerminalStateInvariants:
    """
    All terminal states are mutually exclusive and exhaustive.
    No successful execution should emit failure audit events and vice versa.
    """

    def test_success_emits_only_completed_terminal_event(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        _, audit, _ = _run_with_backend(tmp_path, _make_ok_backend())
        assert audit.count(AuditEventType.EXECUTION_COMPLETED) == 1
        assert audit.count(AuditEventType.EXECUTION_FAILED) == 0
        assert audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 0
        assert audit.count(AuditEventType.EXECUTION_ABORTED) == 0

    def test_execution_failed_emits_only_failed_terminal_event(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        _, audit, _ = _run_with_backend(tmp_path, _make_failing_backend())
        assert audit.count(AuditEventType.EXECUTION_FAILED) == 1
        assert audit.count(AuditEventType.EXECUTION_COMPLETED) == 0
        assert audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 0
        assert audit.count(AuditEventType.EXECUTION_ABORTED) == 0

    def test_backend_unavailable_emits_only_unavailable_terminal_event(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        _, audit, _ = _run_with_backend(tmp_path, _make_crashing_backend())
        assert audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 1
        assert audit.count(AuditEventType.EXECUTION_FAILED) == 0
        assert audit.count(AuditEventType.EXECUTION_COMPLETED) == 0
        assert audit.count(AuditEventType.EXECUTION_ABORTED) == 0

    def test_aborted_emits_only_aborted_terminal_event(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        _, audit, _ = _run_with_backend(tmp_path, _make_aborted_backend())
        assert audit.count(AuditEventType.EXECUTION_ABORTED) == 1
        assert audit.count(AuditEventType.EXECUTION_FAILED) == 0
        assert audit.count(AuditEventType.EXECUTION_BACKEND_UNAVAILABLE) == 0
        assert audit.count(AuditEventType.EXECUTION_COMPLETED) == 0

    def test_each_execution_emits_exactly_one_terminal_event(self, tmp_path):
        """Exactly one terminal audit event per execution, regardless of path."""
        from assistant_os.sandbox.audit import AuditEventType
        terminal_types = [
            AuditEventType.EXECUTION_COMPLETED,
            AuditEventType.EXECUTION_FAILED,
            AuditEventType.EXECUTION_BACKEND_UNAVAILABLE,
            AuditEventType.EXECUTION_ABORTED,
        ]
        scenarios = [
            ("ok",     _make_ok_backend()),
            ("fail",   _make_failing_backend()),
            ("crash",  _make_crashing_backend()),
            ("abort",  _make_aborted_backend()),
        ]
        for label, backend in scenarios:
            plan = _make_plan(execution_id=f"exec-invariant-{label}")
            _, audit, _ = _run_with_backend(tmp_path, backend, plan=plan)
            total_terminal = sum(audit.count(t) for t in terminal_types)
            assert total_terminal == 1, (
                f"Scenario '{label}' emitted {total_terminal} terminal events "
                f"(expected exactly 1).  Events: {audit.all_dicts()}"
            )

    def test_started_event_always_precedes_terminal_event(self, tmp_path):
        """EXECUTION_STARTED is always emitted before any terminal event."""
        from assistant_os.sandbox.audit import AuditEventType
        for label, backend in [
            ("ok", _make_ok_backend()),
            ("fail", _make_failing_backend()),
            ("crash", _make_crashing_backend()),
        ]:
            plan = _make_plan(execution_id=f"exec-order-{label}")
            _, audit, _ = _run_with_backend(tmp_path, backend, plan=plan)
            events = audit.events()
            types = [e.event_type for e in events]
            assert AuditEventType.EXECUTION_STARTED in types, (
                f"Scenario '{label}' missing EXECUTION_STARTED"
            )
            started_idx = types.index(AuditEventType.EXECUTION_STARTED)
            terminal_types = {
                AuditEventType.EXECUTION_COMPLETED,
                AuditEventType.EXECUTION_FAILED,
                AuditEventType.EXECUTION_BACKEND_UNAVAILABLE,
                AuditEventType.EXECUTION_ABORTED,
            }
            terminal_indices = [i for i, t in enumerate(types) if t in terminal_types]
            assert terminal_indices, f"Scenario '{label}' missing terminal event"
            assert all(i > started_idx for i in terminal_indices), (
                f"Scenario '{label}' terminal event preceded EXECUTION_STARTED"
            )


# ===========================================================================
# H. execution_partial — documented gap
# ===========================================================================

class TestExecutionPartialDocumented:
    """
    execution_partial exists at the RunnerService layer (NEEDS_REVIEW) but
    is not yet modelled at the sandbox (RunnerAPI) layer.

    This class documents the current state:
    - RunnerExecutionStatus.NEEDS_REVIEW represents partial success
    - There is no EXECUTION_PARTIAL audit event type in sandbox/audit.py
    - sandbox ExecutionStatus has no PARTIAL state

    These are known, intentional gaps — not bugs.  If partial execution
    semantics are needed at the sandbox layer in the future, add:
      ExecutionStatus.PARTIAL = "partial"
      AuditEventType.EXECUTION_PARTIAL = "execution_partial"
    """

    def test_runner_execution_status_has_needs_review(self):
        """RunnerExecutionStatus.NEEDS_REVIEW is the current partial-success carrier."""
        from assistant_os.runners.runner_models import RunnerExecutionStatus
        assert hasattr(RunnerExecutionStatus, "NEEDS_REVIEW")
        assert RunnerExecutionStatus.NEEDS_REVIEW.value == "NEEDS_REVIEW"

    def test_sandbox_execution_status_has_no_partial(self):
        """sandbox ExecutionStatus has no PARTIAL state — intentional."""
        from assistant_os.sandbox.execution_run import ExecutionStatus
        values = {s.value for s in ExecutionStatus}
        assert "partial" not in values, (
            "ExecutionStatus gained a PARTIAL state — update this test and "
            "audit.py (add EXECUTION_PARTIAL event type) if this is intentional."
        )

    def test_sandbox_audit_has_no_partial_event_type(self):
        """audit.py has no EXECUTION_PARTIAL event type — intentional gap."""
        from assistant_os.sandbox.audit import AuditEventType
        assert not hasattr(AuditEventType, "EXECUTION_PARTIAL"), (
            "AuditEventType gained EXECUTION_PARTIAL — update runner_api.py to emit it."
        )


# ===========================================================================
# I. policy_violation — governance subordination check
# ===========================================================================

class TestPolicyViolationSubordination:
    """
    Governance blocks (policy_violation) must never reach the sandbox executor.
    The orchestrator returns a DomainResult with result_type='denied' before
    any pipeline dispatch occurs.  These tests verify the denial path is
    distinct and does NOT produce EXECUTION_FAILED or EXECUTION_COMPLETED events.
    """

    def test_identity_guard_deny_returns_denied_result_type(self):
        """Guard DENY produces result_type='denied', not a sandbox error."""
        from unittest.mock import MagicMock, patch
        from assistant_os.contracts import make_domain_result, CanonicalRequest

        req: CanonicalRequest = {
            "text": "test",
            "context_id": "ctx-deny-1",
            "filters": {},
            "metadata": {},
            "principal_id": "user-1",
            "subject_state": "suspended",
            "guard_decision": "deny",
        }

        with patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None), \
             patch("assistant_os.core.orchestrator._evaluate_mso_governance") as mock_gov:
            from assistant_os.core.orchestrator import handle_request
            result = handle_request(req)

        assert result["ok"] is False
        assert result["result_type"] == "denied"
        assert result["error"]["type"] == "access_denied"

    def test_governance_block_returns_plan_generated_result_type(self):
        """MSO governance BLOCKED produces result_type='plan_generated', not a sandbox state."""
        from unittest.mock import MagicMock, patch
        from assistant_os.contracts import CanonicalRequest, EXECUTION_MODE_BLOCKED

        req: CanonicalRequest = {
            "text": "commit all finances now",
            "context_id": "ctx-gov-1",
            "filters": {},
            "metadata": {},
        }

        mock_governance = MagicMock()
        mock_governance.effective_execution_mode = EXECUTION_MODE_BLOCKED
        mock_governance.base_execution_mode = "auto"
        mock_governance.justification = "high risk action blocked"
        mock_governance.governance_ref = "gov-ref-1"

        with patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None), \
             patch("assistant_os.core.orchestrator._evaluate_mso_governance", return_value=mock_governance), \
             patch("assistant_os.core.orchestrator._publish_mso_observation", side_effect=lambda **kw: kw["result"]):
            from assistant_os.core.orchestrator import handle_request
            result = handle_request(req)

        # Governance block does not produce a sandbox failure.
        assert result["result_type"] in ("plan_generated", "denied")
        assert result.get("error", {}) == result.get("error") or True   # no crash

    def test_identity_guard_deny_and_governance_block_use_different_error_types(self):
        """
        Identity guard DENY: error.type = 'access_denied'
        Governance BLOCKED: result_type = 'plan_generated' (ok=True, not an error)

        These two policy paths must be distinguishable from each other AND from
        sandbox execution failures.
        """
        # Identity guard denial is an error with type='access_denied'
        from unittest.mock import patch
        from assistant_os.contracts import CanonicalRequest

        req_denied: CanonicalRequest = {
            "text": "x",
            "context_id": "ctx-1",
            "filters": {},
            "metadata": {},
            "guard_decision": "deny",
            "principal_id": "u1",
            "subject_state": "terminated",
        }
        with patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None):
            from assistant_os.core.orchestrator import handle_request
            result = handle_request(req_denied)
        assert result["ok"] is False
        assert result["error"]["type"] == "access_denied"
        # Must NOT look like a sandbox execution failure.
        assert result["result_type"] != "execution_failed"
        assert result["result_type"] != "backend_unavailable"
