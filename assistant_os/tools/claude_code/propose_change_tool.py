"""
Tool — Claude Code Propose Change

Asks the remote Claude Code executor for a change proposal and returns a
CodeProposalEnvelope wrapped in a ToolResult.

This tool is PREVIEW-ONLY — it must produce zero side effects:
  - no file writes
  - no git changes
  - no patch application

Input keys
----------
action              : str  — ACTION_CODE_FIX | ACTION_CODE_CREATE
target_file         : str  — Primary file to change (relative path)
workspace           : str  — Absolute path to workspace root
context             : str  — Change description / instructions from the user
allowed_write_scope : list — Allowed relative file paths (default: [target_file])

Output (ToolResult.data on success)
------------------------------------
Returns a CodeProposalEnvelope dict (see contracts.CodeProposalEnvelope) with:
  proposal_id, action, summary, affected_files, write_intent_summary,
  patch_preview, risk_level, proposal_artifacts, requires_confirmation,
  workspace_hash, allowed_write_scope

Security guardrails enforced by this tool
------------------------------------------
- v0 file-count limit: proposals may not touch more than V0_MAX_TOUCHED_FILES files
- Blocked operations: delete / rename / move are rejected in v0
- workspace_hash is computed from mtime+size of affected_files at proposal time
  for integrity validation at apply time
"""

from __future__ import annotations

import hashlib
import os
import uuid
from typing import Callable, Optional

from ..base.tool import Tool
from ..base.tool_result import ToolResult
from ..base.tool_error import ToolError

_PROVIDER = "claude_code"
_OPERATION = "propose_change"

# v0 hard limit: a proposal may not touch more than this many files
V0_MAX_TOUCHED_FILES = 5

# Operations blocked in v0 (destructive / hard-to-reverse)
V0_BLOCKED_OPERATIONS: frozenset = frozenset({"delete", "rename", "move"})

# patch_preview UI safety caps — whichever limit is hit first triggers truncation
_PATCH_PREVIEW_MAX_LINES = 150
_PATCH_PREVIEW_MAX_CHARS = 8192


def _default_executor(input: dict) -> dict:
    """
    Stub executor.  Returns a minimal valid proposal so the pipeline can be
    exercised without a live Claude Code instance.

    Replace this (or pass executor= to ProposeChangeTool) for production use.

    Executor contract:
        executor(input: dict) -> dict
            input  keys: action, target_file, workspace, context, allowed_write_scope
            output keys: ok (bool), summary (str), patch_preview (str),
                         affected_files (list[str]), write_intent_summary (str),
                         operation_types (list[str]), risk_level (str),
                         error (str, on failure)
    """
    target_file = input.get("target_file", "unknown.py")
    action = input.get("action", "CODE_FIX")
    return {
        "ok": True,
        "summary": f"[stub] {action} proposal for {target_file!r}",
        "patch_preview": (
            f"--- a/{target_file}\n"
            f"+++ b/{target_file}\n"
            f"@@ stub diff — executor not configured @@\n"
        ),
        "affected_files": [target_file],
        "write_intent_summary": f"Modifies {target_file}",
        "operation_types": ["modify"],
        "risk_level": "medium",
    }


def _truncate_patch_preview(patch: str) -> tuple[str, bool]:
    """
    Enforce UI-safe size limits on a raw patch string.

    Applies two caps in order:
      1. Character cap  (_PATCH_PREVIEW_MAX_CHARS): hard byte limit, cuts cleanly
         at the last newline within the cap to avoid truncating mid-line.
      2. Line cap       (_PATCH_PREVIEW_MAX_LINES): applied after the char cap.

    Returns (safe_patch, was_truncated).  The original patch is never mutated.
    """
    truncated = False

    # Cap 1: character limit
    if len(patch) > _PATCH_PREVIEW_MAX_CHARS:
        cut = patch[:_PATCH_PREVIEW_MAX_CHARS]
        last_nl = cut.rfind("\n")
        patch = cut[:last_nl] if last_nl > 0 else cut
        patch += f"\n... (truncated — exceeds {_PATCH_PREVIEW_MAX_CHARS} chars)"
        truncated = True

    # Cap 2: line limit (applied to whatever survived the char cap)
    lines = patch.splitlines()
    if len(lines) > _PATCH_PREVIEW_MAX_LINES:
        patch = "\n".join(lines[:_PATCH_PREVIEW_MAX_LINES])
        patch += f"\n... (truncated — exceeds {_PATCH_PREVIEW_MAX_LINES} lines)"
        truncated = True

    return patch, truncated


