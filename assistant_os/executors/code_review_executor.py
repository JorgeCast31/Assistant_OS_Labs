"""
Real read-only executor for CODE_EXPLAIN and CODE_REVIEW.

Compatible with register_review_executor() in code_pipeline.

This module provides a factory (build_claude_review_executor) that returns a
callable matching the ReviewCodeTool executor contract:

    fn(input: dict) -> dict
        input keys : action, target_file, workspace, context
        output keys: ok (bool), analysis (str)  — or ok=False, error (str)

Architecture position
---------------------
This is a concrete executor implementation — it bridges the tool-level executor
contract (stateless dict-in/dict-out) to the Anthropic Claude API.

It is NOT part of code_pipeline and NOT part of any tool class.
It is injected at application startup via register_review_executor().

Mutating actions (CODE_FIX / CODE_CREATE) are NOT handled here.
ProposeChangeTool and ApplyChangeTool have their own separate executor injection.

File reading
------------
If both target_file and workspace are provided, the file is read and included
in the prompt as a fenced code block.  Hard limits prevent sending files that
are too large:
  - _MAX_FILE_BYTES: 32 768 bytes (32 KB) — truncates the API context safely
  - Binary files: read with errors="replace" to avoid decode failures

Context-only mode
-----------------
If target_file is empty (or the file cannot be found), the executor falls back
to analysing purely from the user's context string.  It does NOT fail — it
returns a clean analysis noting that no file was provided.

Error handling
--------------
Only genuine failures (file read errors, API exceptions) return ok=False.
Missing optional fields are handled gracefully with empty-string fallbacks.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

# Maximum file size accepted for analysis.  Files larger than this are rejected
# with a clean error rather than silently truncated (which would mislead the AI).
_MAX_FILE_BYTES: int = 32_768  # 32 KB

_SYSTEM_PROMPT = """\
You are an expert code analyst embedded in a developer assistant.

Your role:
- For CODE_EXPLAIN requests: describe what the code does, its structure, key \
patterns, and any non-obvious behaviours.  Be concise and developer-friendly.
- For CODE_REVIEW requests: identify bugs, design issues, security concerns, \
and concrete improvement suggestions.  Prioritise actionable findings.

