"""
RunnerAPI — governed execution facade for the sandbox subsystem.

This is the single entry point for ALL code executions in AssistantOS.
Nothing should call ContainerBackend directly from outside this package.

Responsibilities
----------------
1.  Validate the execution request (runtime, workspace, authorized_plan).
2.  Register the ExecutionRun in the registry (if provided).
3.  Register the abort signal with RevocationManager (if provided).
4.  Resolve secrets via SecretInjector and provision an ephemeral env file.
5.  Prepare the workspace model.
6.  Write code to workspace/input/<entry_point>.
7.  Emit execution_started audit event.
8.  Delegate to the configured ExecutionBackend with abort_signal + container_name.
9.  Determine outcome (completed / failed / aborted / timeout / internal_error).
10. Update registry status.
11. Emit execution lifecycle audit event (completed / failed / aborted).
12. Guarantee workspace, secret, and signal cleanup in a finally block (always).

Failure normalization contract
-------------------------------
If backend.execute() raises an unhandled exception, RunnerAPI does NOT re-raise.
Instead it:
  - sets termination_reason = INTERNAL_ERROR (distinct from sandbox ERROR/TIMEOUT)
  - creates a normalized ExecutionResult via ExecutionResult.make_internal_error()
  - stamps metadata onto that result in the finally block as usual
  - runs all cleanup steps unconditionally
  - returns the normalized result to the caller

Pre-execution validation failures (bad runtime, missing workspace, invalid plan)
still raise ValueError before any execution work starts.  These are not execution
failures — they are caller contract violations.

Execution lifecycle (normal path)
----------------------------------
    PENDING → RUNNING → COMPLETED | FAILED | ABORTED

Secret lifecycle (within this method)
--------------------------------------
    if secret_refs and injector:
        bundle   = injector.build_env_bundle(secret_refs, plan_id, exec_id)
        env_file = injector.provision_env_file(bundle)
    try:
        backend.execute(..., env_file, abort_signal, container_name)
    finally:
        backend.cleanup()
        workspace_model.cleanup()
        if env_file:
            injector.cleanup_provision(env_file, bundle)   ← deletes file + invalidates

Abort lifecycle
---------------
    revocation_manager.revoke_execution(id)   ← called externally (any thread)
        → sets abort_signal
        → ContainerBackend polls signal → docker stop container
        → backend returns ExecutionResult(error="Execution aborted")
    RunnerAPI.execute() returns normally
        → finally block: cleanup secrets + unregister signal

Secret guarantees
-----------------
- env_file is created in OS temp dir, NOT in workspace.
- env_file is deleted unconditionally in the finally block.
- EnvBundle is invalidated immediately on abort, failure, or completion.
- No secret values stored in ExecutionResult, ExecutionMetadata,
  ArtifactManifest, audit events, or any persisted structure.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .container_backend import ContainerBackend
from .execution_backend import ExecutionBackend
from .execution_result import ExecutionResult
from .output_policy import OUTPUT_POLICY_REGISTRY, OutputPolicy, OutputPolicyEngine
from .workspace_model import WorkspaceModel

if TYPE_CHECKING:
    from ..secrets.injector import SecretInjector
    from ..secrets.secret_ref import EnvBundle, SecretRef
    from .audit import AuditLog
    from .authorized_plan import AuthorizedPlan
    from .execution_registry import ExecutionRegistry
    from .execution_result import ExecutionMetadata
    from .execution_run import ExecutionRun
    from .revocation import RevocationManager

# ---------------------------------------------------------------------------
# Runtime catalog — only these identifiers are accepted.
# ---------------------------------------------------------------------------
ALLOWED_RUNTIMES: frozenset[str] = frozenset({"python3.11"})

_DEFAULT_RUNTIME = "python3.11"
_DEFAULT_ENTRY_POINT = "main.py"
_DEFAULT_TIMEOUT_SECONDS = 30

# Abort error string emitted by ContainerBackend (used for detection)
_ABORT_ERROR_SUBSTR = "aborted"


class RunnerAPI:
    """
    Governed execution facade.

    Parameters
    ----------
    backend         : ExecutionBackend to use.  Defaults to ContainerBackend.
    timeout_seconds : Hard kill limit for all executions via this instance.
    """

    def __init__(
        self,
        backend: Optional[ExecutionBackend] = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._backend = backend or ContainerBackend()
        self._timeout_seconds = timeout_seconds

    def execute(
        self,
        code: str,
        workspace: str,
        runtime: str = _DEFAULT_RUNTIME,
        entry_point: str = _DEFAULT_ENTRY_POINT,
        authorized_plan: Optional["AuthorizedPlan"] = None,
        secret_refs: Optional[list["SecretRef"]] = None,
        injector: Optional["SecretInjector"] = None,
        registry: Optional["ExecutionRegistry"] = None,
        revocation_manager: Optional["RevocationManager"] = None,
        audit_log: Optional["AuditLog"] = None,
    ) -> ExecutionResult:
        """
        Execute Python code in an isolated container.

        Parameters
        ----------
        code               : Python source code to execute.
        workspace          : Absolute path to an existing directory on the host.
        runtime            : Runtime identifier.  Only "python3.11" is (v0).
        entry_point        : Filename inside workspace/input/ to write code to.
        authorized_plan    : Optional authorization binding.  Validated first.
        secret_refs        : Optional list of SecretRefs to inject.
        injector           : SecretInjector — required when secret_refs is set.
        registry           : ExecutionRegistry for lifecycle tracking.
        revocation_manager : RevocationManager for abort control.
        audit_log          : AuditLog for structured event emission.

        Returns
        -------
        ExecutionResult — always, even on abort, timeout, or error.

        Raises
        ------
        ValueError — bad runtime, non-absolute/missing workspace, secrets
                     without injector, or invalid authorized_plan.
        """
        # ------------------------------------------------------------------
        # Phase 1: Validation (cheapest checks first)
        # ------------------------------------------------------------------
        if authorized_plan is not None:
            authorized_plan.validate()

        if secret_refs and not injector:
            raise ValueError(
                "secret_refs provided but injector is None — "
                "cannot resolve secrets without a SecretInjector"
            )

        self._validate_runtime(runtime)
        self._validate_workspace(workspace)

        # ------------------------------------------------------------------
        # Phase 2: Extract identity fields
        # ------------------------------------------------------------------
        execution_id: str = (
            authorized_plan.execution_id if authorized_plan else ""
        )
        plan_id: str = (
            authorized_plan.plan_id if authorized_plan else ""
        )
        container_name: str = f"assistantos-runner-{uuid.uuid4().hex[:12]}"

        # ------------------------------------------------------------------
        # Phase 3: Register ExecutionRun
        # ------------------------------------------------------------------
        run: Optional["ExecutionRun"] = None
        if execution_id:
            # Build run unconditionally so governance fields (authorized_plan_hash,
            # policy_id) reach audit events even when no registry is provided.
            from .execution_run import (  # noqa: PLC0415
                ExecutionRun, ExecutionStatus, TerminationReason,
            )
            run = ExecutionRun(
                execution_id=execution_id,
                plan_id=plan_id,
                authorized_plan_hash=(
                    authorized_plan.authorized_plan_hash
                    if authorized_plan else ""
                ),
                policy_id=(
                    authorized_plan.policy_id if authorized_plan else ""
                ),
                runtime_profile=(
                    authorized_plan.runtime_profile if authorized_plan else runtime
                ),
                container_id=container_name,
            )
            if registry is not None:
                try:
                    registry.register(run)
                except Exception:
                    pass  # Don't nullify run — registry errors must not clear governance context

        # ------------------------------------------------------------------
        # Phase 4: Abort signal + revocation registration
        # ------------------------------------------------------------------
        abort_signal: Optional[threading.Event] = None
        if revocation_manager is not None and execution_id:
            abort_signal = threading.Event()
            revocation_manager.register_abort_signal(
                execution_id, abort_signal, plan_id=plan_id
            )

        # ------------------------------------------------------------------
        # Phase 5: Secret resolution
        # ------------------------------------------------------------------
        env_bundle: Optional["EnvBundle"] = None
        env_file: str = ""

        if secret_refs and injector:
            env_bundle = injector.build_env_bundle(
                secret_refs,
                plan_id=plan_id,
                execution_id=execution_id,
            )
            env_file = injector.provision_env_file(env_bundle)

            # Emit secret audit events (before execution)
            if audit_log:
                _emit_secret_events(audit_log, env_bundle, plan_id, execution_id,
                                    injector, "provisioned")

        # ------------------------------------------------------------------
        # Phase 6: Workspace preparation
        # ------------------------------------------------------------------
        workspace_model = WorkspaceModel(workspace)
        workspace_model.prepare()
        workspace_model.write_code(code, entry_point)

        # ------------------------------------------------------------------
        # Phase 7: Execution with lifecycle tracking
        # ------------------------------------------------------------------
        from .execution_run import ExecutionStatus, TerminationReason  # noqa: PLC0415

        _outcome_status = ExecutionStatus.FAILED
        _outcome_reason = TerminationReason.ERROR
        result: Optional[ExecutionResult] = None

        # Mark RUNNING before starting
        _update_registry(registry, run, ExecutionStatus.RUNNING,
                         TerminationReason.NONE, container_id=container_name)
        _emit_execution_event(audit_log, "started", execution_id, plan_id,
                              "running", "none", run, container_name)

        try:
            self._backend.prepare(workspace)
            result = self._backend.execute(
                workspace_path=workspace,
                entry_point=entry_point,
                timeout_seconds=self._timeout_seconds,
                env_file=env_file,
                abort_signal=abort_signal,
                container_name=container_name,
            )

            # Apply output policy (non-fatal — errors must not mask execution result)
            _apply_output_policy(result, authorized_plan, audit_log, execution_id, plan_id)

            # Collect artifacts before workspace is cleaned up
            _collect_artifacts(result, workspace, audit_log, execution_id, plan_id)

            # Determine outcome from result
            if (abort_signal is not None and abort_signal.is_set()) or (
                result.error is not None
                and _ABORT_ERROR_SUBSTR in (result.error or "").lower()
            ):
                _outcome_status = ExecutionStatus.ABORTED
                _outcome_reason = TerminationReason.REVOKED
            elif result.timed_out:
                _outcome_status = ExecutionStatus.FAILED
                _outcome_reason = TerminationReason.TIMEOUT
            elif result.ok:
                _outcome_status = ExecutionStatus.COMPLETED
                _outcome_reason = TerminationReason.NONE
            else:
                _outcome_status = ExecutionStatus.FAILED
                _outcome_reason = TerminationReason.ERROR

        except Exception as _exc:
            # Normalize hard backend failures — never re-raise from RunnerAPI.
            # Pre-execution validation errors (ValueError from validate()) are raised
            # before this try block and still propagate normally.
            _outcome_status = ExecutionStatus.FAILED
            _outcome_reason = TerminationReason.INTERNAL_ERROR
            if result is None:
                # Backend never returned — create a safe placeholder result.
                result = ExecutionResult.make_internal_error(
                    error=f"{type(_exc).__name__}: {str(_exc)[:200]}"
                )

        finally:
            # ----------------------------------------------------------
            # Phase 8: Unconditional cleanup (always runs)
            # ----------------------------------------------------------
            # 0. Build and stamp execution metadata onto result (before cleanup,
            #    while output_record and manifest are still intact).
            if result is not None:
                try:
                    result.metadata = _build_execution_metadata(
                        authorized_plan=authorized_plan,
                        runtime=runtime,
                        backend_instance=self._backend,
                        result=result,
                        outcome_status=_outcome_status,
                        outcome_reason=_outcome_reason,
                        container_id=container_name,
                    )
                except Exception:
                    pass  # Never mask execution result

            # 1. Container backend cleanup
            self._backend.cleanup(workspace)

            # 2. Workspace cleanup
            workspace_model.cleanup()

            # 3. Secret cleanup — invalidates env_bundle immediately
            if env_file and injector and env_bundle is not None:
                injector.cleanup_provision(env_file, env_bundle)
            elif injector and env_bundle is not None:
                injector.cleanup(env_bundle)

            # 4. Emit secret invalidation event
            if audit_log and env_bundle is not None:
                _emit_secret_events(audit_log, env_bundle, plan_id, execution_id,
                                    injector, "invalidated")

            # 5. Unregister abort signal
            if revocation_manager is not None and execution_id:
                revocation_manager.unregister_abort_signal(execution_id)

            # 6. Update registry to final status
            _update_registry(registry, run, _outcome_status, _outcome_reason,
                             ended_at=time.time())

            # 7. Emit final execution event
            _emit_execution_event(
                audit_log,
                _outcome_status.value,
                execution_id,
                plan_id,
                _outcome_status.value,
                _outcome_reason.value,
                run,
                container_name,
            )

        return result  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_runtime(runtime: str) -> None:
        if runtime not in ALLOWED_RUNTIMES:
            raise ValueError(
                f"Runtime {runtime!r} is not in the allowed catalog. "
                f"Allowed: {sorted(ALLOWED_RUNTIMES)}"
            )

    @staticmethod
    def _validate_workspace(workspace: str) -> None:
        ws = Path(workspace)
        if not ws.is_absolute():
            raise ValueError(
                f"workspace must be an absolute path: {workspace!r}"
            )
        if not ws.exists():
            raise ValueError(
                f"workspace does not exist: {workspace!r}"
            )
        if not ws.is_dir():
            raise ValueError(
                f"workspace is not a directory: {workspace!r}"
            )


# ---------------------------------------------------------------------------
# Private helpers (module-level to keep RunnerAPI.execute() readable)
# ---------------------------------------------------------------------------


def _update_registry(registry, run, status, reason,
                     ended_at=None, container_id=None) -> None:
    """Update registry; silently swallow errors so they don't block execution."""
    if registry is None or run is None:
        return
    try:
        registry.update_status(
            run.execution_id,
            status,
            termination_reason=reason,
            ended_at=ended_at,
            container_id=container_id,
        )
    except Exception:
        pass