def compute_workspace_hash(workspace: str, affected_files: list) -> str:
    """
    Hash the mtime + size + content of each affected file to detect workspace
    changes between proposal time and apply time.

    Returns a 16-character hex string (SHA-256 prefix).
    """
    parts = []
    for rel_path in sorted(affected_files):
        abs_path = os.path.join(workspace, rel_path) if workspace else rel_path
        try:
            stat = os.stat(abs_path)
            with open(abs_path, "rb") as fh:
                content_hash = hashlib.sha256(fh.read()).hexdigest()[:16]
            parts.append(f"{rel_path}:{stat.st_mtime}:{stat.st_size}:{content_hash}")
        except OSError:
            parts.append(f"{rel_path}:missing")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


class ProposeChangeTool(Tool):
    """Generate a change proposal without applying it (preview path)."""

    def __init__(self, executor: Optional[Callable] = None) -> None:
        self._executor = executor or _default_executor

    def execute(self, input: dict) -> ToolResult:
        action = input.get("action", "")
        target_file = input.get("target_file", "")
        workspace = input.get("workspace", "")
        allowed_scope: list = input.get("allowed_write_scope") or (
            [target_file] if target_file else []
        )

        metadata = {
            "provider": _PROVIDER,
            "operation": _OPERATION,
            "action": action,
            "target_file": target_file,
        }

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
                    code="ProposalFailed",
                    message=result.get("error", "Proposal executor returned an error"),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        # Guard: blocked operation types (v0)
        op_types: list = result.get("operation_types", [])
        blocked = [op for op in op_types if op in V0_BLOCKED_OPERATIONS]
        if blocked:
            return ToolResult(
                ok=False, data=None,
                error=ToolError(
                    code="BlockedOperationV0",
                    message=(
                        f"v0 does not support: {blocked}. "
                        "Delete / rename / move operations are deferred to v1."
                    ),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        # Guard: file-count limit (v0)
        affected_files: list = result.get("affected_files", [target_file] if target_file else [])
        if len(affected_files) > V0_MAX_TOUCHED_FILES:
            return ToolResult(
                ok=False, data=None,
                error=ToolError(
                    code="TooManyFilesV0",
                    message=(
                        f"Proposal touches {len(affected_files)} files; "
                        f"v0 limit is {V0_MAX_TOUCHED_FILES}."
                    ),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        # Compute workspace hash for integrity validation at apply time
        workspace_hash = compute_workspace_hash(workspace, affected_files) if workspace else ""

        # Truncate patch_preview to UI-safe size before storing in the envelope
        raw_patch = result.get("patch_preview", "")
        safe_patch, patch_was_truncated = _truncate_patch_preview(raw_patch)

        envelope: dict = {
            "proposal_id": str(uuid.uuid4()),
            "action": action,
            "summary": result.get("summary", ""),
            "affected_files": affected_files,
            "write_intent_summary": result.get("write_intent_summary", ""),
            "patch_preview": safe_patch,
            "patch_preview_truncated": patch_was_truncated,
            "risk_level": result.get("risk_level", "medium"),
            "proposal_artifacts": {
                "operation_types": op_types,
                **(result.get("artifacts") or {}),
            },
            "requires_confirmation": True,
            "workspace_hash": workspace_hash,
            "allowed_write_scope": allowed_scope,
        }

        return ToolResult(ok=True, data=envelope, error=None, metadata=metadata)
