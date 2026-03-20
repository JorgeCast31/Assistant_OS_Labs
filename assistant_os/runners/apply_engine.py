"""
ApplyEngine — Slice 2.

Applies structured changes onto an isolated workspace.

Supported operations:
  file_replace  — write full file content (creates missing directories)
  patch         — not implemented in this slice (logged and skipped)

Change dict format:
    {
        "op": "file_replace" | "patch",
        "path": "relative/path/to/file.py",
        "content": "..."      # required for file_replace
        "patch": "..."        # ignored this slice
    }

All paths are validated to stay within the workspace boundary.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from .errors import ApplyError
from .workspace_manager import _append_log

logger = logging.getLogger(__name__)


class ApplyEngine:
    """Applies a list of changes onto a prepared workspace directory."""

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
            ApplyError: if a change is structurally invalid or violates path policy.
        """
        _append_log(log_file, "apply: start")
        modified: List[str] = []

        for change in changes:
            op = change.get("op")
            relative_path = change.get("path", "")

            if op == "file_replace":
                target = self._resolve_safe(workspace_path, relative_path)
                content = change.get("content", "")
                self._file_replace(target, content, log_file)
                # Use the resolved target to produce a clean, normalised relative
                # path — eliminates any ../ or redundant segments from the input.
                normalized = target.relative_to(workspace_path.resolve()).as_posix()
                modified.append(normalized)

            elif op == "patch":
                _append_log(log_file, f"apply: patch skipped → {relative_path!r} (not implemented)")
                logger.debug("patch skipped for %s", relative_path)

            else:
                msg = f"Unknown op {op!r} for path {relative_path!r}"
                _append_log(log_file, f"apply: error → {msg}")
                raise ApplyError(msg)

        _append_log(log_file, "apply: done")
        return modified

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
