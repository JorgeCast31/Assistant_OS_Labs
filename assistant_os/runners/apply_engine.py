"""
ApplyEngine — M2D hardened.

Applies structured changes onto an isolated workspace.

Supported operations:
  file_replace  — write full file content (creates missing directories)
  patch         — apply a unified diff (file must already exist)

Change dict format:
    file_replace:
        {"op": "file_replace", "path": "relative/path.py", "content": "..."}

    patch:
        {"op": "patch", "path": "relative/path.py", "patch": "<unified diff>"}

All paths are validated to stay within the workspace boundary.

Audit contract:
    apply_changes_with_audit() returns (modified_files, audit_entries).
    Each audit entry:
        {
            "path":         str,   # normalised relative path
            "operation":    str,   # "file_replace" | "patch"
            "before_hash":  str,   # SHA-256 of content before (empty-file hash if new)
            "after_hash":   str,   # SHA-256 of content after
            "diff":         str,   # unified diff between before and after
        }
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .errors import ApplyError
from .workspace_manager import _append_log

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

_DIFF_HEADER_PREFIXES = (
    "--- ", "+++ ", "diff ", "index ", "new file", "deleted file", "Binary",
)


def _compute_hash(content: str) -> str:
    """Return the SHA-256 hex digest of *content* encoded as UTF-8."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _make_diff(before: str, after: str, path: str) -> str:
    """Return a unified diff string between *before* and *after* content."""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _apply_unified_diff(original: str, patch_text: str) -> str:
    """Apply a unified diff patch to *original* content.

    Returns the patched content string.

    Raises:
        ApplyError: if no valid hunks are found, or a hunk position is
                    out of bounds for the current content.

    The patch must use standard unified diff format::

        @@ -start[,count] +start[,count] @@
        [lines prefixed with ' ' (context), '-' (removed), '+' (added), '\\\\' (no-newline)]

    Context lines in the patch are used for count tracking only; the actual
    content of unchanged lines is preserved from the original file.
    """
    result_lines: List[str] = original.splitlines(keepends=True)
    patch_lines = patch_text.splitlines(keepends=True)

    cumulative_offset = 0
    hunks_applied = 0
    pos = 0

    while pos < len(patch_lines):
        m = _HUNK_HEADER.match(patch_lines[pos])
        if not m:
            pos += 1
            continue

        orig_start_1 = int(m.group(1))   # 1-based start in original
        orig_count = int(m.group(2)) if m.group(2) is not None else 1
        pos += 1

        # Collect hunk body until the next @@ header or end of patch,
        # skipping any diff-header lines that appear between hunks.
        hunk_body: List[str] = []
        while pos < len(patch_lines) and not _HUNK_HEADER.match(patch_lines[pos]):
            line = patch_lines[pos]
            if not any(line.startswith(pfx) for pfx in _DIFF_HEADER_PREFIXES):
                hunk_body.append(line)
            pos += 1

        # Parse hunk body.
        # to_remove: number of lines to replace in result_lines (context + removed).
        # to_insert: list of lines to insert instead (context + added).
        # For context lines we preserve the ORIGINAL content to keep line endings intact.
        to_remove = 0
        to_insert: List[str] = []
        ctx_positions: List[int] = []   # indices in to_insert that are context (use original)

        for line in hunk_body:
            if not line:
                # Bare newline in patch body — treat as context.
                to_remove += 1
                ctx_positions.append(len(to_insert))
                to_insert.append("\n")
                continue
            marker = line[0]
            content = line[1:]   # everything after the marker, including line ending

            if marker == " ":    # context: keep from original
                to_remove += 1
                ctx_positions.append(len(to_insert))
                to_insert.append(content)   # placeholder; replaced below with original
            elif marker == "-":  # removed: consume from original, don't add to new
                to_remove += 1
            elif marker == "+":  # added: insert in new
                to_insert.append(content)
            elif marker == "\\":  # "\ No newline at end of file"
                if to_insert:
                    to_insert[-1] = to_insert[-1].rstrip("\n")
            # Unknown markers silently ignored (defensive).

        # Compute actual start position in the current (already-modified) result_lines.
        # When orig_count == 0 it is a pure insertion: the position is AFTER line orig_start_1.
        if orig_count == 0:
            actual_start = orig_start_1 + cumulative_offset
        else:
            actual_start = orig_start_1 - 1 + cumulative_offset

        # Bounds check.
        if actual_start < 0 or actual_start + to_remove > len(result_lines):
            raise ApplyError(
                f"Patch hunk at original line {orig_start_1} cannot be applied: "
                f"expected {to_remove} lines at position {actual_start}, "
                f"but the file has {len(result_lines)} lines."
            )

        # Replace context placeholders with the actual original lines.
        ctx_offset = 0  # how many removed lines we've passed (to align ctx_positions)
        orig_slice = result_lines[actual_start : actual_start + to_remove]
        orig_ctx_idx = 0   # index into context lines within the original slice

        for i, line in enumerate(hunk_body):
            if not line or line[0] == " ":
                # This is a context line.  Find its position in to_insert and patch.
                # Context lines come in order: the k-th context line in hunk_body
                # corresponds to the k-th element in orig_slice that is context.
                # Since removed lines consume from orig_slice too, we track a combined
                # index across both context and removed.
                pass  # handled by building ctx_actual below

        # Simpler: walk the hunk body once more to fill context from original.
        orig_i = 0        # index into orig_slice (advances for '-' and ' ')
        final_insert: List[str] = []
        add_i = 0         # index into to_insert (advances for ' ' and '+')

        for line in hunk_body:
            if not line:
                final_insert.append(orig_slice[orig_i] if orig_i < len(orig_slice) else "\n")
                orig_i += 1
                add_i += 1
                continue
            marker = line[0]
            if marker == " ":
                # Use original content for context (preserves line endings).
                final_insert.append(orig_slice[orig_i] if orig_i < len(orig_slice) else line[1:])
                orig_i += 1
                add_i += 1
            elif marker == "-":
                orig_i += 1  # consume from original, skip in output
            elif marker == "+":
                final_insert.append(line[1:])
                add_i += 1
            elif marker == "\\":
                if final_insert:
                    final_insert[-1] = final_insert[-1].rstrip("\n")
            # else: ignore

        # Apply the hunk.
        result_lines[actual_start : actual_start + to_remove] = final_insert
        cumulative_offset += len(final_insert) - to_remove
        hunks_applied += 1

    if hunks_applied == 0:
        raise ApplyError(
            "Patch contains no valid hunks — no '@@ -N,N +N,N @@' headers found. "
            "Supply a unified diff (output of 'diff -u' or 'git diff')."
        )

    return "".join(result_lines)


