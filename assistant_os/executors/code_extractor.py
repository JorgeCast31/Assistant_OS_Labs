"""
Lightweight code extraction utilities for large-file targeting in the CODE domain.

All functions are pure (no I/O, no side effects).  The caller is responsible
for reading file content and performing any security checks.

Public API
----------
detect_lang(filename)                              -> "python" | "typescript" | ...
extract_symbol(content, symbol_name, lang)         -> (block, start_line_1based, error)
extract_line_range(content, start, end)            -> (block, error)
extract_index(content, lang)                       -> list[{"kind", "name", "line"}]
"""
from __future__ import annotations

import os
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_LANG_MAP: dict[str, str] = {
    ".py":   "python",
    ".ts":   "typescript",
    ".tsx":  "typescript",
    ".js":   "javascript",
    ".jsx":  "javascript",
    ".mjs":  "javascript",
    ".go":   "go",
    ".rs":   "rust",
}


def detect_lang(filename: str) -> str:
    """Return a canonical language tag for filename's extension."""
    ext = os.path.splitext(filename)[1].lower()
    return _LANG_MAP.get(ext, "unknown")


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------

def extract_symbol(
    content: str,
    symbol_name: str,
    lang: str,
    max_lines: int = 350,
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Locate a named function/class/const in content and return its code block.

    Returns (block, start_line_1based, None) on success
            (None, None, error_message)       on failure
    """
    lines = content.splitlines()
    if lang == "python":
        return _extract_python_symbol(lines, symbol_name, max_lines)
    elif lang in ("typescript", "javascript"):
        return _extract_ts_symbol(lines, symbol_name, max_lines)
    else:
        return _extract_generic_symbol(lines, symbol_name, max_lines)


def _extract_python_symbol(
    lines: list[str],
    symbol_name: str,
    max_lines: int,
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Find def/class for symbol_name in Python source."""
    start_patterns = (
        f"def {symbol_name}(",
        f"async def {symbol_name}(",
        f"class {symbol_name}(",
        f"class {symbol_name}:",
    )
    start_idx: Optional[int] = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if any(stripped.startswith(p) for p in start_patterns):
            start_idx = i
            break

    if start_idx is None:
        return None, None, f"Symbol '{symbol_name}' not found in file"

    # Walk back up to 10 lines to capture decorators (@register..., @property, etc.)
    decorator_start = start_idx
    for j in range(start_idx - 1, max(start_idx - 10, -1), -1):
        stripped = lines[j].lstrip()
        if stripped.startswith("@"):
            decorator_start = j
        elif stripped:  # non-empty, non-decorator line → stop scanning
            break

    # Base indentation is the def/class line (not the decorator)
    base_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())

    # Find the end of the function/class HEADER: the line ending with ":" at
    # balanced bracket depth.  This correctly handles multi-line signatures:
    #
    #   def foo(          ← start_idx
    #       x: int,       ← still header (depth > 0)
    #   ) -> "SomeType":  ← header ends here (depth → 0, line ends with ":")
    #       body...
    #
    # Without this, a closing ")" at indent 0 would prematurely stop the scan.
    depth = 0
    header_end_idx = start_idx
    for i in range(start_idx, min(len(lines), start_idx + 30)):
        for ch in lines[i]:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
        if depth <= 0 and lines[i].rstrip().endswith(":"):
            header_end_idx = i
            break

    # Scan body from the first line after the header's closing ":"
    end_idx = header_end_idx + 1
    while end_idx < len(lines) and (end_idx - start_idx) < max_lines:
        line = lines[end_idx]
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            curr_indent = len(line) - len(line.lstrip())
            if curr_indent <= base_indent:
                break
        end_idx += 1

    block = "\n".join(lines[decorator_start:end_idx])
    return block, decorator_start + 1, None  # 1-based line number


