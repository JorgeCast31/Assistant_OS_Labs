"""
Real preview executor for CODE_FIX and CODE_CREATE.

Asks Claude to analyse a change request and return a structured proposal dict
compatible with the ProposeChangeTool executor contract.

This executor is PREVIEW-ONLY — it produces zero side effects:
  - no file writes
  - no git changes
  - no patch application

Compatible with:
  - ProposeChangeTool(executor=build_claude_propose_executor())
  - register_propose_executor() in code_pipeline

Architecture position
---------------------
Concrete executor implementation that bridges ProposeChangeTool's executor
contract to the Anthropic API.  Wired at startup via register_propose_executor().
apply_change_tool remains stubbed and is NOT affected by this module.

File context
------------
For CODE_FIX:  reads the target file if present (needed for correct diffs).
               Missing file is an error — you cannot fix something that doesn't exist.
For CODE_CREATE: file may not exist yet; context-only mode is used.
Files larger than _MAX_FILE_BYTES are read partially (first N bytes + truncation
notice) rather than rejected, so large-file proposals can still be generated.

Contract analysis (M30)
-----------------------
Before proposing any change Claude is instructed to infer:
  - The current return type / contract of the target function/method/class.
  - Which call sites in the file consume that return value and how.
  - Whether the proposed change preserves backward compatibility.

Three new output fields encode the result:
  contract_assumptions  : str   — what Claude observed about the current API contract
  caller_risk           : str   — "safe" | "review_required" | "breaking"
  caller_risk_notes     : str   — which callers are affected and why

Automatic risk escalation:
  caller_risk == "breaking"        → risk_level forced to "high"
  caller_risk == "review_required" → risk_level raised to at least "medium"

Response parsing
----------------
Claude is instructed to return ONLY a JSON object.  The parser strips markdown
code fences, then extracts the first {...} block as a fallback.  Non-JSON
responses produce ok=False with the raw text excerpt.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Optional

# File size cap for context inclusion.  Larger files are partially read rather
# than rejected, so the proposal can reference the beginning of the file.
_MAX_FILE_BYTES: int = 65_536  # 64 KB

_SYSTEM_PROMPT = """\
Eres un asistente de planificación de cambios de código integrado en una herramienta
de desarrollo. Tu responsabilidad principal es proponer cambios SEGUROS — es decir,
que respeten los contratos existentes del código y no rompan silenciosamente a los callers.

Idioma: los campos de texto libre del JSON (summary, write_intent_summary,
contract_assumptions, caller_risk_notes) deben escribirse en español.
Los nombres de archivos, funciones, variables, rutas y el contenido del diff van
siempre en su forma original sin traducir.

CONTRACT ANALYSIS (required before every proposal):
Whenever file content is provided, you MUST examine it and:
1. Identify the target symbol (function / method / class) being changed.
2. Determine its CURRENT contract:
   - What does it return? (exact type and shape — e.g. None on success,
     (int, dict) tuple on error, bool, list, etc.)
   - What exceptions does it raise?
   - What invariants does it maintain?
3. Find EVERY call site for that symbol inside the provided file content.
   Note exactly how each caller consumes the return value:
   e.g. `if result:`, `status, body = result`, `result.get("key")`, etc.
4. Decide caller_risk:
   - "safe"            — your proposed change is fully backward-compatible with
                         all identified callers.
   - "review_required" — change is likely compatible but callers should be
                         inspected before applying (e.g. new optional param,
                         semantic shift without type change).
   - "breaking"        — your change would cause one or more existing callers
                         to fail, raise an exception, or produce wrong results.

Respond with ONLY a JSON object — no other text.

Required JSON schema:
{
  "summary": "One-sentence description of the change",
  "affected_files": ["relative/path/to/file.py"],
  "write_intent_summary": "Short description: e.g. 'Modifies auth.py to fix token validation'",
  "patch_preview": "Unified diff showing key changes (- old lines, + new lines)",
  "operation_types": ["modify"],
  "risk_level": "low",
  "contract_assumptions": "What you observed about the current contract (return type, usage pattern)",
  "caller_risk": "safe",
  "caller_risk_notes": "Which callers are affected and how, or 'No callers found in file' if none"
}