def _emit_execution_event(
    audit_log, suffix, execution_id, plan_id,
    status, termination_reason, run, container_name,
) -> None:
    """Emit an ExecutionEvent; silently swallow errors."""
    if audit_log is None or not execution_id:
        return
    try:
        from .audit import AuditEventType, ExecutionEvent  # noqa: PLC0415
        _TYPE_MAP = {
            "started":   AuditEventType.EXECUTION_STARTED,
            "completed": AuditEventType.EXECUTION_COMPLETED,
            "failed":    AuditEventType.EXECUTION_FAILED,
            "aborted":   AuditEventType.EXECUTION_ABORTED,
        }
        event_type = _TYPE_MAP.get(suffix, f"execution_{suffix}")
        audit_log.emit(ExecutionEvent(
            event_type=event_type,
            execution_id=execution_id,
            plan_id=plan_id,
            timestamp=time.time(),
            status=status,
            termination_reason=termination_reason,
            runtime_profile=run.runtime_profile if run else "python3.11",
            container_id=container_name,
            authorized_plan_hash=run.authorized_plan_hash if run else "",
            policy_id=run.policy_id if run else "",
        ))
    except Exception:
        pass


def _emit_secret_events(
    audit_log, env_bundle, plan_id, execution_id, injector, phase,
) -> None:
    """
    Emit SecretAccessEvents for all handles in the bundle.

    phase: "provisioned" | "invalidated"
    Never includes secret values — only name, ref_token, plan_id, execution_id.
    """
    if audit_log is None or env_bundle is None:
        return
    try:
        from .audit import AuditEventType, SecretAccessEvent  # noqa: PLC0415
        _PHASE_TYPE = {
            "provisioned": AuditEventType.SECRET_PROVISIONED,
            "invalidated": AuditEventType.SECRET_INVALIDATED,
        }
        event_type = _PHASE_TYPE.get(phase, f"secret_{phase}")
        backend_name = (
            type(injector._backend).__name__  # noqa: SLF001
            if injector else ""
        )
        for handle in env_bundle.handles:
            audit_log.emit(SecretAccessEvent(
                event_type=event_type,
                secret_name=handle.name,
                ref_token=handle.ref_token,
                plan_id=plan_id,
                execution_id=execution_id,
                timestamp=time.time(),
                backend=backend_name,
            ))
    except Exception:
        pass