Guidelines:
- Use bullet points for lists of findings or features.
- Keep responses under 400 words unless the file is large and complex.
- Do not repeat the code back verbatim.
- If no file is provided, respond based on the user question alone.
"""


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def _read_target_file(workspace: str, target_file: str) -> tuple[Optional[str], Optional[str]]:
    """
    Read the contents of target_file relative to workspace.

    Returns (content, error_message).  Exactly one will be None:
      - (content, None)  on success
      - (None, message)  on any failure
      - (None, None)     when target_file or workspace is empty (context-only mode)
    """
    if not target_file or not workspace:
        return None, None  # context-only mode — not an error

    abs_path = os.path.normpath(os.path.join(workspace, target_file))

    # Guard: reject paths that escape the workspace root (traversal attempt)
    workspace_norm = os.path.normpath(workspace)
    if not abs_path.startswith(workspace_norm + os.sep) and abs_path != workspace_norm:
        return None, f"Path traversal rejected: {target_file!r} escapes workspace"

    if not os.path.exists(abs_path):
        return None, f"File not found: {target_file!r}"

    if not os.path.isfile(abs_path):
        return None, f"Not a regular file: {target_file!r}"

    file_size = os.path.getsize(abs_path)
    if file_size > _MAX_FILE_BYTES:
        return None, (
            f"File too large to analyse: {target_file!r} "
            f"({file_size:,} bytes; limit is {_MAX_FILE_BYTES:,} bytes). "
            "Split the file or specify a smaller excerpt."
        )

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), None
    except OSError as exc:
        return None, f"Cannot read {target_file!r}: {exc}"


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _build_user_prompt(
    action: str,
    target_file: str,
    file_content: Optional[str],
    context: str,
) -> str:
    """
    Build the user-turn prompt sent to Claude.

    Structure:
      [Action directive]
      [File path if present]
      [User question / context if present]
      [File content block if available, else notice]
    """
    parts: list[str] = []

    if action == "CODE_EXPLAIN":
        parts.append("Please explain the following code clearly and concisely.")
    else:
        parts.append(
            "Please review the following code. Identify any bugs, design issues, "
            "security concerns, and concrete improvements."
        )

    if target_file:
        parts.append(f"File: `{target_file}`")

    if context and context.strip():
        parts.append(f"User question / context: {context.strip()}")

    if file_content is not None:
        # Detect language from extension for syntax-highlighted fences
        ext = os.path.splitext(target_file)[1].lstrip(".") if target_file else ""
        fence_lang = ext if ext else ""
        parts.append(f"```{fence_lang}\n{file_content}\n```")
    else:
        parts.append(
            "(No file content available. "
            "Responding based on context and file path only.)"
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_claude_review_executor(
    client=None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> Callable[[dict], dict]:
    """
    Return a real executor callable for CODE_EXPLAIN / CODE_REVIEW.

    Parameters
    ----------
    client : anthropic.Anthropic | None
        An already-constructed Anthropic client.  If None, one is built from
        the ANTHROPIC_API_KEY environment variable (loaded via config.py).
    model : str | None
        Claude model ID.  Defaults to CODE_REVIEW_MODEL from config.py
        (claude-haiku-4-5-20251001).
    max_tokens : int | None
        Token budget for analysis responses.  Defaults to CODE_REVIEW_MAX_TOKENS
        from config.py (1024).

    Returns
    -------
    Callable[[dict], dict]
        Compatible with register_review_executor() and ReviewCodeTool's
        executor= parameter.

    Wiring example (app startup)
    ----------------------------
        from assistant_os.executors.code_review_executor import build_claude_review_executor
        from assistant_os.pipelines.code_pipeline import register_review_executor

        register_review_executor(build_claude_review_executor())

    Executor input contract
    -----------------------
        action      : "CODE_EXPLAIN" | "CODE_REVIEW"
        target_file : str — relative path within workspace (may be "")
        workspace   : str — absolute workspace root (may be "")
        context     : str — raw user text / question

    Executor output contract (on success)
    --------------------------------------
        ok       : True
        analysis : str — concise analysis from Claude

    Executor output contract (on failure)
    --------------------------------------
        ok    : False
        error : str — human-readable failure reason
    """
    import anthropic as _anthropic
    from ..config import CODE_REVIEW_MODEL, CODE_REVIEW_MAX_TOKENS, ANTHROPIC_API_KEY

    _model = model or CODE_REVIEW_MODEL
    _max_tokens = max_tokens or CODE_REVIEW_MAX_TOKENS

    if client is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to your .env file or environment before calling "
                "build_claude_review_executor()."
            )
        client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def executor(inp: dict) -> dict:
        action: str = inp.get("action", "CODE_REVIEW")
        target_file: str = inp.get("target_file", "")
        workspace: str = inp.get("workspace", "")
        context: str = inp.get("context", "")

        # Step 1: read file (None content = context-only mode, not an error)
        file_content, read_error = _read_target_file(workspace, target_file)
        if read_error:
            return {"ok": False, "error": read_error}

        # Step 2: build prompt
        prompt = _build_user_prompt(action, target_file, file_content, context)

        # Step 3: call Claude
        try:
            response = client.messages.create(
                model=_model,
                max_tokens=_max_tokens,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            analysis: str = response.content[0].text
            return {"ok": True, "analysis": analysis}

        except _anthropic.AuthenticationError as exc:
            return {"ok": False, "error": f"API authentication failed: {exc}"}
        except _anthropic.RateLimitError as exc:
            return {"ok": False, "error": f"API rate limit exceeded: {exc}"}
        except _anthropic.APIStatusError as exc:
            return {"ok": False, "error": f"Claude API error {exc.status_code}: {exc.message}"}
        except Exception as exc:
            return {"ok": False, "error": f"Unexpected error calling Claude: {exc}"}

    return executor
