"""
Tool — Claude Code Review / Explain

Read-only tool that forwards a code analysis request to the remote Claude Code
executor and returns a ToolResult.  This tool has no side effects.

Input keys
----------
action      : str — ACTION_CODE_EXPLAIN | ACTION_CODE_REVIEW
target_file : str — Relative path of the file to analyse (within workspace root)
workspace   : str — Absolute path to the workspace root
context     : str — Additional instructions / question from the user (optional)

Output (ToolResult.data on success)
------------------------------------
analysis    : str — Free-text analysis returned by Claude Code
action      : str — Echo of input action
target_file : str — Echo of target_file

Note on the executor
--------------------
_DEFAULT_EXECUTOR is a stub that returns a placeholder response.
Replace it (or pass a custom executor to ReviewCodeTool.__init__) with a
callable that invokes the real Claude Code remote executor.

Executor contract:
    executor(input: dict) -> dict
        input  keys: action, target_file, workspace, context
        output keys: ok (bool), analysis (str), error (str, on failure)
"""

from __future__ import annotations

from typing import Callable, Optional

from ..base.tool import Tool
from ..base.tool_result import ToolResult
from ..base.tool_error import ToolError

_PROVIDER = "claude_code"
_OPERATION = "review_code"


def _default_executor(input: dict) -> dict:
    """
    Stub executor.  Returns a placeholder analysis so the pipeline
    can be exercised without a live Claude Code instance.

    Replace this (or pass executor= to ReviewCodeTool) for production use.
    """
    target = input.get("target_file", "code")
    action = input.get("action", "CODE_REVIEW")
    return {
        "ok": True,
        "analysis": (
            f"[stub] {action} of {target!r} — executor not configured. "
            "Configure a real executor to get actual analysis."
        ),
    }


class ReviewCodeTool(Tool):
    """Read-only code analysis tool (explain + review)."""

    def __init__(self, executor: Optional[Callable] = None) -> None:
        self._executor = executor or _default_executor

    def execute(self, input: dict) -> ToolResult:
        metadata = {
            "provider": _PROVIDER,
            "operation": _OPERATION,
            "action": input.get("action", ""),
            "target_file": input.get("target_file", ""),
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
                    code="ReviewFailed",
                    message=result.get("error", "Review executor returned an error"),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        return ToolResult(
            ok=True,
            data={
                "analysis": result.get("analysis", ""),
                "action": input.get("action", ""),
                "target_file": input.get("target_file", ""),
            },
            error=None,
            metadata=metadata,
        )