def _apply_output_policy(
    result: ExecutionResult,
    authorized_plan: Any,
    audit_log: Any,
    execution_id: str,
    plan_id: str,
) -> None:
    """
    Apply OutputPolicy to result.stdout/stderr.

    Mutates result in-place:
      - result.output_record is populated with the governed OutputRecord.
      - Blocked streams are blanked in result.stdout / result.stderr.
      - result.truncated is updated if policy triggers truncation.

    Errors are silently swallowed — policy failures must not mask execution results.
    """
    try:
        from .audit import AuditEventType, OutputEvent  # noqa: PLC0415

        # Resolve which policy to use (default unless plan specifies otherwise).
        policy_id = authorized_plan.policy_id if authorized_plan else "default"
        policy: OutputPolicy = OUTPUT_POLICY_REGISTRY.get(
            policy_id, OUTPUT_POLICY_REGISTRY["default"]
        )

        output_record, truncated_streams = OutputPolicyEngine.apply(
            result.stdout, result.stderr, policy
        )
        result.output_record = output_record

        # Enforce blocked streams — blank them in result too.
        if not output_record.stdout_persistable():
            result.stdout = ""
        elif output_record.stdout_truncated:
            result.stdout = output_record.stdout

        if not output_record.stderr_persistable():
            result.stderr = ""
        elif output_record.stderr_truncated:
            result.stderr = output_record.stderr

        # Propagate truncation flag.
        if output_record.truncated:
            result.truncated = True

        # Emit an explicit OutputEvent for each truncated/suppressed stream.
        if audit_log and execution_id:
            now = time.time()
            if "stdout" in truncated_streams:
                audit_log.emit(OutputEvent(
                    event_type=AuditEventType.OUTPUT_TRUNCATED,
                    execution_id=execution_id,
                    plan_id=plan_id,
                    timestamp=now,
                    stream="stdout",
                    original_bytes=output_record.stdout_bytes,
                    retained_bytes=len(output_record.stdout),
                    policy_id=output_record.output_policy_id,
                    classification=output_record.stdout_classification,
                ))
            if "stderr" in truncated_streams:
                audit_log.emit(OutputEvent(
                    event_type=AuditEventType.OUTPUT_TRUNCATED,
                    execution_id=execution_id,
                    plan_id=plan_id,
                    timestamp=now,
                    stream="stderr",
                    original_bytes=output_record.stderr_bytes,
                    retained_bytes=len(output_record.stderr),
                    policy_id=output_record.output_policy_id,
                    classification=output_record.stderr_classification,
                ))
    except Exception:
        pass


