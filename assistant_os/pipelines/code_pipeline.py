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

import os
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
        "context": plan.get("raw_text", ""),
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

    if phase == "apply" and proposal:
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
        "context": plan.get("raw_text", ""),
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
    """Apply a confirmed proposal after all integrity checks pass."""
    from ..tools.claude_code.apply_change_tool import ApplyChangeTool

    action = plan.get("action", "")
    workspace: str = payload.get("workspace", "")

    # Semantic pre-gate: structural checks before mechanical ApplyChangeTool guards
    applicability_error = _check_proposal_applicability(proposal)
    if applicability_error:
        proposal_id = proposal.get("proposal_id", "")
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

    # Inject the pipeline-scoped applied-proposals set for single-use tracking
    tool_result = ApplyChangeTool(applied_proposals=_applied_proposals).execute({
        "proposal": proposal,
        "workspace": workspace,
        "context_id": plan.get("trace_id", ""),
    })

    proposal_id = proposal.get("proposal_id", "")

    if not tool_result.ok:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_CODE_APPLY,
            domain="CODE",
            message=f"Error al aplicar el cambio: {tool_result.error.message}",
            data={
                "proposal_id": proposal_id,
                "action": action,
                "guard_failure": tool_result.error.code,
            },
            error={"type": tool_result.error.code, "message": tool_result.error.message},
        )

    applied = tool_result.data.get("applied_files", [])
    created = tool_result.data.get("created_files", [])
    modified = tool_result.data.get("modified_files", [])
    apply_mode: str = tool_result.data.get("apply_mode", "stub")

    lines = [
        "CODE · aplicado",
        "✓ Cambios aplicados",
        f"Archivos modificados: {len(modified)}",
        f"Archivos creados: {len(created)}",
    ]
    if created:
        lines.append(f"  Creados: {', '.join(created)}")
    if modified:
        lines.append(f"  Modificados: {', '.join(modified)}")
    if apply_mode == "stub":
        lines.append("(modo stub — ningún archivo fue escrito en disco)")

    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_CODE_APPLY,
        domain="CODE",
        message="\n".join(lines),
        data={
            "type": "code_apply",
            # UI smoke-test flags
            "apply_ready": True,
            "single_use": True,
            # Executor mode — "stub" until a real apply executor is wired
            "apply_mode": apply_mode,
            # Proposal identity
            "proposal_id": proposal_id,
            "action": action,
            # Applied file lists
            "applied_files": applied,
            "created_files": created,
            "modified_files": modified,
            # Structured audit record for traceability
            "audit_summary": {
                "proposal_id": proposal_id,
                "action": action,
                "applied_count": len(applied),
                "created_count": len(created),
                "modified_count": len(modified),
                "apply_mode": apply_mode,
                "workspace": workspace,
            },
        },
        trace_id=plan.get("trace_id"),
        plan_id=plan.get("plan_id"),
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
