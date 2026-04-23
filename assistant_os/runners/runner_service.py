"""
RunnerService — Slice 4 / M1B.

Orchestrates the full Runner pipeline:
    preflight → workspace → apply → sandbox (RunnerAPI/Docker) → test → validate → report → notify → result

Design notes:
  - Only pre-workspace failures return early (no artifacts dir to write to).
  - Apply and test errors do NOT return early — they accumulate state and the
    loop always closes through validation → report → notify.
  - All phases after workspace are wrapped individually so a failure in
    (e.g.) report cannot destroy the test result already captured.
  - M1B: when request.authorized_plan and request.code are both set, a Phase 2.5
    sandbox execution via RunnerAPI (Docker) is inserted after apply and before test.
    The sandbox uses an isolated _sandbox/ sub-directory, not the workspace root.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple

from .apply_engine import ApplyEngine
from .authority_consumption_registry import AuthorityConsumptionRegistry
from .errors import (
    ApplyError,
    PolicyViolationError,
    PreflightError,
    TestExecutionError,
    WorkspacePreparationError,
)
from .notification_engine import NotificationEngine
from .report_builder import ReportBuilder
from .runner_models import (
    RunnerExecutionRequest,
    RunnerExecutionResult,
    RunnerExecutionStatus,
    TestExecutionResult,
    ValidationResult,
)
from .test_engine import TestEngine
from .validation_engine import ValidationEngine
from .workspace_manager import PreparedWorkspace, _append_log, log_preflight_failure, prepare_workspace

if TYPE_CHECKING:
    from ..sandbox.audit_store import AuditStore
    from ..sandbox.execution_registry import ExecutionRegistry
    from ..sandbox.runner_api import RunnerAPI

logger = logging.getLogger(__name__)


def _promote_changes(
    workspace_path: Path,
    repo_root: str,
    modified_files: List[str],
    log_file: Path,
) -> Tuple[List[str], str]:
    """Copy modified files from sandbox workspace back to original repo.

    Returns (promoted_files, status) where status is one of:
        "performed" — at least one file was copied successfully
        "skipped"   — modified_files was empty, nothing to promote
        "failed"    — all promotion attempts failed
    """
    if not modified_files:
        return [], "skipped"

    repo = Path(repo_root).resolve()
    ws = workspace_path.resolve()
    promoted: List[str] = []

    for rel in modified_files:
        rel_path = Path(rel)
        # Safety: reject absolute paths and path-traversal components.
        if rel_path.is_absolute() or ".." in rel_path.parts:
            _append_log(log_file, f"promote: skipped {rel!r} — path traversal rejected")
            continue

        src = ws / rel_path
        dst = repo / rel_path

        # Verify resolved paths stay within their respective roots.
        try:
            src.resolve().relative_to(ws)
            dst.resolve().relative_to(repo)
        except ValueError:
            _append_log(log_file, f"promote: skipped {rel!r} — outside boundary")
            continue

        if not src.is_file():
            _append_log(log_file, f"promote: skipped {rel!r} — not found in workspace")
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            promoted.append(rel)
            _append_log(log_file, f"promote: {rel!r} → repo")
        except OSError as exc:
            _append_log(log_file, f"promote: failed {rel!r} — {exc}")
            logger.warning("Promotion failed for %r: %s", rel, exc)

    if not promoted:
        return [], "failed"
    return promoted, "performed"


# Path to the persistent audit log for all sandbox executions.
# Sibling of executions/ under var/runner/.
_AUDIT_STORE_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "var" / "runner" / "audit.jsonl"
)


class RunnerService:
    """Orchestrator for the full Runner pipeline (Slice 4 / M1B).

    Parameters
    ----------
    runner_api : RunnerAPI instance for Docker-based sandbox execution.
                 If None, a default RunnerAPI (ContainerBackend) is created.
    registry   : ExecutionRegistry for lifecycle tracking.
                 If None, a new registry is created per-service instance.
    audit_store: Persistent AuditStore.
                 If None, an AuditStore writing to _AUDIT_STORE_PATH is created.

    All three parameters accept None to enable easy test injection while
    giving production code sensible defaults on construction.
    """

    def __init__(
        self,
        runner_api: Optional["RunnerAPI"] = None,
        registry: Optional["ExecutionRegistry"] = None,
        audit_store: Optional["AuditStore"] = None,
    ) -> None:
        from ..sandbox.runner_api import RunnerAPI as _RunnerAPI  # noqa: PLC0415
        from ..sandbox.execution_registry import ExecutionRegistry as _Registry  # noqa: PLC0415
        from ..sandbox.audit_store import AuditStore as _AuditStore  # noqa: PLC0415

        self._runner_api: RunnerAPI = runner_api or _RunnerAPI()
        self._registry: ExecutionRegistry = registry or _Registry()
        self._audit_store: AuditStore = audit_store or _AuditStore(_AUDIT_STORE_PATH)
        self._authority_consumption_registry = AuthorityConsumptionRegistry()

    def run(self, request: RunnerExecutionRequest) -> RunnerExecutionResult:
        """Execute the complete pipeline for *request*.

        Flow:
            1. Preflight validation.
            2. Workspace preparation.
            3. Apply changes (if request.changes).
            2.5. Sandbox execution via RunnerAPI/Docker (if authorized_plan + code present).
            4. Run tests (if request.test_spec and apply/sandbox succeeded).
            5. Validate final state.
            6. Build report.
            7. Notify.
            8. Return complete result.
        """
        started_at = datetime.now(timezone.utc)

        # ------------------------------------------------------------------
        # Phase 1: workspace (only early-return path — no artifacts dir yet)
        # ------------------------------------------------------------------
        try:
            self._preflight(request)
            workspace: PreparedWorkspace = prepare_workspace(request)
        except PreflightError as exc:
            # invalid_request — caller supplied a malformed or structurally invalid request.
            logger.info(
                "Runner execution %s rejected (invalid_request): %s",
                request.execution_id, exc,
            )
            return self._fail(request, started_at, str(exc))
        except PolicyViolationError as exc:
            # policy_violation — request conflicts with a Runner enforcement policy.
            logger.warning(
                "Runner execution %s rejected (policy_violation): %s",
                request.execution_id, exc,
            )
            return self._fail(request, started_at, str(exc))
        except WorkspacePreparationError as exc:
            # backend_unavailable — infrastructure failure during workspace setup.
            logger.error(
                "Runner execution %s failed (backend_unavailable): %s",
                request.execution_id, exc,
            )
            return self._fail(request, started_at, str(exc))
        except Exception as exc:
            logger.exception("Unexpected error during workspace preparation")
            return self._fail(request, started_at, f"Internal error: {exc}")

        log_file = Path(workspace.artifacts_path) / "runner.log"
        workspace_path = Path(workspace.workspace_path)

        # ------------------------------------------------------------------
        # Phase 2: apply
        # ------------------------------------------------------------------
        modified_files: List[str] = []
        changes_detail: List[Dict[str, Any]] = []
        apply_error: Optional[str] = None

        if request.changes:
            _append_log(log_file, "phase: APPLY_START")
            try:
                modified_files, changes_detail = ApplyEngine().apply_changes_with_audit(
                    workspace_path=workspace_path,
                    changes=request.changes,
                    log_file=log_file,
                )
                _append_log(log_file, "phase: APPLY_DONE")
            except (ApplyError, PolicyViolationError) as exc:
                apply_error = str(exc)
                _append_log(log_file, f"phase: APPLY_FAILED → {exc}")
            except Exception as exc:
                apply_error = f"Internal error: {exc}"
                _append_log(log_file, f"phase: APPLY_FAILED → internal error: {exc}")
                logger.exception("Unexpected error during apply phase")

        # ------------------------------------------------------------------
        # Phase 2.1: promote validated workspace files back to original repo
        # ------------------------------------------------------------------
        promoted_files: List[str] = []
        promotion_status: Optional[str] = None

        if apply_error is None and modified_files:
            _append_log(log_file, "phase: PROMOTE_START")
            try:
                promoted_files, promotion_status = _promote_changes(
                    workspace_path=workspace_path,
                    repo_root=request.repo_path,
                    modified_files=modified_files,
                    log_file=log_file,
                )
                _append_log(
                    log_file,
                    f"phase: PROMOTE_DONE → {promotion_status} ({len(promoted_files)} files)",
                )
            except Exception as exc:
                promotion_status = "failed"
                _append_log(log_file, f"phase: PROMOTE_FAILED → {exc}")
                logger.exception("Unexpected error during promotion phase")

        # ------------------------------------------------------------------
        # Phase 2.5: sandbox execution via RunnerAPI (Docker)
        #
        # Triggered when BOTH authorized_plan and code are present on the request.
        # Uses an isolated _sandbox/ sub-directory so the repo workspace is
        # never touched by WorkspaceModel.cleanup() inside RunnerAPI.
        # Errors are captured in apply_error to flow through validation/report/notify.
        # ------------------------------------------------------------------
        authorized_plan_info: Optional[Dict[str, Any]] = None
        sandbox_metadata: Optional[Dict[str, Any]] = None

        if apply_error is None and request.authorized_plan is not None and request.code is not None:
            _append_log(log_file, "phase: SANDBOX_EXEC_START")
            # Isolated workspace for Docker execution — separate from the repo workspace.
            sandbox_ws = Path(workspace.artifacts_path) / "_sandbox"
            sandbox_ws.mkdir(parents=True, exist_ok=True)

            # Capture governance summary for metadata.json.
            ap = request.authorized_plan
            authorized_plan_info = {
                "execution_id": ap.execution_id,
                "plan_id": ap.plan_id,
                "policy_id": ap.policy_id,
                "authorized_plan_hash": ap.authorized_plan_hash,
                "capability_scope": list(ap.capability_scope),
                "runtime_profile": ap.runtime_profile,
            }

            try:
                sandbox_exec = self._runner_api.execute(
                    code=request.code,
                    workspace=str(sandbox_ws),
                    authorized_plan=request.authorized_plan,
                    registry=self._registry,
                    audit_log=self._audit_store,
                )
                if sandbox_exec.metadata is not None:
                    sandbox_metadata = sandbox_exec.metadata.to_dict()

                if sandbox_exec.ok:
                    _append_log(
                        log_file,
                        f"phase: SANDBOX_EXEC_DONE exit=0 duration={sandbox_exec.duration_ms}ms",
                    )
                else:
                    # Categorise the failure semantically so distinct states are not collapsed.
                    meta_reason = (
                        (sandbox_exec.metadata.termination_reason or "")
                        if sandbox_exec.metadata is not None
                        else ""
                    )
                    if meta_reason == "internal_error":
                        # TerminationReason.INTERNAL_ERROR — backend infrastructure failure,
                        # not a sandbox code fault.  Map to backend_unavailable category.
                        apply_error = f"Sandbox backend unavailable: {sandbox_exec.error or 'unknown backend error'}"
                    elif sandbox_exec.timed_out or meta_reason == "timeout":
                        apply_error = "Sandbox execution timed out"
                    elif meta_reason in ("revoked", "manual"):
                        apply_error = "Sandbox execution aborted"
                    elif sandbox_exec.error:
                        # Error string set by backend (e.g. Docker not found) but not
                        # an INTERNAL_ERROR termination — treat as execution_failed.
                        apply_error = f"Sandbox error: {sandbox_exec.error}"
                    else:
                        stderr_excerpt = (sandbox_exec.stderr or "")[:200]
                        apply_error = (
                            f"Sandbox execution failed (exit {sandbox_exec.exit_code})"
                            + (f": {stderr_excerpt}" if stderr_excerpt else "")
                        )
                    _append_log(log_file, f"phase: SANDBOX_EXEC_FAILED → {apply_error}")

            except ValueError as exc:
                apply_error = f"Sandbox validation error: {exc}"
                _append_log(log_file, f"phase: SANDBOX_EXEC_FAILED → {exc}")
            except Exception as exc:
                apply_error = f"Sandbox internal error: {exc}"
                _append_log(log_file, f"phase: SANDBOX_EXEC_FAILED → internal error: {exc}")
                logger.exception("Unexpected error during sandbox execution phase")

        # ------------------------------------------------------------------
        # Phase 3: test (skipped if apply or sandbox failed)
        # ------------------------------------------------------------------
        test_result: Optional[TestExecutionResult] = None
        test_error: Optional[str] = None

        if apply_error is None and request.test_spec:
            try:
                test_result = TestEngine().run_tests(
                    workspace_path=workspace_path,
                    test_spec=request.test_spec,
                    log_file=log_file,
                )
                # TEST_DONE is logged by TestEngine itself.
            except (TestExecutionError, PolicyViolationError) as exc:
                test_error = str(exc)
                _append_log(log_file, f"phase: TEST_DONE (error: {exc})")
            except Exception as exc:
                test_error = f"Internal error: {exc}"
                _append_log(log_file, f"phase: TEST_DONE (internal error: {exc})")
                logger.exception("Unexpected error during test phase")

        # ------------------------------------------------------------------
        # Build intermediate result (passed through to V/R/N)
        # ------------------------------------------------------------------
        error_message = apply_error or test_error
        intermediate_status = (
            RunnerExecutionStatus.FAILED
            if error_message
            else self._determine_status(modified_files, test_result)
        )
        summary = self._build_summary(intermediate_status, modified_files, test_result)

        finished_at = datetime.now(timezone.utc)
        result = RunnerExecutionResult(
            execution_id=request.execution_id,
            status=intermediate_status,
            started_at=started_at,
            finished_at=finished_at,
            workspace_path=workspace.workspace_path,
            artifacts_path=workspace.artifacts_path,
            modified_files=modified_files,
            test_result=test_result,
            error=error_message,
            summary=summary,
            authorized_plan_info=authorized_plan_info,
            sandbox_metadata=sandbox_metadata,
            changes_detail=changes_detail if changes_detail else None,
            promoted_files=promoted_files if promoted_files else None,
            promotion_status=promotion_status,
        )

        # ------------------------------------------------------------------
        # Phase 4: validation (always runs when a workspace exists)
        # ------------------------------------------------------------------
        _append_log(log_file, "phase: VALIDATION_START")
        validation: Optional[ValidationResult] = None
        try:
            validation = ValidationEngine().validate(result, request.validation_spec)
            result.validation_result = validation
            result.final_status = validation.final_status
            _append_log(log_file, f"phase: VALIDATION_DONE → {validation.final_status}")
        except Exception as exc:
            _append_log(log_file, f"validation: error → {exc}")
            logger.exception("Unexpected error during validation phase")
            result.final_status = result.final_status or "failed"

        # Fallback validation for report/notify if validation itself failed.
        if validation is None:
            validation = ValidationResult(
                final_status=result.final_status or "failed",
                reasons=["Validation phase failed due to an internal error."],
                validation_summary="Validation unavailable.",
            )

        # ------------------------------------------------------------------
        # Phase 5: report
        # ------------------------------------------------------------------
        _append_log(log_file, "phase: REPORT_START")
        try:
            report = ReportBuilder().build(result, validation)
            result.report_json_path = report.json_path
            result.report_md_path = report.md_path
            _append_log(log_file, "phase: REPORT_DONE")
        except Exception as exc:
            _append_log(log_file, f"report: error → {exc}")
            logger.exception("Unexpected error during report phase")

        # ------------------------------------------------------------------
        # Phase 6: notify
        # ------------------------------------------------------------------
        _append_log(log_file, "phase: NOTIFY_START")
        try:
            notif = NotificationEngine().notify(result, validation)
            result.notification_path = notif.notification_path
            _append_log(log_file, "phase: NOTIFY_DONE")
        except Exception as exc:
            _append_log(log_file, f"notify: error → {exc}")
            logger.warning("Notification error (non-fatal): %s", exc)

        # ------------------------------------------------------------------
        # Persist final metadata and return
        # ------------------------------------------------------------------
        self._write_final_metadata(workspace.artifacts_path, result)
        _append_log(
            log_file,
            f"status: {intermediate_status.value} | final: {result.final_status}",
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _preflight(self, request: RunnerExecutionRequest) -> None:
        if not request.execution_id or not request.execution_id.strip():
            raise PreflightError("execution_id must not be empty.")
        # Prevent path traversal: execution_id becomes a directory name under
        # var/runner/executions/. Reject any value that could escape that base.
        if (
            ".." in request.execution_id
            or "/" in request.execution_id
            or "\\" in request.execution_id
        ):
            raise PreflightError(
                f"execution_id contains invalid characters (path separators or '..' not allowed): "
                f"{request.execution_id!r}"
            )
        if (
            request.authorized_plan is not None
            and request.authorized_plan.authority_artifact is not None
        ):
            try:
                request.authorized_plan.validate()
            except ValueError as exc:
                raise PolicyViolationError(
                    f"Authority artifact verification failed: {exc}"
                ) from exc
            signature = self._resolve_authority_artifact_signature(
                request.authorized_plan.authority_artifact
            )
            if not signature:
                raise PolicyViolationError(
                    "Authority artifact verification failed: missing signature."
                )
            if not self._authority_consumption_registry.consume(signature):
                raise PolicyViolationError(
                    "Authority artifact replay detected: signature already consumed."
                )
        if not request.repo_path or not request.repo_path.strip():
            raise PreflightError("repo_path must not be empty.")
        # M2D — fast-fail: validate changes before workspace creation.
        if request.changes:
            self._validate_changes_preflight(request.changes)

    def _validate_changes_preflight(self, changes: List[Any]) -> None:
        """Validate *changes* structurally before workspace creation.

        Raises PreflightError immediately (no workspace I/O yet) for:
        - Unknown op
        - Missing or absolute path
        - file_replace with missing content field
        - patch with empty patch field
        """
        _VALID_OPS = frozenset({"file_replace", "patch"})
        for i, change in enumerate(changes):
            if not isinstance(change, dict):
                raise PreflightError(
                    f"changes[{i}] must be a dict, got {type(change).__name__!r}."
                )
            op = change.get("op")
            if op not in _VALID_OPS:
                raise PreflightError(
                    f"changes[{i}]: unknown op {op!r}. Valid ops: {sorted(_VALID_OPS)}."
                )
            path = change.get("path", "")
            if not path or not path.strip():
                raise PreflightError(f"changes[{i}]: 'path' must not be empty.")
            # Reject all absolute paths regardless of host OS.
            # Path.is_absolute() catches Windows drive-letter paths (C:\...).
            # The extra startswith("/") catches POSIX-style absolute paths on
            # Windows, where Path("/etc/passwd").is_absolute() returns False
            # because Windows does not treat a leading "/" as absolute.
            # Change paths must ALWAYS be relative — both forms are invalid.
            if Path(path).is_absolute() or path.startswith("/"):
                raise PreflightError(
                    f"changes[{i}]: path {path!r} is absolute — only relative paths are allowed."
                )
            if op == "file_replace" and change.get("content") is None:
                raise PreflightError(
                    f"changes[{i}]: file_replace for {path!r} missing required 'content' field."
                )
            if op == "patch":
                patch_text = change.get("patch", "")
                if not patch_text or not patch_text.strip():
                    raise PreflightError(
                        f"changes[{i}]: patch op for {path!r} has empty 'patch' field."
                    )

    def _resolve_authority_artifact_signature(self, authority_artifact: Any) -> str:
        if hasattr(authority_artifact, "signature"):
            return str(getattr(authority_artifact, "signature", "")).strip()
        if isinstance(authority_artifact, Mapping):
            return str(authority_artifact.get("signature", "")).strip()
        return ""

    def _determine_status(
        self,
        modified_files: List[str],
        test_result: Optional[TestExecutionResult],
    ) -> RunnerExecutionStatus:
        if test_result is not None:
            if test_result.status == "passed":
                return RunnerExecutionStatus.TESTS_PASSED
            elif test_result.status == "timed_out":
                return RunnerExecutionStatus.FAILED
            else:
                return RunnerExecutionStatus.TESTS_FAILED
        if modified_files:
            return RunnerExecutionStatus.CHANGES_APPLIED
        return RunnerExecutionStatus.WORKSPACE_READY

    def _build_summary(
        self,
        status: RunnerExecutionStatus,
        modified_files: List[str],
        test_result: Optional[TestExecutionResult],
    ) -> str:
        if test_result is not None:
            duration = f"{test_result.duration_ms}ms" if test_result.duration_ms is not None else "N/A"
            return (
                f"Tests {test_result.status}. "
                f"{len(modified_files)} file(s) modified. "
                f"Duration: {duration}."
            )
        if modified_files:
            return f"Applied {len(modified_files)} file(s): {modified_files}."
        return "Workspace prepared. No changes applied."

    def _fail(
        self,
        request: RunnerExecutionRequest,
        started_at: datetime,
        error_message: str,
    ) -> RunnerExecutionResult:
        """Return a FAILED result for pre-workspace failures (no artifacts dir)."""
        finished_at = datetime.now(timezone.utc)
        logger.error("Runner execution %s FAILED: %s", request.execution_id, error_message)
        log_preflight_failure(
            execution_id=request.execution_id,
            repo_path=request.repo_path,
            error=error_message,
        )
        return RunnerExecutionResult(
            execution_id=request.execution_id,
            status=RunnerExecutionStatus.FAILED,
            final_status="failed",
            started_at=started_at,
            finished_at=finished_at,
            error=error_message,
            summary=f"Execution failed: {error_message}",
        )

    def _write_final_metadata(self, artifacts_path: str, result: RunnerExecutionResult) -> None:
        metadata_file = Path(artifacts_path) / "metadata.json"
        if not metadata_file.exists():
            return

        try:
            data = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}

        data.update(
            {
                "execution_id": result.execution_id,
                "status": result.status.value,
                "final_status": result.final_status,
                "started_at": result.started_at.isoformat(),
                "finished_at": result.finished_at.isoformat(),
                "error": result.error,
                "summary": result.summary,
                "modified_files": result.modified_files,
                "test_result": (
                    dataclasses.asdict(result.test_result)
                    if result.test_result is not None
                    else None
                ),
                "validation_result": (
                    dataclasses.asdict(result.validation_result)
                    if result.validation_result is not None
                    else None
                ),
                "report_json_path": result.report_json_path,
                "report_md_path": result.report_md_path,
                "notification_path": result.notification_path,
                # M1B governance fields — present when RunnerAPI (Docker) was invoked.
                "authorized_plan": result.authorized_plan_info,
                "sandbox_execution": result.sandbox_metadata,
                # M2D audit — per-file change detail.
                "changes_detail": result.changes_detail,
                # M2F.1 promotion — files copied from workspace back to repo.
                "promoted_files": result.promoted_files,
                "promotion_status": result.promotion_status,
            }
        )

        try:
            metadata_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not update metadata.json: %s", exc)