# ---------------------------------------------------------------------------
# ApplyEngine
# ---------------------------------------------------------------------------


class ApplyEngine:
    """Applies a list of changes onto a prepared workspace directory."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_changes(
        self,
        workspace_path: Path,
        changes: List[Dict[str, Any]],
        log_file: Path,
    ) -> List[str]:
        """Apply *changes* in order onto *workspace_path*.

        Returns:
            List of relative file paths that were modified.

        Raises:
            ApplyError: if a change is invalid or violates path policy.

        Backward-compatible wrapper around apply_changes_with_audit().
        """
        modified, _ = self.apply_changes_with_audit(workspace_path, changes, log_file)
        return modified

    def apply_changes_with_audit(
        self,
        workspace_path: Path,
        changes: List[Dict[str, Any]],
        log_file: Path,
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Apply *changes* and return (modified_files, audit_entries).

        Each audit entry contains:
            path, operation, before_hash, after_hash, diff

        Raises:
            ApplyError: if a change is structurally invalid, a file is missing
                        for a patch op, or a path violates the workspace boundary.
        """
        _append_log(log_file, "apply: start")
        modified: List[str] = []
        audit_entries: List[Dict[str, Any]] = []

        for change in changes:
            op = change.get("op")
            relative_path = change.get("path", "")

            if op == "file_replace":
                content = change.get("content")
                if content is None:
                    msg = f"file_replace for {relative_path!r}: 'content' is required (use empty string for an empty file)"
                    _append_log(log_file, f"apply: error → {msg}")
                    raise ApplyError(msg)

                target = self._resolve_safe(workspace_path, relative_path)

                before_content = target.read_text(encoding="utf-8") if target.exists() else ""
                before_hash = _compute_hash(before_content)

                self._file_replace(target, content, log_file)
                normalized = target.relative_to(workspace_path.resolve()).as_posix()
                modified.append(normalized)

                after_hash = _compute_hash(content)
                audit_entries.append({
                    "path": normalized,
                    "operation": "file_replace",
                    "before_hash": before_hash,
                    "after_hash": after_hash,
                    "diff": _make_diff(before_content, content, normalized),
                })

            elif op == "patch":
                patch_text = change.get("patch", "")
                if not patch_text or not patch_text.strip():
                    msg = (
                        f"patch op for {relative_path!r}: 'patch' field is empty. "
                        "Provide a non-empty unified diff."
                    )
                    _append_log(log_file, f"apply: error → {msg}")
                    raise ApplyError(msg)

                target = self._resolve_safe(workspace_path, relative_path)

                if not target.exists():
                    msg = (
                        f"patch op for {relative_path!r}: file does not exist. "
                        "Use 'file_replace' to create new files."
                    )
                    _append_log(log_file, f"apply: error → {msg}")
                    raise ApplyError(msg)

                before_content = target.read_text(encoding="utf-8")
                before_hash = _compute_hash(before_content)

                after_content = self._patch_file(target, patch_text, log_file)
                normalized = target.relative_to(workspace_path.resolve()).as_posix()
                modified.append(normalized)

                after_hash = _compute_hash(after_content)
                audit_entries.append({
                    "path": normalized,
                    "operation": "patch",
                    "before_hash": before_hash,
                    "after_hash": after_hash,
                    "diff": _make_diff(before_content, after_content, normalized),
                })

            else:
                msg = f"Unknown op {op!r} for path {relative_path!r}"
                _append_log(log_file, f"apply: error → {msg}")
                raise ApplyError(msg)

        _append_log(log_file, "apply: done")
        return modified, audit_entries

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_safe(self, workspace_path: Path, relative_path: str) -> Path:
        """Resolve *relative_path* inside *workspace_path*, blocking traversal.

        Raises:
            ApplyError: if the resolved path escapes the workspace.
        """
        if not relative_path or not relative_path.strip():
            raise ApplyError("change 'path' must not be empty.")

        workspace_resolved = workspace_path.resolve()
        target = (workspace_resolved / relative_path).resolve()

        try:
            target.relative_to(workspace_resolved)
        except ValueError:
            raise ApplyError(
                f"Path traversal detected: {relative_path!r} escapes workspace."
            )

        return target

    def _file_replace(self, target: Path, content: str, log_file: Path) -> None:
        """Write *content* to *target*, creating parent directories as needed."""
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            _append_log(log_file, f"apply: file_replace → {target.name!r}")
            logger.info("file_replace: wrote %s (%d bytes)", target, len(content))
        except OSError as exc:
            msg = f"file_replace failed for {target}: {exc}"
            _append_log(log_file, f"apply: error → {msg}")
            raise ApplyError(msg) from exc

    def _patch_file(self, target: Path, patch_text: str, log_file: Path) -> str:
        """Apply *patch_text* (unified diff) to *target*.

        Returns the patched file content string.

        Raises:
            ApplyError: if the patch is malformed or cannot be applied.
        """
        original = target.read_text(encoding="utf-8")
        try:
            patched = _apply_unified_diff(original, patch_text)
        except ApplyError:
            raise
        except Exception as exc:
            msg = f"patch failed for {target.name!r}: {exc}"
            _append_log(log_file, f"apply: error → {msg}")
            raise ApplyError(msg) from exc

        try:
            target.write_text(patched, encoding="utf-8")
            _append_log(log_file, f"apply: patch → {target.name!r}")
            logger.info("patch: applied to %s (%d → %d bytes)", target, len(original), len(patched))
        except OSError as exc:
            msg = f"patch write failed for {target}: {exc}"
            _append_log(log_file, f"apply: error → {msg}")
            raise ApplyError(msg) from exc

        return patched