def _collect_artifacts(
    result: ExecutionResult,
    workspace: str,
    audit_log: Any,
    execution_id: str,
    plan_id: str,
) -> None:
    """
    Collect artifacts from workspace/out/ and emit artifact audit events.

    Mutates result in-place:
      - result.manifest is populated with the ArtifactManifest.
      - result.artifacts list is populated from manifest records.

    Must be called BEFORE workspace cleanup.
    Errors are silently swallowed — artifact collection failures must not
    mask execution results.
    """
    try:
        from .artifact_policy import ArtifactPolicy  # noqa: PLC0415
        from .audit import ArtifactEvent, AuditEventType  # noqa: PLC0415

        manifest = ArtifactPolicy().collect(workspace)
        result.manifest = manifest
        result.artifacts = [r.path for r in manifest.records]

        if audit_log and execution_id:
            now = time.time()
            for record in manifest.records:
                audit_log.emit(ArtifactEvent(
                    event_type=AuditEventType.ARTIFACT_COLLECTED,
                    execution_id=execution_id,
                    plan_id=plan_id,
                    timestamp=now,
                    artifact_path=record.path,
                    size_bytes=record.size_bytes,
                    classification=record.classification,
                    sha256=record.sha256,
                ))
            for rejected in manifest.rejected:
                audit_log.emit(ArtifactEvent(
                    event_type=AuditEventType.ARTIFACT_REJECTED,
                    execution_id=execution_id,
                    plan_id=plan_id,
                    timestamp=now,
                    artifact_path=rejected.get("path", ""),
                    size_bytes=0,
                    rejection_reason=rejected.get("reason", ""),
                ))
    except Exception:
        pass