Rules:
- affected_files: relative paths only, at most 5 files
- operation_types: use "modify" for existing files, "create" for new files
  NEVER include "delete", "rename", or "move"
- risk_level: "low" | "medium" | "high"
  MANDATORY ESCALATION — you MUST follow these rules:
  * If caller_risk == "breaking"        → risk_level MUST be "high"
  * If caller_risk == "review_required" → risk_level MUST be at least "medium"
- contract_assumptions: ALWAYS fill in — even if "No file provided" or "New file, no prior contract"
- caller_risk: ALWAYS one of "safe" | "review_required" | "breaking"
- caller_risk_notes: be specific — name which callers are affected; if safe, explain why
- patch_preview: unified diff format (--- a/file / +++ b/file / @@ ... @@ / - / +)
- If the change cannot be safely proposed: {"error": "reason — do not include other fields"}
- Respond with ONLY the JSON object, no markdown, no explanation, no code fences
"""


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def _read_file_for_context(
    workspace: str,
    target_file: str,
    action: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Read the target file for proposal context.

    Returns (content, error_message).  Exactly one will be None on definitive
    outcomes:
      (content, None)   — file read successfully
      (None, None)      — no file to read (empty args or CODE_CREATE + missing file)
      (None, error_str) — read failed with a hard error

    For CODE_CREATE: a missing target file is expected (we're creating it).
    For CODE_FIX:    a missing target file is an error.
    Files > _MAX_FILE_BYTES are partially read with a truncation notice appended.
    """
    if not target_file or not workspace:
        return None, None

    abs_path = os.path.normpath(os.path.join(workspace, target_file))
    workspace_norm = os.path.normpath(workspace)

    # Traversal guard — reject paths that escape the workspace root
    if not abs_path.startswith(workspace_norm + os.sep) and abs_path != workspace_norm:
        return None, f"Path traversal rejected: {target_file!r} escapes workspace"

    if not os.path.exists(abs_path):
        if action == "CODE_CREATE":
            return None, None  # Expected — we are creating this file
        return None, f"File not found: {target_file!r} (required for CODE_FIX)"

    if not os.path.isfile(abs_path):
        return None, f"Not a regular file: {target_file!r}"

    try:
        file_size = os.path.getsize(abs_path)
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            if file_size > _MAX_FILE_BYTES:
                content = fh.read(_MAX_FILE_BYTES)
                return (
                    content
                    + f"\n... (file truncated at {_MAX_FILE_BYTES:,} bytes for context)",
                    None,
                )
            return fh.read(), None
    except OSError as exc:
        return None, f"Cannot read {target_file!r}: {exc}"


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _build_propose_prompt(
    action: str,
    target_file: str,
    file_content: Optional[str],
    context: str,
    allowed_write_scope: list,
) -> str:
    """
    Build the user-turn prompt for proposal generation.

    M30: When file content is available for CODE_FIX, prepends an explicit
    contract analysis directive so Claude scans callers before proposing
    changes that could silently break them.
    """
    parts: list[str] = []

    if action == "CODE_FIX":
        if file_content is not None:
            parts.append(
                "Generate a fix proposal for the following change request.\n\n"
                "REQUIRED — perform contract analysis FIRST:\n"
                "1. Identify the function/method/class the change will modify.\n"
                "2. Determine its current return type and contract "
                "(e.g. None on success, tuple on error, bool, etc.).\n"
                "3. Scan the file for every call site of that symbol and note how "
                "callers consume the return value.\n"
                "4. Set caller_risk to 'breaking' if your patch would cause any "
                "caller to fail, 'review_required' if callers need inspection, "
                "or 'safe' if fully backward-compatible.\n"
                "Then produce the JSON proposal."
            )
        else:
            parts.append(
                "Generate a fix proposal for the following code change request.\n"
                "(No file content available — set contract_assumptions to "
                "'File not provided' and caller_risk to 'review_required'.)"
            )
    else:
        # CODE_CREATE — new file, no existing callers to check
        parts.append(
            "Generate a creation proposal for the following new code request.\n"
            "Since this is new code, set contract_assumptions to describe the "
            "intended contract for the new symbol, and set caller_risk to 'safe'."
        )

    if target_file:
        parts.append(f"Target file: `{target_file}`")

    if allowed_write_scope and allowed_write_scope != ([target_file] if target_file else []):
        parts.append(f"Allowed write scope: {', '.join(str(p) for p in allowed_write_scope)}")

    if context and context.strip():
        parts.append(f"Change request: {context.strip()}")

    if file_content is not None:
        ext = os.path.splitext(target_file)[1].lstrip(".") if target_file else ""
        parts.append(f"Current file content:\n```{ext}\n{file_content}\n```")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# JSON parsing + validation
