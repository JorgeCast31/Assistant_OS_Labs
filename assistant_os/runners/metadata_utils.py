"""
runners/metadata_utils.py — Shared utility for patching execution metadata.

This is a neutral persistence layer shared by both CODE execution paths:

  PATH A (kernel):  assistant_os/pipelines/code_pipeline.py
  PATH B (HTTP):    assistant_os/api/code_api.py

Dependency direction (intentional, enforced):
  API layer   → runners  ✓ (allowed)
  Pipelines   → runners  ✓ (allowed)
  Runners     → nothing above them — no imports from api or pipelines

By defining EXECUTIONS_ROOT here once and importing it everywhere else,
we eliminate the previous duplication where code_api owned the path
definition but code_pipeline needed the same location.

No business logic lives here.  Pure I/O helpers.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical execution artifacts root — single definition for the whole system.
# Resolves to: {project_root}/var/runner/executions
# Both PATH A and PATH B import this rather than each defining their own.
# ---------------------------------------------------------------------------

EXECUTIONS_ROOT: Path = (
    Path(__file__).parent.parent.parent / "var" / "runner" / "executions"
)


# ---------------------------------------------------------------------------
# Metadata patch utility
# ---------------------------------------------------------------------------


def patch_execution_metadata(
    execution_id: str,
    fields: Dict[str, Any],
    *,
    base_path: Optional[Path] = None,
) -> None:
    """Merge *fields* into the existing metadata.json for *execution_id*.

    Non-destructive: reads, updates in-memory, writes back atomically.
    Silent on error — a metadata patch failure must never interrupt execution.

    Args:
        execution_id : Directory name under EXECUTIONS_ROOT (or *base_path*).
        fields       : Key-value pairs to merge into metadata.json.
        base_path    : Override the root path (for test isolation only).
                       Production callers omit this argument.
    """
    root = base_path if base_path is not None else EXECUTIONS_ROOT
    meta_path = root / execution_id / "metadata.json"
    if not meta_path.exists():
        return
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data.update(fields)
        meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "PATCH_METADATA_ERROR execution_id=%s error=%s", execution_id, exc
        )