def _build_execution_metadata(
    authorized_plan: Any,
    runtime: str,
    backend_instance: Any,
    result: "ExecutionResult",
    outcome_status: Any,
    outcome_reason: Any,
    container_id: str,
) -> "ExecutionMetadata":
    """
    Build a fully-populated ExecutionMetadata from all available execution data.

    Called by RunnerAPI in the finally block, after output policy and artifact
    collection have run, so output_record and manifest are already populated.

    Never raises — all fallbacks produce safe empty/zero values.
    """
    from .execution_result import ExecutionMetadata  # noqa: PLC0415

    execution_id = authorized_plan.execution_id if authorized_plan else ""
    plan_id = authorized_plan.plan_id if authorized_plan else ""
    policy_id = authorized_plan.policy_id if authorized_plan else ""
    runtime_profile = (
        authorized_plan.runtime_profile if authorized_plan else runtime
    )
    authorized_plan_hash = (
        authorized_plan.authorized_plan_hash if authorized_plan else ""
    )

    # Stream sizes: prefer governed values from output_record (post-policy).
    if result.output_record is not None:
        stdout_bytes = result.output_record.stdout_bytes
        stderr_bytes = result.output_record.stderr_bytes
    else:
        stdout_bytes = len(result.stdout) if result.stdout else 0
        stderr_bytes = len(result.stderr) if result.stderr else 0

    artifact_count = len(getattr(result.manifest, "records", []))

    return ExecutionMetadata(
        execution_id=execution_id,
        plan_id=plan_id,
        policy_id=policy_id,
        authorized_plan_hash=authorized_plan_hash,
        runtime_profile=runtime_profile,
        duration_ms=result.duration_ms,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        truncated=result.truncated,
        backend=type(backend_instance).__name__,
        status=outcome_status.value if hasattr(outcome_status, "value") else str(outcome_status),
        termination_reason=outcome_reason.value if hasattr(outcome_reason, "value") else str(outcome_reason),
        container_id=container_id,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        artifact_count=artifact_count,
    )