def _extract_ts_symbol(
    lines: list[str],
    symbol_name: str,
    max_lines: int,
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Find function/class/const for symbol_name in TypeScript/JavaScript."""
    # Method-like pattern (inside a class body)
    _method_re = re.compile(
        rf'^\s*(?:async\s+)?(?:static\s+)?(?:public\s+|private\s+|protected\s+)?'
        rf'(?:override\s+)?{re.escape(symbol_name)}\s*[(<]'
    )
    # Top-level candidates (stripped line prefixes)
    _prefixes = (
        f"function {symbol_name}(",
        f"function {symbol_name} (",
        f"async function {symbol_name}(",
        f"class {symbol_name} ",
        f"class {symbol_name}{{",
        f"class {symbol_name}:",
        f"const {symbol_name} =",
        f"const {symbol_name}=",
        f"let {symbol_name} =",
        f"export function {symbol_name}",
        f"export async function {symbol_name}",
        f"export const {symbol_name}",
        f"export class {symbol_name}",
        f"export default function {symbol_name}",
        f"export default class {symbol_name}",
    )

    start_idx: Optional[int] = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if any(stripped.startswith(p) for p in _prefixes) or _method_re.match(line):
            start_idx = i
            break

    if start_idx is None:
        return None, None, f"Symbol '{symbol_name}' not found in file"

    # Brace counting to find end of block
    depth = 0
    in_block = False
    end_idx = min(len(lines), start_idx + max_lines)
    for i in range(start_idx, end_idx):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                in_block = True
            elif ch == "}":
                depth -= 1
        if in_block and depth == 0:
            end_idx = i + 1
            break

    block = "\n".join(lines[start_idx:end_idx])
    return block, start_idx + 1, None


def _extract_generic_symbol(
    lines: list[str],
    symbol_name: str,
    max_lines: int,
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Fallback: find first occurrence of symbol_name, capture next N lines."""
    for i, line in enumerate(lines):
        if symbol_name in line and not line.lstrip().startswith(("//", "#", "*")):
            limit = min(len(lines), i + max_lines // 3)
            return "\n".join(lines[i:limit]), i + 1, None
    return None, None, f"Symbol '{symbol_name}' not found in file"


# ---------------------------------------------------------------------------
# Line range extraction
# ---------------------------------------------------------------------------

def extract_line_range(
    content: str,
    start: int,
    end: int,
) -> tuple[Optional[str], Optional[str]]:
    """
    Extract lines [start..end] (1-based, inclusive) from content.

    Returns (block, None) on success, (None, error_str) on failure.
    """
    lines = content.splitlines()
    n = len(lines)

    if start < 1 or start > n:
        return None, f"Start line {start} out of range (file has {n} lines)"
    actual_end = min(max(end, start), n)

    block = "\n".join(lines[start - 1 : actual_end])
    if not block.strip():
        return None, f"Lines {start}-{actual_end} contain only whitespace"
    return block, None


# ---------------------------------------------------------------------------
# Index extraction
# ---------------------------------------------------------------------------

def extract_index(content: str, lang: str) -> list[dict]:
    """
    Return a list of top-level symbols in content.

    Each entry: {"kind": str, "name": str, "line": int}
    kind values: "function", "method", "class", "const/arrow"
    """
    if lang == "python":
        return _index_python(content)
    elif lang in ("typescript", "javascript"):
        return _index_ts(content)
    else:
        return _index_generic(content)


def _index_python(content: str) -> list[dict]:
    symbols: list[dict] = []
    for i, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("def ") or stripped.startswith("async def "):
            name_part = re.split(r"\bdef\s+", stripped, maxsplit=1)[-1]
            name = name_part.split("(")[0].strip()
            kind = "method" if indent > 0 else "function"
            symbols.append({"kind": kind, "name": name, "line": i})
        elif stripped.startswith("class "):
            name = stripped[6:].split("(")[0].split(":")[0].strip()
            symbols.append({"kind": "class", "name": name, "line": i})
    return symbols


_TS_FUNC_RE  = re.compile(r'^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)')
_TS_CLASS_RE = re.compile(r'^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)')
_TS_CONST_RE = re.compile(
    r'^(?:export\s+)?(?:const|let)\s+(\w+)\s*(?::\s*\S+\s*)?=\s*(?:async\s+)?(?:\(|function\b)'
)


def _index_ts(content: str) -> list[dict]:
    symbols: list[dict] = []
    for i, raw_line in enumerate(content.splitlines(), 1):
        line = raw_line.strip()
        if m := _TS_FUNC_RE.match(line):
            symbols.append({"kind": "function", "name": m.group(1), "line": i})
        elif m := _TS_CLASS_RE.match(line):
            symbols.append({"kind": "class", "name": m.group(1), "line": i})
        elif m := _TS_CONST_RE.match(line):
            symbols.append({"kind": "const/arrow", "name": m.group(1), "line": i})
    return symbols


def _index_generic(content: str) -> list[dict]:
    symbols: list[dict] = []
    for i, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "*", "/*")):
            continue
        if len(line) - len(line.lstrip()) == 0:  # top-level only
            m = re.match(r'^(\w{4,})', stripped)
            if m:
                symbols.append({"kind": "symbol", "name": m.group(1), "line": i})
    return symbols[:50]
