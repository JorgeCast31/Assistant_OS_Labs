"""
CODE Domain Pipeline v0

Entry point: execute(plan, context_id) -> DomainResult

Dispatches CODE actions to the appropriate read-only or mutating helpers.
All domain logic lives here; tools remain stateless technical adapters.

READ-ONLY actions (no confirmation, auto-execute):
  CODE_EXPLAIN — explain / describe code
  CODE_REVIEW  — review / audit code

MUTATING actions (preview → confirm → apply):
  CODE_FIX    — fix a bug / correct existing code
  CODE_CREATE — create a new file / class / function

Canonical two-phase mutating flow
----------------------------------
Preview path (default, phase absent or "preview"):
  plan["domain_payload"]["phase"] is not "apply"
  → validate workspace + write scope
  → call ProposeChangeTool
  → return DomainResult(result_type=code_preview, requires_confirmation=True)

Apply path (triggered after user confirmation):
  plan["domain_payload"]["phase"] == "apply"
  plan["domain_payload"]["proposal"] is a CodeProposalEnvelope
  → validate workspace
  → call ApplyChangeTool (runs 5 integrity guards)
  → return DomainResult(result_type=code_apply)

proposal_id single-use protection
-----------------------------------
_applied_proposals is a module-level set injected into ApplyChangeTool so that
the pipeline (not the tool) owns the lifecycle of applied proposals.

Write scope validation
-----------------------
_validate_write_scope_early() is called before ProposeChangeTool to reject
obviously unsafe paths (absolute, traversal) before any executor call.

Read-only executor registry
----------------------------
_review_executor holds an optional real executor callable for CODE_EXPLAIN and
CODE_REVIEW.  It is None by default (stub used).  Call register_review_executor()
at application startup to wire a real Claude Code callable without changing any
other code.

Propose executor registry
--------------------------
_propose_executor holds an optional real executor callable for CODE_FIX and
CODE_CREATE preview generation.  It is None by default (stub used).  Call
register_propose_executor() at application startup.  The apply path is always
stubbed — _propose_executor has zero effect on ApplyChangeTool.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Callable, Optional

from ..contracts import (
    DomainResult,
    make_domain_result,
    ACTION_CODE_EXPLAIN,
    ACTION_CODE_REVIEW,
    ACTION_CODE_FIX,
    ACTION_CODE_CREATE,
    RESULT_TYPE_CODE_EXPLAIN,
    RESULT_TYPE_CODE_REVIEW,
    RESULT_TYPE_CODE_PREVIEW,
    RESULT_TYPE_CODE_APPLY,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
)
from ..core.context import get_context
from ..runners.metadata_utils import patch_execution_metadata

# ---------------------------------------------------------------------------
# Module-level single-use applied-proposal tracker.
# In production replace with a persistent store (DB, Redis, etc.) so that
# restarts don't reset the guard.
# ---------------------------------------------------------------------------
_applied_proposals: set = set()


# ---------------------------------------------------------------------------
# Read-only executor registry.
# None → ReviewCodeTool falls back to its own stub executor.
# Set via register_review_executor() at app startup for real execution.
# ---------------------------------------------------------------------------
_review_executor: Optional[Callable] = None


def register_review_executor(fn: Optional[Callable]) -> None:
    """
    Register a real executor callable for CODE_EXPLAIN / CODE_REVIEW actions.

    Call once at application startup.  Pass None to revert to the default stub.
    The change takes effect immediately for all subsequent requests — no restart
    required.

    Callable contract
    -----------------
    fn(input: dict) -> dict

    input keys:
        action      : str — "CODE_EXPLAIN" | "CODE_REVIEW"
        target_file : str — relative file path within workspace (may be empty)
        workspace   : str — absolute path to the workspace root (may be empty)
        context     : str — raw user text / question

    output keys (on success):
        ok          : True
        analysis    : str — free-text explanation or review

    output keys (on failure):
        ok          : False
        error       : str — human-readable failure reason

    Example
    -------
        from assistant_os.pipelines.code_pipeline import register_review_executor

        def my_claude_executor(inp: dict) -> dict:
            # call Claude Code API here
            ...
            return {"ok": True, "analysis": result}

        register_review_executor(my_claude_executor)
    """
    global _review_executor
    _review_executor = fn


# ---------------------------------------------------------------------------
# Propose executor registry.
# None → ProposeChangeTool falls back to its own stub executor.
# Set via register_propose_executor() at app startup for real execution.
# ---------------------------------------------------------------------------
_propose_executor: Optional[Callable] = None


def register_propose_executor(fn: Optional[Callable]) -> None:
    """
    Register a real executor callable for CODE_FIX / CODE_CREATE preview.

    Call once at application startup.  Pass None to revert to the default stub.
    Only affects the preview phase — the apply path is always stubbed.

    Callable contract
    -----------------
    fn(input: dict) -> dict

    input keys:
        action              : str  — "CODE_FIX" | "CODE_CREATE"
        target_file         : str  — relative path within workspace (may be "")
        workspace           : str  — absolute workspace root (may be "")
        context             : str  — raw user text / change request
        allowed_write_scope : list — allowed relative paths

    output keys (on success):
        ok                   : True
        summary              : str
        affected_files       : list[str]
        write_intent_summary : str
        patch_preview        : str
        operation_types      : list[str]  — "modify" | "create" only
        risk_level           : str        — "low" | "medium" | "high"

    output keys (on failure):
        ok    : False
        error : str — human-readable failure reason
    """
    global _propose_executor
    _propose_executor = fn


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def execute(plan: dict, context_id: str) -> DomainResult:
    """
    Dispatch a CODE domain plan to the appropriate execution helper.

    Args:
        plan:       ExecutionPlan dict.  CODE-specific data lives in
                    plan["domain_payload"] to keep top-level fields clean.
        context_id: Canonical context ID for this request.

    Returns:
        DomainResult — never transport-wrapped.
    """
    _context = get_context(context_id)  # noqa: F841 — reserved for future use

    if not plan.get("plan_id"):
        return make_domain_result(
            ok=False,
            result_type="code_unknown",
            domain="CODE",
            message="plan_id is required",
            error={"type": "ExecutionPlanViolation", "message": "plan_id is required"},
        )

    action = plan.get("action", "")

    if action == ACTION_CODE_EXPLAIN:
        return _execute_read_only(plan, context_id, result_type=RESULT_TYPE_CODE_EXPLAIN)

    if action == ACTION_CODE_REVIEW:
        return _execute_read_only(plan, context_id, result_type=RESULT_TYPE_CODE_REVIEW)

    if action in (ACTION_CODE_FIX, ACTION_CODE_CREATE):
        return _execute_mutating(plan, context_id)

    return make_domain_result(
        ok=False,
        result_type="code_unknown",
        domain="CODE",
        message=f"Acción CODE desconocida: {action!r}",
        data={"plan": dict(plan)},
        error={"type": "UnknownAction", "message": f"No handler for CODE action: {action!r}"},
    )


# ---------------------------------------------------------------------------
# Executor context
# ---------------------------------------------------------------------------

def _build_executor_context(plan: dict, payload: dict) -> str:
    """Build executor context, optionally enriched by a non-authoritative MSO package."""
    base_context = str(plan.get("raw_text", "")).strip()
    code_package: dict = payload.get("_mso_code_package") or {}
    if not code_package:
        return base_context

    lines = ["[MSO advisory package - non-authoritative]"]
    if code_package.get("task_summary"):
        lines.append(f"Task summary: {code_package['task_summary']}")
    if code_package.get("repo_context"):
        lines.append(f"Repo context: {code_package['repo_context']}")
    constraints = code_package.get("constraints") or []
    if constraints:
        lines.append(f"Constraints: {'; '.join(str(item) for item in constraints)}")
    if code_package.get("expected_artifact"):
        lines.append(f"Expected artifact: {code_package['expected_artifact']}")
    risk_notes = code_package.get("risk_notes") or []
    if risk_notes:
        lines.append(f"Risk notes: {'; '.join(str(item) for item in risk_notes)}")

    advisory_block = "\n".join(lines)
    if not base_context:
        return advisory_block
    return f"{base_context}\n\n{advisory_block}"


# ---------------------------------------------------------------------------
# Read-only path
# ---------------------------------------------------------------------------

def _execute_read_only(plan: dict, context_id: str, result_type: str) -> DomainResult:
    """
    Call ReviewCodeTool and return a DomainResult (no confirmation needed).

    Uses _review_executor if registered via register_review_executor(); otherwise
    ReviewCodeTool falls back to its internal stub.
    """
    from ..tools.claude_code.review_code_tool import ReviewCodeTool

    payload: dict = plan.get("domain_payload") or {}
    action = plan.get("action", "")

    # Pass the registered executor (or None → stub) into the tool
    tool_result = ReviewCodeTool(executor=_review_executor).execute({
        "action": action,
        "target_file": payload.get("target_file", ""),
        "workspace": payload.get("workspace", ""),
        "context": _build_executor_context(plan, payload),
    })

    if not tool_result.ok:
        return make_domain_result(
            ok=False,
            result_type=result_type,
            domain="CODE",
            message="Error al analizar el código.",
            data={
                "action": action,
                "target_file": payload.get("target_file", ""),
                "executor_live": _review_executor is not None,
            },
            error={"type": tool_result.error.code, "message": tool_result.error.message},
        )

    analysis = tool_result.data.get("analysis", "")
    target = tool_result.data.get("target_file", "")
    action_label = "Explicación" if result_type == RESULT_TYPE_CODE_EXPLAIN else "Revisión"

    return make_domain_result(
        ok=True,
        result_type=result_type,
        domain="CODE",
        message=f"CODE · {action_label.lower()}\n\n{analysis}",
        data={
            "type": result_type,
            "analysis": analysis,
            "target_file": target,
            "action": action,
            "executor_live": _review_executor is not None,
        },
        trace_id=plan.get("trace_id"),
        plan_id=plan.get("plan_id"),
    )


# ---------------------------------------------------------------------------
# Mutating path — preview + apply
# ---------------------------------------------------------------------------

def _execute_mutating(plan: dict, context_id: str) -> DomainResult:
    """
    Route CODE_FIX / CODE_CREATE through the two-phase preview/apply flow.

    Phase is determined by domain_payload["phase"]:
    - "apply" + proposal present → apply path
    - anything else              → preview path (default)
    """
    payload: dict = plan.get("domain_payload") or {}

    # Workspace must be valid before any tool call — validate early so both
    # preview and apply fail with a clean error before touching the filesystem.
    workspace: str = payload.get("workspace", "")
    ws_error = _validate_workspace(workspace)
    if ws_error:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CODE_PREVIEW,
            domain="CODE",
            message=ws_error,
            data={"plan": dict(plan)},
            error={"type": "InvalidWorkspace", "message": ws_error},
        )

    phase = payload.get("phase", "preview")
    proposal = payload.get("proposal")

    if phase == "apply":
        if proposal is None:
            return make_domain_result(
                ok=False,
                result_type=RESULT_TYPE_CODE_APPLY,
                domain="CODE",
                message="apply phase requires proposal",
                error={"type": "ExecutionPlanViolation", "message": "apply phase requires proposal"},
            )
        return _apply_code_proposal(plan, proposal, payload)
    return _build_code_preview(plan, payload)


def _build_code_preview(plan: dict, payload: dict) -> DomainResult:
    """Call ProposeChangeTool and build a preview DomainResult."""
    from ..tools.claude_code.propose_change_tool import ProposeChangeTool

    action = plan.get("action", "")
    target_file: str = payload.get("target_file", "")
    workspace: str = payload.get("workspace", "")
    allowed_scope: list = payload.get("allowed_write_scope") or (
        [target_file] if target_file else []
    )

    # Early path validation (before executor call)
    scope_error = _validate_write_scope_early(target_file)
    if scope_error:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CODE_PREVIEW,
            domain="CODE",
            message=scope_error,
            data={"plan": dict(plan)},
            error={"type": "WriteOutOfScope", "message": scope_error},
        )

    tool_result = ProposeChangeTool(executor=_propose_executor).execute({
        "action": action,
        "target_file": target_file,
        "workspace": workspace,
        "context": _build_executor_context(plan, payload),
        "allowed_write_scope": allowed_scope,
    })

    if not tool_result.ok:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CODE_PREVIEW,
            domain="CODE",
            message="Error al generar la propuesta de cambio.",
            data={"plan": dict(plan)},
            error={"type": tool_result.error.code, "message": tool_result.error.message},
        )

    envelope: dict = tool_result.data
    proposal_id = envelope.get("proposal_id", "")
    affected_files: list = envelope.get("affected_files", [])
    risk = envelope.get("risk_level", RISK_MEDIUM)

    action_label = "Corrección" if action == ACTION_CODE_FIX else "Creación"

    # Multi-file: vertical list for 2+ files so each path is easy to scan
    if len(affected_files) > 1:
        files_str = "\n  " + "\n  ".join(affected_files)
    else:
        files_str = affected_files[0] if affected_files else "ningún archivo"

    # operation_types — pulled from the envelope; fallback is explicit, not a silent "modify"
    # so that message == data is always a faithful projection, never a free re-interpretation.
    op_types: list = envelope.get("proposal_artifacts", {}).get("operation_types", [])
    op_str = ", ".join(op_types) if op_types else "(tipo de operación no disponible)"

    # patch_preview — treat absent key AND empty string identically: both are "no diff"
    _raw_patch = envelope.get("patch_preview", "")
    patch_text = (
        _raw_patch.strip()
        if _raw_patch.strip()
        else "(sin diff disponible — executor no generó vista previa)"
    )
    patch_truncated: bool = envelope.get("patch_preview_truncated", False)

    # ---------------------------------------------------------------------------
    # Degradation metadata
    # Derived from the exact same variables used to build the message so that
    # data.preview_warnings and the visible text always share a single source of truth.
    # ---------------------------------------------------------------------------
    _VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})
    preview_warnings: list = []
    if not op_types:
        preview_warnings.append("missing_operation_types")
    if not affected_files:
        preview_warnings.append("missing_affected_files")
    if not _raw_patch.strip():
        preview_warnings.append("missing_patch_preview")
    if risk not in _VALID_RISK_LEVELS:
        preview_warnings.append("invalid_risk_level")
    if len(op_types) > 1:
        preview_warnings.append("multiple_operation_types")
    if patch_truncated:
        preview_warnings.append("patch_preview_truncated")
    preview_degraded: bool = bool(preview_warnings)

    # A preview is reviewable when the human has enough information to decide.
    # Missing diff, affected files, or operation types make review impossible.
    # Other warnings (truncation, multi-op, invalid risk) degrade but do not block review.
    _NON_REVIEWABLE = frozenset({
        "missing_operation_types",
        "missing_affected_files",
        "missing_patch_preview",
    })
    preview_reviewable: bool = not any(w in _NON_REVIEWABLE for w in preview_warnings)

    # A preview is applicable only when it is fully reviewable AND free of structural
    # warnings that make future apply unsafe (truncation, multi-op, invalid risk).
    # This does not trigger apply — it only marks the preview as a valid candidate.
    _NON_APPLICABLE_WARNINGS = frozenset({
        "patch_preview_truncated",
        "multiple_operation_types",
        "invalid_risk_level",
    })
    preview_applicable: bool = preview_reviewable and not any(
        w in _NON_APPLICABLE_WARNINGS for w in preview_warnings
    )

    lines = [
        f"CODE · vista previa — {action_label}",
        f"Objetivo: {envelope.get('summary', plan.get('raw_text', ''))}",
        f"Archivos afectados: {files_str}",
        f"Tipo: {op_str}",
        f"Intento de escritura: {envelope.get('write_intent_summary', '')}",
        f"Riesgo: {risk}",
        "",
        "Vista previa del cambio:",
        patch_text,
    ]
    if patch_truncated:
        lines.append(
            "(vista previa truncada — el diff completo está disponible en data.patch_preview)"
        )
    lines += ["", "¿Confirmo la aplicación?"]
    message = "\n".join(lines)

    # ------------------------------------------------------------------
    # Persist the apply-plan in context_store so the confirm flow can
    # retrieve it.  This is the bridge between preview and apply:
    #   preview → store_pending_plan(apply-plan) → user confirms →
    #   _execute_confirmed_plan retrieves apply-plan → code_pipeline
    #   executes with phase="apply" → builds AuthorizedPlan → runner.
    #
    # The apply-plan clones the original plan and injects:
    #   domain_payload.phase    = "apply"
    #   domain_payload.proposal = the full CodeProposalEnvelope
    #
    # A new context_id is generated for the apply step so the single-use
    # contract of context_store is preserved per phase.
    # ------------------------------------------------------------------
    apply_context_id: str = ""
    if preview_applicable:
        from ..context_store import store_pending_plan
        apply_payload = dict(payload)
        apply_payload["phase"] = "apply"
        apply_payload["proposal"] = envelope
        apply_plan = dict(plan)
        apply_plan["domain_payload"] = apply_payload

        apply_context_id = str(uuid.uuid4())
        store_pending_plan(
            context_id=apply_context_id,
            plan=apply_plan,
            operation=action,
            raw_text=plan.get("raw_text", ""),
        )

    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_CODE_PREVIEW,
        domain="CODE",
        message=message,
        data={
            "type": "code_preview",
            # UI smoke-test flags
            "preview_ready": True,
            "single_use": True,
            # Proposal identity
            "proposal": envelope,
            "proposal_id": proposal_id,
            "action": action,
            # operation_types lifted to top level for direct smoke-test access
            # (also available at data.proposal.proposal_artifacts.operation_types)
            "operation_types": op_types,
            # Change summary
            "summary": envelope.get("summary", ""),
            "affected_files": affected_files,
            "write_intent_summary": envelope.get("write_intent_summary", ""),
            # Diff preview
            "patch_preview": envelope.get("patch_preview", ""),
            "patch_preview_truncated": envelope.get("patch_preview_truncated", False),
            # Risk + confirmation gate
            "risk_level": risk,
            "requires_confirmation": True,
            # Apply-phase confirm handle (empty string when preview is not applicable)
            "apply_context_id": apply_context_id,
            # Degradation metadata
            "preview_degraded": preview_degraded,
            "preview_warnings": preview_warnings,
            "preview_reviewable": preview_reviewable,
            "preview_applicable": preview_applicable,
            # Executor status
            "propose_executor_live": _propose_executor is not None,
        },
        trace_id=plan.get("trace_id"),
        plan_id=plan.get("plan_id"),
    )


def _check_proposal_applicability(proposal: dict) -> str | None:
    """
    Semantic pre-gate: verify the proposal has all fields required for a safe apply.

    Returns a human-readable error string if the proposal should not be applied,
    or None if all checks pass.

    This runs BEFORE the mechanical ApplyChangeTool guards (proposal_id, single-use,
    blocked ops, write scope, workspace hash) so that structural issues are reported
    with clear, actionable messages rather than cryptic guard codes.

    Checks (in priority order):
      1. operation_types must be present (non-empty)
      2. affected_files must be present (non-empty)
      3. patch_preview must be present (non-empty, non-whitespace)
      4. risk_level must be canonical (low / medium / high)
      5. patch_preview must not be truncated (apply on partial diff is unsafe)
      6. operation_types must be a single type (multi-op ambiguity is not supported)
    """
    _VALID_RISK = frozenset({"low", "medium", "high"})

    op_types: list = proposal.get("proposal_artifacts", {}).get("operation_types", [])
    if not op_types:
        return (
            "La propuesta no tiene operation_types definidos. "
            "Genera una nueva propuesta antes de aplicar."
        )

    affected: list = proposal.get("affected_files", [])
    if not affected:
        return (
            "La propuesta no tiene archivos afectados (affected_files vacío). "
            "Genera una nueva propuesta antes de aplicar."
        )

    patch: str = proposal.get("patch_preview", "")
    if not patch.strip():
        return (
            "La propuesta no tiene vista previa del diff (patch_preview vacío). "
            "Genera una nueva propuesta antes de aplicar."
        )

    risk: str = proposal.get("risk_level", "")
    if risk not in _VALID_RISK:
        return (
            f"risk_level {risk!r} no es canónico (se esperaba low / medium / high). "
            "Genera una nueva propuesta antes de aplicar."
        )

    if proposal.get("patch_preview_truncated", False):
        return (
            "La vista previa del diff fue truncada. "
            "Aplicar sobre un diff incompleto es inseguro — genera una nueva propuesta."
        )

    if len(op_types) > 1:
        return (
            f"La propuesta contiene múltiples operation_types ({op_types}). "
            "v0 sólo admite un tipo de operación por apply — genera una nueva propuesta."
        )

    return None


def _apply_code_proposal(plan: dict, proposal: dict, payload: dict) -> DomainResult:
    """Apply a confirmed proposal through the exclusive audited runner path.

    Execution flow (no fallback, no ApplyChangeTool):
      single-use check
      → semantic pre-gate (_check_proposal_applicability)
      → _build_authorized_plan_from_kernel   ← governance binding
      → _build_runner_execution_request      ← pure translation
      → RunnerBackedExecutor.execute()       ← audited runner path
      → map RunnerExecutionResult → DomainResult

    Rules
    -----
    - AuthorizedPlan is built only AFTER all checks pass.
    - execution_id == plan_id (single kernel-issued identity).
    - No file mutation in preview.  Only this function mutates.
    - On RunnerBackedExecutor exception: return error, do NOT mark proposal used.
    - On RunnerBackedExecutor return (any status): mark proposal used, map result.
    """
    action = plan.get("action", "")
    proposal_id = proposal.get("proposal_id", "")

    # ------------------------------------------------------------------
    # Guard 0 — proposal_id required
    # Apply without an identity token is not permitted.
    # ------------------------------------------------------------------
    if not proposal_id:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CODE_APPLY,
            domain="CODE",
            message="proposal_id is required",
            data={"action": action},
            error={"type": "ExecutionPlanViolation", "message": "proposal_id is required"},
        )

    # ------------------------------------------------------------------
    # Guard 1 — Single-use enforcement
    # Prevents double-application of the same proposal regardless of runner
    # outcome.  Checked BEFORE building AuthorizedPlan to fail fast.
    # ------------------------------------------------------------------
    if proposal_id in _applied_proposals:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CODE_APPLY,
            domain="CODE",
            message="Esta propuesta ya fue aplicada (single-use violation).",
            data={
                "proposal_id": proposal_id,
                "action": action,
                "guard_failure": "ProposalAlreadyApplied",
            },
            error={
                "type": "ProposalAlreadyApplied",
                "message": f"Proposal {proposal_id!r} has already been applied.",
            },
        )

    # ------------------------------------------------------------------
    # Guard 2 — Semantic pre-gate
    # Structural checks before any executor call.
    # ------------------------------------------------------------------
    applicability_error = _check_proposal_applicability(proposal)
    if applicability_error:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CODE_APPLY,
            domain="CODE",
            message=f"Propuesta no aplicable: {applicability_error}",
            data={
                "proposal_id": proposal_id,
                "action": action,
                "guard_failure": "NotApplicable",
            },
            error={"type": "NotApplicable", "message": applicability_error},
        )

    # ------------------------------------------------------------------
    # Guard 3 — Invalid changes
    # If proposal carries a "changes" list but every entry is filtered out
    # by _extract_file_replace_changes, refuse to continue.  Passing None
    # (stub / no-changes path) is still valid — runner skips apply phase.
    # ------------------------------------------------------------------
    _raw_changes = proposal.get("changes")
    if _raw_changes:
        _extracted = _extract_file_replace_changes(proposal)
        if not _extracted:
            return make_domain_result(
                ok=False,
                result_type=RESULT_TYPE_CODE_APPLY,
                domain="CODE",
                message="no valid changes after validation",
                data={"proposal_id": proposal_id, "action": action},
                error={"type": "InvalidChanges", "message": "no valid changes after validation"},
            )

    # ------------------------------------------------------------------
    # Build AuthorizedPlan — governance binding.
    # Only constructed AFTER all checks pass, BEFORE any mutation.
    # execution_id == plan_id (kernel plan is the single authority).
    # ------------------------------------------------------------------
    authorized_plan = _build_authorized_plan_from_kernel(plan)

    # ------------------------------------------------------------------
    # Build RunnerExecutionRequest — pure translation, no execution.
    # ------------------------------------------------------------------
    request = _build_runner_execution_request(plan, proposal, authorized_plan)

    # ------------------------------------------------------------------
    # Execute — via the registered code_executor agent (audited runner).
    # No fallback.  If this raises, the proposal is NOT marked used so
    # the caller can retry after fixing the infrastructure issue.
    # ------------------------------------------------------------------
    from ..agents.registry import get_agent
    _agent = get_agent("code_executor")
    # Capture invocation metadata once — propagated into audit_summary on every path.
    _agent_invocation = {
        "agent_name":             _agent["name"],
        "agent_version":          _agent["version"],
        "agent_requires_review":  _agent["requires_review"],
        "agent_capability_scope": _agent["capability_scope"],
    }
    try:
        runner_result = _agent["entrypoint"](request)
    except Exception as exc:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CODE_APPLY,
            domain="CODE",
            message="Runner raised an unexpected exception.",
            data={
                "proposal_id": proposal_id,
                "action": action,
                "guard_failure": "RunnerException",
                "audit_summary": {
                    "action": action,
                    "files_changed": 0,
                    "execution_source": "runner",
                    "execution_id": authorized_plan.execution_id,
                    "plan_id": authorized_plan.plan_id,
                    "policy_id": authorized_plan.policy_id,
                    "capability_scope": authorized_plan.capability_scope,
                    "agent_invocation": _agent_invocation,
                },
            },
            error={"type": "RunnerException", "message": str(exc)},
        )

    # Persist agent_invocation + request_snapshot to metadata.json (best-effort, non-fatal).
    # Closes PATH A trazabilidad gaps:
    #   agent_invocation — GET /api/code/executions/{id} exposes agent metadata.
    #   request_snapshot — enables rerun from the API for kernel-originated executions.
    #
    # PATH A snapshot subset vs PATH B:
    #   repo_path, changes, plan_id, policy_id, capability_scope, metadata — all present.
    #   test_spec, validation_spec, code — not carried through the kernel pipeline; None.
    #   mode = "kernel" distinguishes from HTTP-originated executions ("code_execution").
    _request_snapshot = {
        "repo_path":        request.repo_path,
        "changes":          request.changes,
        "test_spec":        None,
        "validation_spec":  None,
        "source":           "assistant_os",
        "mode":             "kernel",
        "metadata":         request.metadata,
        "plan_id":          authorized_plan.plan_id,
        "policy_id":        authorized_plan.policy_id,
        "capability_scope": authorized_plan.capability_scope,
        "code":             None,
    }
    patch_execution_metadata(
        runner_result.execution_id,
        {
            "agent_invocation": _agent_invocation,
            "request_snapshot": _request_snapshot,
        },
    )

    # Mark proposal used AFTER runner dispatch (regardless of runner outcome).
    # This prevents retry on partial applies that may have modified the workspace.
    # proposal_id is guaranteed non-empty by Guard 0.
    _applied_proposals.add(proposal_id)

    # ------------------------------------------------------------------
    # Map RunnerExecutionResult → DomainResult
    # ------------------------------------------------------------------
    execution_id = runner_result.execution_id
    final_status = runner_result.final_status or ""
    modified = runner_result.modified_files or []

    audit_summary = {
        "action": action,
        "files_changed": len(modified),
        "execution_source": "runner",
        "execution_id": authorized_plan.execution_id,
        "plan_id": authorized_plan.plan_id,
        "policy_id": authorized_plan.policy_id,
        "capability_scope": authorized_plan.capability_scope,
        "promoted_files": runner_result.promoted_files or [],
        "promotion_status": runner_result.promotion_status,
        "agent_invocation": _agent_invocation,
    }

    if final_status == "needs_review":
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CODE_APPLY,
            domain="CODE",
            message="Aplicación completada pero requiere revisión manual antes de aceptarse.",
            data={
                "proposal_id": proposal_id,
                "action": action,
                "execution_id": execution_id,
                "status": final_status,
                "audit_summary": audit_summary,
            },
            error={
                "type": "NeedsReview",
                "message": "Runner returned needs_review — manual validation required before accepting.",
            },
        )

    if runner_result.error or final_status == "failed":
        error_msg = runner_result.error or f"Runner failed with status: {final_status}"
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CODE_APPLY,
            domain="CODE",
            message=f"Aplicación fallida: {error_msg}",
            data={
                "proposal_id": proposal_id,
                "action": action,
                "execution_id": execution_id,
                "status": final_status,
                "guard_failure": "RunnerFailed",
                "audit_summary": audit_summary,
            },
            error={"type": "RunnerFailed", "message": error_msg},
        )

    promoted = runner_result.promoted_files or []
    lines = [
        "CODE · aplicado vía runner auditado",
        f"✓ Ejecución auditada: {execution_id}",
        f"Archivos modificados: {len(modified)}",
    ]
    if modified:
        lines.append(f"  Modificados: {', '.join(modified)}")
    if promoted:
        lines.append(f"  Propagados al repo: {', '.join(promoted)}")
    lines.append(f"Status: {final_status or 'success'}")

    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_CODE_APPLY,
        domain="CODE",
        message="\n".join(lines),
        data={
            "type": "code_apply",
            "apply_ready": True,
            "single_use": True,
            "execution_id": execution_id,
            "status": final_status or "success",
            "proposal_id": proposal_id,
            "action": action,
            "modified_files": modified,
            "created_files": [],
            "applied_files": modified,
            "report_json_path": runner_result.report_json_path,
            "report_md_path": runner_result.report_md_path,
            "audit_summary": audit_summary,
            "changes_detail": runner_result.changes_detail or [],
            "promoted_files": promoted,
            "promotion_status": runner_result.promotion_status,
        },
        trace_id=plan.get("trace_id"),
        plan_id=plan.get("plan_id"),
    )


# ---------------------------------------------------------------------------
# AuthorizedPlan factory (apply path only)
#
# AuthorizedPlan is constructed HERE — inside the pipeline, after the user
# has confirmed the proposal.  It is NEVER constructed during the preview
# phase.  execution_id == plan_id so the kernel plan is the single authority.
# ---------------------------------------------------------------------------

_ACTION_CAPABILITY_SCOPE: dict[str, list[str]] = {
    ACTION_CODE_FIX:    ["code_fix"],
    ACTION_CODE_CREATE: ["code_create"],
}


def _build_authorized_plan_from_kernel(plan: dict) -> "AuthorizedPlan":
    """
    Build an AuthorizedPlan from the kernel ExecutionPlan.

    Rules
    -----
    execution_id  = plan["plan_id"]  — kernel plan is the single identity source.
    plan_id       = plan["plan_id"]  — same value; no separate execution UUID.
    policy_id     = "default"        — governed by orchestrator, not code_api.
    capability_scope = action-derived (code_fix | code_create | code_execute).
    authorized_plan_hash = SHA-256 of the canonicalized plan identity so every
                           execution is traceable back to the kernel plan content.
    """
    from ..sandbox.authorized_plan import AuthorizedPlan

    plan_id = plan.get("plan_id")
    action = plan.get("action", "")
    workspace = (plan.get("domain_payload") or {}).get("workspace", "")

    capability_scope = _ACTION_CAPABILITY_SCOPE.get(action, ["code_execute"])

    plan_identity = {
        "plan_id": plan_id,
        "action": action,
        "workspace": workspace,
        "capability_scope": sorted(capability_scope),
    }
    authorized_plan_hash = hashlib.sha256(
        json.dumps(plan_identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    ap = AuthorizedPlan(
        execution_id=plan_id,
        plan_id=plan_id,
        authorized_plan_hash=authorized_plan_hash,
        policy_id="default",
        capability_scope=capability_scope,
    )
    ap.validate()
    return ap


# ---------------------------------------------------------------------------
# RunnerExecutionRequest bridge (apply path only)
#
# _build_runner_execution_request translates a confirmed CodeProposalEnvelope
# into a RunnerExecutionRequest.  Pure translation — no execution, no IO.
#
# Changes format
# --------------
# "file_replace" is used when the proposal carries full file content (real
# executor path, e.g. Claude Code agent produces full file content).
# None is used when only a patch diff is available (stub executor) — the
# runner still runs (workspace, validation, report, audit) but Phase 2
# (ApplyEngine) is skipped, so modified_files == [].  This is intentionally
# honest: stub execution = no filesystem mutation, but the governance binding
# and audit trail ARE real.
#
# Validation rules (enforced here, before RunnerService sees the request):
# - paths must be relative (no leading /, no ..)
# - content must not be empty for file_replace
# - changes list may be None (Phase 2 skip) but never empty list
# ---------------------------------------------------------------------------


def _extract_file_replace_changes(proposal: dict) -> list | None:
    """
    Extract applicable changes from a CodeProposalEnvelope.

    Supports two ops:
      file_replace — full file content (real executor or CREATE path).
      patch        — unified diff applied to an existing file (M2D).

    Returns
    -------
    list  : [{op: "file_replace"|"patch", path: str, ...}, ...] when the
            proposal carries actionable changes.
    None  : when no changes are present (stub executor path).  RunnerService
            skips Phase 2 (apply) but still produces an audited execution record.

    Validation
    ----------
    Rejects absolute paths and path-traversal entries so that ApplyEngine
    never receives unsafe inputs from this path.
    """
    raw = proposal.get("changes")
    if not raw or not isinstance(raw, list):
        return None

    valid = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        path = c.get("path", "")
        op = c.get("op", "file_replace")  # default for backward compat
        # Reject empty paths, absolute paths, and traversal
        if not path or path.startswith("/") or path.startswith("\\") or ".." in path.split("/"):
            continue

        if op == "file_replace":
            content = c.get("content")
            # Reject missing or empty content
            if content is None or content == "":
                continue
            valid.append({"op": "file_replace", "path": path, "content": content})

        elif op == "patch":
            patch_text = c.get("patch", "")
            # Reject empty patch texts
            if not patch_text or not patch_text.strip():
                continue
            valid.append({"op": "patch", "path": path, "patch": patch_text})

    return valid or None


def _build_runner_execution_request(
    plan: dict,
    proposal: dict,
    authorized_plan: "AuthorizedPlan",
) -> "RunnerExecutionRequest":
    """
    Translate a confirmed CodeProposalEnvelope + AuthorizedPlan into a
    RunnerExecutionRequest.  Pure translation — no execution, no IO.

    execution_id    = authorized_plan.execution_id (== kernel plan_id).
    repo_path       = domain_payload["workspace"].
    changes         = file_replace list from proposal (or None for stub path).
    authorized_plan = the governance binding built from the kernel plan.
    """
    from ..runners.runner_models import RunnerExecutionRequest

    payload = plan.get("domain_payload") or {}
    workspace = payload.get("workspace", "")
    action = plan.get("action", "")

    changes = _extract_file_replace_changes(proposal)

    return RunnerExecutionRequest(
        execution_id=authorized_plan.execution_id,
        repo_path=workspace,
        changes=changes,
        metadata={
            "source": "assistant_os",
            "domain": "CODE",
            "action": action,
            "plan_id": authorized_plan.plan_id,
        },
        authorized_plan=authorized_plan,
    )


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

def _validate_write_scope_early(target_file: str) -> str | None:
    """
    Quick pre-check for obvious unsafe paths before calling ProposeChangeTool.
    Returns an error string or None if the path looks safe.
    """
    if not target_file:
        return None  # No specific file; defer full validation to the tool

    if os.path.isabs(target_file):
        return f"Absolute paths are not allowed: {target_file!r}"

    parts = target_file.replace("\\", "/").split("/")
    if ".." in parts:
        return f"Path traversal rejected: {target_file!r}"

    return None


def _validate_workspace(workspace: str) -> str | None:
    """
    Validate the workspace root before any tool is invoked.

    Checks (in order):
      1. Non-empty — required for mutating operations
      2. Absolute path — relative roots are ambiguous and unsafe
      3. Exists on disk — prevents silent hash mismatches on a phantom path
      4. Is a directory — guards against accidentally pointing at a file

    Future: add allowed-roots check here when a workspace ACL config is added.

    Returns an error message string or None if the workspace is valid.
    """
    if not workspace or not workspace.strip():
        return "workspace is required for mutating CODE operations"

    if not os.path.isabs(workspace):
        return f"workspace must be an absolute path: {workspace!r}"

    if not os.path.exists(workspace):
        return f"workspace does not exist: {workspace!r}"

    if not os.path.isdir(workspace):
        return f"workspace is not a directory: {workspace!r}"

    return None