# ---------------------------------------------------------------------------

def _parse_proposal_json(text: str) -> Optional[dict]:
    """
    Extract a JSON object from Claude's response text.

    Handles:
    - plain JSON
    - JSON wrapped in ```json ... ``` fences
    - JSON preceded/followed by stray text (extracts first {...} block)

    Returns parsed dict or None if no valid JSON can be found.
    """
    text = text.strip()

    # Strip code fences
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            break

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract first {...} block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


_VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})
_CANONICAL_OPS = frozenset({"create", "modify", "delete", "rename", "move"})
_BLOCKED_OPS = frozenset({"delete", "rename", "move"})
_VALID_CALLER_RISKS = frozenset({"safe", "review_required", "breaking"})


def _validate_and_normalise(raw: dict, target_file: str, action: str) -> dict:
    """
    Validate and normalise the raw JSON from Claude into the executor output contract.

    - Fills in safe defaults for missing / empty fields.
    - Removes blocked operation types (delete/rename/move).
    - Normalises risk_level to a known value.
    - Surfaces Claude's own error field as ok=False.
    - M30: extracts contract_assumptions / caller_risk / caller_risk_notes and
      applies automatic risk escalation:
        caller_risk == "breaking"        → risk_level forced to "high"
        caller_risk == "review_required" → risk_level raised to at least "medium"
    """
    if raw.get("error"):
        return {"ok": False, "error": str(raw["error"])}

    # operation_types — normalise to canonical set, then strip blocked ops
    op_types = [str(op).lower() for op in raw.get("operation_types", [])]
    op_types = [op for op in op_types if op in _CANONICAL_OPS]   # drop unknown values
    op_types = [op for op in op_types if op not in _BLOCKED_OPS]  # drop blocked ops
    if not op_types:
        op_types = ["create" if action == "CODE_CREATE" else "modify"]

    # risk_level — start from Claude's suggestion
    risk = str(raw.get("risk_level", "medium")).lower()
    if risk not in _VALID_RISK_LEVELS:
        risk = "medium"

    # M30: caller_risk — normalise and apply escalation
    caller_risk = str(raw.get("caller_risk", "")).lower().strip()
    if caller_risk not in _VALID_CALLER_RISKS:
        # If the field is absent or unrecognised, default conservatively
        caller_risk = "review_required" if action == "CODE_FIX" else "safe"

    caller_risk_notes = str(raw.get("caller_risk_notes", "")).strip()
    contract_assumptions = str(raw.get("contract_assumptions", "")).strip()

    # Automatic risk escalation based on caller compatibility
    if caller_risk == "breaking":
        risk = "high"
    elif caller_risk == "review_required" and risk == "low":
        risk = "medium"

    # affected_files — default to target_file if missing
    affected = [str(f) for f in raw.get("affected_files", []) if f]
    if not affected and target_file:
        affected = [target_file]

    return {
        "ok": True,
        "summary": str(raw.get("summary", f"{action} proposal")).strip(),
        "affected_files": affected,
        "write_intent_summary": str(raw.get("write_intent_summary", "")).strip(),
        "patch_preview": str(raw.get("patch_preview", "(preview not available)")).strip(),
        "operation_types": op_types,
        "risk_level": risk,
        # M30: contract analysis fields
        "contract_assumptions": contract_assumptions,
        "caller_risk": caller_risk,
        "caller_risk_notes": caller_risk_notes,
    }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_claude_propose_executor(
    client=None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> Callable[[dict], dict]:
    """
    Return a real executor callable for CODE_FIX / CODE_CREATE preview generation.

    The returned callable is compatible with:
      - ProposeChangeTool(executor=...)
      - register_propose_executor() in code_pipeline

    This is PREVIEW-ONLY — no file writes, no git operations.

    Parameters
    ----------
    client : anthropic.Anthropic | None
        Anthropic client.  If None, built from ANTHROPIC_API_KEY in config.
    model : str | None
        Claude model ID.  Defaults to CODE_PROPOSE_MODEL from config.
    max_tokens : int | None
        Token budget.  Defaults to CODE_PROPOSE_MAX_TOKENS from config.

    Executor input contract
    -----------------------
        action              : "CODE_FIX" | "CODE_CREATE"
        target_file         : str — relative path within workspace (may be "")
        workspace           : str — absolute workspace root (may be "")
        context             : str — raw user text / change request
        allowed_write_scope : list[str] — allowed relative paths

    Executor output contract (on success)
    --------------------------------------
        ok                   : True
        summary              : str
        affected_files       : list[str]
        write_intent_summary : str
        patch_preview        : str
        operation_types      : list[str]  — only "modify" | "create"
        risk_level           : str        — "low" | "medium" | "high"

    Executor output contract (on failure)
    --------------------------------------
        ok    : False
        error : str
    """
    import anthropic as _anthropic
    from ..config import CODE_PROPOSE_MODEL, CODE_PROPOSE_MAX_TOKENS, ANTHROPIC_API_KEY

    _model = model or CODE_PROPOSE_MODEL
    _max_tokens = max_tokens or CODE_PROPOSE_MAX_TOKENS

    if client is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to your .env file before calling build_claude_propose_executor()."
            )
        client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def executor(inp: dict) -> dict:
        action: str = inp.get("action", "CODE_FIX")
        target_file: str = inp.get("target_file", "")
        workspace: str = inp.get("workspace", "")
        context: str = inp.get("context", "")
        allowed_scope: list = inp.get("allowed_write_scope") or (
            [target_file] if target_file else []
        )

        # Read file for context
        file_content, read_error = _read_file_for_context(workspace, target_file, action)
        if read_error:
            return {"ok": False, "error": read_error}

        # Build prompt
        prompt = _build_propose_prompt(
            action, target_file, file_content, context, allowed_scope
        )

        # Call Claude — 45 s hard timeout to avoid indefinite hangs
        _CALL_TIMEOUT = 45.0
        import time as _time
        _cp_start = _time.perf_counter()
        try:
            response = client.messages.create(
                model=_model,
                max_tokens=_max_tokens,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                timeout=_CALL_TIMEOUT,
            )
            _cp_latency_ms = int((_time.perf_counter() - _cp_start) * 1000)
            raw_text: str = response.content[0].text
            try:
                _usage = getattr(response, "usage", None)
                _tokens_in = getattr(_usage, "input_tokens", None) if _usage else None
                _tokens_out = getattr(_usage, "output_tokens", None) if _usage else None
                from ..mso.cognitive_usage_ledger import record_provider_call
                record_provider_call(
                    trace_id=inp.get("context_id") or inp.get("plan_id") or "",
                    source_component="code_propose_executor",
                    surface="code_executor",
                    domain="CODE",
                    action=action,
                    provider_used="anthropic",
                    model_used=_model,
                    tokens_in=_tokens_in,
                    tokens_out=_tokens_out,
                    latency_ms=_cp_latency_ms,
                    response_source="llm_code_propose",
                )
            except Exception:
                pass
        except _anthropic.AuthenticationError as exc:
            return {"ok": False, "error": f"API authentication failed: {exc}"}
        except _anthropic.RateLimitError as exc:
            return {"ok": False, "error": f"API rate limit exceeded: {exc}"}
        except _anthropic.APIStatusError as exc:
            return {"ok": False, "error": f"Claude API error {exc.status_code}: {exc.message}"}
        except _anthropic.APITimeoutError as exc:
            return {"ok": False, "error": f"Claude API timeout after {_CALL_TIMEOUT:.0f}s: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"Unexpected error calling Claude: {exc}"}

        # Parse JSON response
        parsed = _parse_proposal_json(raw_text)
        if parsed is None:
            return {
                "ok": False,
                "error": f"Claude returned non-JSON response: {raw_text[:200]!r}",
            }

        return _validate_and_normalise(parsed, target_file, action)

    return executor
