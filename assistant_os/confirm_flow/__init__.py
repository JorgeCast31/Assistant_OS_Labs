"""Confirm flow observability — passive read-only surface over context_store.

This subpackage produces non-authoritative summaries of the pending-plan
queue used by the confirmation execution flow. It does NOT execute, mutate,
authorize, or schedule plans. Authority remains with MSO; consumption
remains with the existing per-domain confirmation endpoints.
"""

from .readiness import (
    CompactPendingEntry,
    ConfirmFlowSummary,
    get_confirm_flow_summary,
    list_pending_summary,
)

__all__ = [
    "CompactPendingEntry",
    "ConfirmFlowSummary",
    "get_confirm_flow_summary",
    "list_pending_summary",
]
