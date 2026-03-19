"""
Tool — Claude Code Apply Change

Applies a previously confirmed CodeProposalEnvelope.

Five safety checks are performed before any write:
  1. proposal_id must be non-empty
  2. proposal_id must not have been applied before (single-use)
  3. No blocked v0 operation types (delete / rename / move)
  4. All affected_files must be within allowed_write_scope
  5. Workspace hash must match the hash recorded at proposal time

Input keys
----------
proposal   : dict — CodeProposalEnvelope from propose_change_tool (confirmed)
workspace  : str  — Absolute path to workspace root
context_id : str  — Request trace ID (for audit)

Output (ToolResult.data on success)
------------------------------------
applied_files  : list[str] — All files touched
created_files  : list[str] — Files created (subset of applied_files)
modified_files : list[str] — Files modified (subset of applied_files)
proposal_id    : str       — Echo of the applied proposal_id

Single-use enforcement
----------------------
_APPLIED_PROPOSALS is a module-level set.  code_pipeline passes its own
_applied_proposals set so that single-use tracking is scoped to the pipeline
(not the tool instance), which makes it testable via dependency injection.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from ..base.tool import Tool
from ..base.tool_result import ToolResult
from ..base.tool_error import ToolError
from .propose_change_tool import compute_workspace_hash, V0_BLOCKED_OPERATIONS

_PROVIDER = "claude_code"
_OPERATION = "apply_change"

# Module-level fallback applied-proposal tracker.
# code_pipeline injects its own set so this is only used when the tool is
# instantiated standalone (e.g. in integration tests).
_APPLIED_PROPOSALS: set = set()


def _default_executor(input: dict) -> dict:
    """
    Stub executor.  Simulates applying a patch by reporting which files
    would be touched.  Active when APPLY_EXECUTION_MODE=stub (the default).

    Executor contract:
        executor(input: dict) -> dict
            input  keys: proposal (CodeProposalEnvelope), workspace, context_id
            output keys: ok (bool), apply_mode (str), applied_files (list[str]),
                         created_files (list[str]), modified_files (list[str]),
                         error (str, on failure)
    """
    proposal = input.get("proposal", {})
    affected_files: list = proposal.get("affected_files", [])
    action = proposal.get("action", "")

    if action == "CODE_CREATE":
        return {
            "ok": True,
            "apply_mode": "stub",
            "applied_files": list(affected_files),
            "created_files": list(affected_files),
            "modified_files": [],
        }
    return {
        "ok": True,
        "apply_mode": "stub",
        "applied_files": list(affected_files),
        "created_files": [],
        "modified_files": list(affected_files),
    }


def _real_executor(input: dict) -> dict:
    """
    Real executor — routes to RunnerAPI / ContainerBackend.

    Active when APPLY_EXECUTION_MODE=real.  Requires Docker on the host.

    Code extraction strategy (MVP)
    --------------------------------
    1. Proposal may carry an optional ``execution_code`` field (future: set by
       the propose executor after generating a patch).  If present, use it.
    2. Fall back to extracting "+" lines from ``patch_preview`` — this gives a
       rough approximation of what CODE_CREATE would write.
    3. If neither is available, run a sentinel script that confirms the execution
       boundary is functional without applying any real change.

    The goal of this MVP is to establish and verify the container execution
    boundary, NOT to perform a complete patch application.  Real patch
    application (write → apply diff → run) is deferred to the next sprint.
    """
    from ...config import RUNNER_TIMEOUT_SECONDS, RUNNER_BASE_IMAGE, RUNNER_MEMORY_LIMIT, RUNNER_CPU_LIMIT  # noqa: PLC0415
    from ...sandbox.runner_api import RunnerAPI  # noqa: PLC0415
    from ...sandbox.container_backend import ContainerBackend  # noqa: PLC0415
    import os  # noqa: PLC0415

    proposal: dict = input.get("proposal", {})
    workspace: str = input.get("workspace", "")
    affected_files: list = proposal.get("affected_files", [])
    action: str = proposal.get("action", "")

    # --- Code extraction (best-effort) ---
    code: str = proposal.get("execution_code", "")
    if not code:
        # Extract "+" lines from the unified diff as a rough approximation.
        patch: str = proposal.get("patch_preview", "")
        added_lines = [
            line[1:]  # strip leading "+"
            for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        code = "\n".join(added_lines) if added_lines else ""

    if not code.strip():
        # Sentinel: no extractable code — confirm the boundary is functional.
        code = (
            "# AssistantOS Runner MVP — execution boundary sentinel\n"
            "# Real patch application will be implemented in the next sprint.\n"
            "print('[runner] execution boundary OK — apply_mode=real')\n"
        )

    # Use a runner-specific sub-directory of the workspace to avoid
    # polluting the proposal workspace with input/output/artifacts dirs.
    runner_workspace = os.path.join(workspace, "_runner_exec")
    os.makedirs(runner_workspace, exist_ok=True)

    try:
        backend = ContainerBackend(
            base_image=RUNNER_BASE_IMAGE,
            memory_limit=RUNNER_MEMORY_LIMIT,
            cpu_limit=RUNNER_CPU_LIMIT,
        )
        runner = RunnerAPI(backend=backend, timeout_seconds=RUNNER_TIMEOUT_SECONDS)
        exec_result = runner.execute(code=code, workspace=runner_workspace)
    except Exception as exc:
        return {"ok": False, "error": f"RunnerAPI error: {exc}"}

    if exec_result.timed_out:
        return {
            "ok": False,
            "error": f"Execution timed out after {RUNNER_TIMEOUT_SECONDS}s",
        }

    if exec_result.error:
        return {"ok": False, "error": exec_result.error}

    if not exec_result.ok:
        stderr_excerpt = exec_result.stderr[:300]
        return {
            "ok": False,
            "error": (
                f"Execution failed (exit {exec_result.exit_code}): {stderr_excerpt}"
            ),
        }

    is_create = action == "CODE_CREATE"
    return {
        "ok": True,
        "apply_mode": "real",
        "applied_files": list(affected_files),
        "created_files": list(affected_files) if is_create else [],
        "modified_files": [] if is_create else list(affected_files),
        # Structured execution result available for audit / observability.
        "execution_result": exec_result.to_dict(),
    }


def _select_default_executor() -> Callable:
    """
    Return the appropriate default executor based on APPLY_EXECUTION_MODE.

    Called once at ApplyChangeTool instantiation time.  The config value is
    read fresh each time to allow test isolation via env-var patching.
    """
    from ...config import APPLY_EXECUTION_MODE  # noqa: PLC0415
    if APPLY_EXECUTION_MODE == "real":
        return _real_executor
    return _default_executor


def _validate_write_scope(
    affected_files: list,
    allowed_scope: list,
    workspace: str,
) -> Optional[str]:
    """
    Return an error message if any file is outside allowed_write_scope,
    uses path traversal, or is an absolute path.  Return None if all clear.
    """
    for rel_path in affected_files:
        if os.path.isabs(rel_path):
            return f"Absolute path rejected: {rel_path!r}"
        parts = rel_path.replace("\\", "/").split("/")
        if ".." in parts:
            return f"Path traversal rejected: {rel_path!r}"
        if allowed_scope and rel_path not in allowed_scope:
            return f"File {rel_path!r} is not in allowed_write_scope"
    return None


class ApplyChangeTool(Tool):
    """Apply a confirmed code change proposal (single-use, integrity-validated)."""

    def __init__(
        self,
        executor: Optional[Callable] = None,
        applied_proposals: Optional[set] = None,
    ) -> None:
        # If no executor is explicitly injected, select based on APPLY_EXECUTION_MODE.
        # Tests always inject their own executor or rely on stub (the default mode),
        # so existing tests are unaffected.
        self._executor = executor if executor is not None else _select_default_executor()
        # Use the caller-supplied set (pipeline-scoped) or the module-level fallback
        self._applied = applied_proposals if applied_proposals is not None else _APPLIED_PROPOSALS

    def execute(self, input: dict) -> ToolResult:
        proposal: dict = input.get("proposal", {})
        workspace: str = input.get("workspace", "")

        proposal_id: str = proposal.get("proposal_id", "")
        affected_files: list = proposal.get("affected_files", [])
        allowed_scope: list = proposal.get("allowed_write_scope", [])
        stored_hash: str = proposal.get("workspace_hash", "")
        action: str = proposal.get("action", "")

        metadata = {
            "provider": _PROVIDER,
            "operation": _OPERATION,
            "proposal_id": proposal_id,
            "action": action,
        }

        # Guard 1: proposal_id required
        if not proposal_id:
            return ToolResult(
                ok=False, data=None,
                error=ToolError(
                    code="MissingProposalId",
                    message="proposal_id is required for apply. Was the proposal confirmed?",
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        # Guard 2: single-use check
        if proposal_id in self._applied:
            return ToolResult(
                ok=False, data=None,
                error=ToolError(
                    code="ProposalAlreadyApplied",
                    message=(
                        f"Proposal {proposal_id!r} has already been applied. "
                        "Create a new proposal."
                    ),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        # Guard 3: blocked v0 operations
        op_types: list = proposal.get("proposal_artifacts", {}).get("operation_types", [])
        blocked = [op for op in op_types if op in V0_BLOCKED_OPERATIONS]
        if blocked:
            return ToolResult(
                ok=False, data=None,
                error=ToolError(
                    code="BlockedOperationV0",
                    message=f"v0 does not support: {blocked}",
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        # Guard 4: write scope validation
        scope_error = _validate_write_scope(affected_files, allowed_scope, workspace)
        if scope_error:
            return ToolResult(
                ok=False, data=None,
                error=ToolError(code="WriteOutOfScope", message=scope_error, provider=_PROVIDER),
                metadata=metadata,
            )

        # Guard 5: workspace integrity check
        if stored_hash and workspace:
            current_hash = compute_workspace_hash(workspace, affected_files)
            if current_hash != stored_hash:
                return ToolResult(
                    ok=False, data=None,
                    error=ToolError(
                        code="WorkspaceModified",
                        message=(
                            "Workspace was modified after the proposal was generated. "
                            "Please create a new proposal."
                        ),
                        provider=_PROVIDER,
                    ),
                    metadata=metadata,
                )

        # All checks passed — execute the apply
        try:
            result = self._executor(input)
        except Exception as exc:
            return ToolResult(
                ok=False, data=None,
                error=ToolError(code="ExecutorException", message=str(exc), provider=_PROVIDER),
                metadata=metadata,
            )

        if not result.get("ok"):
            return ToolResult(
                ok=False, data=None,
                error=ToolError(
                    code="ApplyFailed",
                    message=result.get("error", "Apply executor returned an error"),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        # Mark as applied — single-use protection
        self._applied.add(proposal_id)

        return ToolResult(
            ok=True,
            data={
                "apply_mode": result.get("apply_mode", "stub"),
                "applied_files": result.get("applied_files", affected_files),
                "created_files": result.get("created_files", []),
                "modified_files": result.get("modified_files", affected_files),
                "proposal_id": proposal_id,
            },
            error=None,
            metadata=metadata,
        )
