"""
Kernel — Execution Context Layer

Provides a minimal context resolution API for domain pipelines.

Pipelines that need to resolve shared runtime state (e.g. a pending plan
stored during a preview step) call get_context(context_id) rather than
importing context_store directly. This keeps the pipeline dependency on
the memory layer thin and testable.

Usage inside a pipeline
-----------------------
    from assistant_os.core.context import get_context, set_context

    ctx = get_context(context_id)
    if ctx:
        plan = ctx["plan"]

The kernel never calls these functions — it only passes context_id to
pipelines. Context resolution is a pipeline-layer concern.

API
---
get_context(context_id) -> dict | None
set_context(context_id, data)          -- low-level write; prefer store_pending_plan for plans
clear_context(context_id)              -- explicit removal
"""

from __future__ import annotations

from typing import Optional

from ..context_store import (
    get_pending_plan,
    store_pending_plan,
    remove_pending_plan,
)


def get_context(context_id: str) -> Optional[dict]:
    """
    Resolve runtime context for the given context_id.

    Returns the stored context dict if found and not expired, or None.
    The returned dict shape matches StoredContext: plan, operation,
    raw_text, created_at, expires_at.
    """
    stored = get_pending_plan(context_id)
    if stored is None:
        return None
    return dict(stored)


def set_context(context_id: str, data: dict) -> None:
    """
    Persist a context entry under context_id.

    Args:
        context_id: Unique identifier for this context.
        data:       Dict with keys: plan, operation, raw_text.
                    TTL and timestamps are managed automatically.
    """
    store_pending_plan(
        context_id=context_id,
        plan=data.get("plan", {}),
        operation=data.get("operation", ""),
        raw_text=data.get("raw_text", ""),
    )


def clear_context(context_id: str) -> bool:
    """
    Remove a context entry.

    Returns True if removed, False if not found.
    """
    return remove_pending_plan(context_id)
