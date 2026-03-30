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
  - _MAX_FILE_BYTES: 65 536 bytes (64 KB) — keeps API context manageable
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

import logging
import os
from typing import Callable, Optional

_log = logging.getLogger(__name__)

# Maximum file size accepted for analysis.  Files larger than this are rejected
# with a clean error rather than silently truncated (which would mislead the AI).
_MAX_FILE_BYTES: int = 65_536  # 64 KB

_SYSTEM_PROMPT = """\
Eres un analista de código experto integrado en un asistente de desarrollo.

Tu función:
- Para solicitudes CODE_EXPLAIN: describe qué hace el código, su estructura, \
los patrones clave y los comportamientos no obvios. Sé conciso y orientado al desarrollador.
- Para solicitudes CODE_REVIEW: identifica bugs, problemas de diseño, riesgos \
de seguridad y sugerencias de mejora concretas. Prioriza los hallazgos accionables.

Reglas de idioma:
- Responde SIEMPRE en español, excepto lo siguiente:
  - Nombres de funciones, clases, variables e identificadores: en su forma original.
  - Nombres de archivos, rutas y ramas git: en su forma original.
  - Bloques de código, diffs y fragmentos de código: sin traducir.
  - Términos técnicos de uso habitual en inglés por desarrolladores (commit, token,
    endpoint, API, framework, pipeline, etc.): pueden permanecer en inglés cuando
    sea natural.
- Tono técnico y profesional.

Directrices adicionales:
- Usa listas con viñetas para hallazgos o características.
- Mantén las respuestas en menos de 400 palabras salvo que el archivo sea grande \
y complejo.
- No repitas el código textualmente.
- CRÍTICO: Cuando se proporcione contenido de archivo en el prompt, basa tu \
análisis EXCLUSIVAMENTE en ese código real. NO produzcas consejos genéricos ni \
asumas nada que no esté en el contenido proporcionado. Referencia números de \
línea específicos, nombres de funciones y patrones del código real.
- Si no se proporciona contenido de archivo (solo una ruta o pregunta), \
indícalo explícitamente y responde basándote en lo que puedas inferir.
"""


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def _resolve_and_check_path(
    workspace: str,
    target_file: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve and security-check a file path.
    Returns (abs_path, error) — abs_path is None on error.
    """
    if not target_file or not workspace:
        return None, None  # context-only mode — not an error

    abs_path = os.path.normpath(os.path.join(workspace, target_file))
    workspace_norm = os.path.normpath(workspace)
    if not abs_path.startswith(workspace_norm + os.sep) and abs_path != workspace_norm:
        return None, f"Path traversal rejected: {target_file!r} escapes workspace"
    if not os.path.exists(abs_path):
        return None, f"File not found: {target_file!r}"
    if not os.path.isfile(abs_path):
        return None, f"Not a regular file: {target_file!r}"
    return abs_path, None


def _read_target_file(
    workspace: str,
    target_file: str,
    symbol_name: str = "",
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
) -> tuple[Optional[str], Optional[str], Optional[int]]:
    """
    Read target_file relative to workspace, optionally extracting a section.

    When symbol_name or line_start is provided:
      - The file is read in full (size limit bypassed for local extraction)
      - Only the matching block is returned

    When neither is provided:
      - Files exceeding _MAX_FILE_BYTES are rejected to protect API context

    Returns (content, error, context_start_line):
      - (content, None, line)  on success  — line is 1-based, None if full file
      - (None, error, None)    on failure
      - (None, None, None)     when target_file or workspace is empty
    """
    abs_path, err = _resolve_and_check_path(workspace, target_file)
    if err:
        return None, err, None
    if abs_path is None:
        return None, None, None  # context-only mode

    file_size = os.path.getsize(abs_path)
    _log.debug("[review_executor] reading %r  size=%d bytes", target_file, file_size)

    # Size check: only enforced when no targeted extraction is requested
    if file_size > _MAX_FILE_BYTES and not symbol_name and line_start is None:
        _log.info(
            "[review_executor] file too large: %r  size=%d  limit=%d",
            target_file, file_size, _MAX_FILE_BYTES,
        )
        return None, (
            f"File too large to analyse: {target_file!r} "
            f"({file_size:,} bytes; limit is {_MAX_FILE_BYTES:,} bytes). "
            "Split the file or specify a smaller excerpt."
        ), None

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            full_content = fh.read()
    except OSError as exc:
        _log.warning("[review_executor] cannot read %r: %s", target_file, exc)
        return None, f"Cannot read {target_file!r}: {exc}", None

    # Symbol targeting
    if symbol_name:
        from .code_extractor import extract_symbol, detect_lang
        lang = detect_lang(target_file)
        block, start_line, sym_err = extract_symbol(full_content, symbol_name, lang)
        if sym_err:
            _log.warning("[review_executor] symbol %r not found in %r: %s", symbol_name, target_file, sym_err)
            return None, sym_err, None
        _log.info(
            "[review_executor] extracted symbol %r from %r  start_line=%s  chars=%d",
            symbol_name, target_file, start_line, len(block or ""),
        )
        return block, None, start_line

    # Line range targeting
    if line_start is not None:
        from .code_extractor import extract_line_range
        effective_end = line_end if line_end is not None else line_start + 100
        block, rng_err = extract_line_range(full_content, line_start, effective_end)
        if rng_err:
            return None, rng_err, None
        _log.info(
            "[review_executor] extracted lines %d-%d from %r  chars=%d",
            line_start, effective_end, target_file, len(block or ""),
        )
        return block, None, line_start

    # Full file (within size limit)
    _log.info("[review_executor] loaded %r  chars=%d", target_file, len(full_content))
    return full_content, None, None


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _build_user_prompt(
    action: str,
    target_file: str,
    file_content: Optional[str],
    context: str,
    symbol_name: str = "",
    start_line: Optional[int] = None,
    line_end: Optional[int] = None,
) -> str:
    """
    Build the user-turn prompt sent to Claude.

    Structure:
      [Action directive]
      [File path + optional extraction annotation]
      [User question / context]
      [File content block or notice]
    """
    parts: list[str] = []

    if action == "CODE_EXPLAIN":
        parts.append("Please explain the following code clearly and concisely.")
    else:
        parts.append(
            "Please review the following code. Identify any bugs, design issues, "
            "security concerns, and concrete improvements."
        )

    # File annotation with extraction context
    if target_file:
        if symbol_name and start_line:
            parts.append(f"File: `{target_file}` — extracted symbol `{symbol_name}` (starts at line {start_line})")
        elif start_line is not None and line_end is not None:
            parts.append(f"File: `{target_file}` — lines {start_line}-{line_end}")
        elif start_line is not None:
            parts.append(f"File: `{target_file}` — starting at line {start_line}")
        else:
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
        action: str      = inp.get("action", "CODE_REVIEW")
        target_file: str = inp.get("target_file", "")
        workspace: str   = inp.get("workspace", "")
        context: str     = inp.get("context", "")
        # M29: optional targeting params
        symbol_name: str        = inp.get("symbol_name", "")
        line_start: Optional[int] = inp.get("line_start")
        line_end: Optional[int]   = inp.get("line_end")

        # Step 1: read file — supports targeted extraction (symbol / line range)
        file_content, read_error, ctx_start_line = _read_target_file(
            workspace, target_file,
            symbol_name=symbol_name,
            line_start=line_start,
            line_end=line_end,
        )
        if read_error:
            _log.warning("review_executor: read_error: %s", read_error)
            return {"ok": False, "error": read_error}

        # Step 2: build prompt with extraction annotation
        prompt = _build_user_prompt(
            action, target_file, file_content, context,
            symbol_name=symbol_name,
            start_line=ctx_start_line,
            line_end=line_end,
        )

        # Step 3: call Claude
        _log.debug(
            "review_executor: action=%s  file=%r  symbol=%r  start_line=%s  prompt_chars=%d",
            action, target_file, symbol_name or None, ctx_start_line, len(prompt),
        )
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
