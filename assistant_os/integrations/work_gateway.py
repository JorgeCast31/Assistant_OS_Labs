"""
Work Integration Gateway
========================
Non-HTTP aggregation point for work domain pipeline dependencies.

This module is the single import target for ``work_pipeline`` when it needs
Notion access, context persistence, or work-specific formatting.  It carries
zero HTTP logic — it is a pure re-export hub for the pipeline layer.

All symbols are sourced from their authoritative owners:

  * ``check_notion_available``, ``get_notion_status``, ``query_work_db``,
    ``format_work_query_response``, ``get_work_item_by_id``,
    ``get_editable_field_options``, ``search_work_items_by_title``,
    ``search_work_items_with_filters``
        → ``integrations.notion``  (Notion integration layer)

  * ``store_pending_plan``
        → ``context_store``  (context persistence)

  * ``generate_update_preview``
        → ``parsers.work_update_parser``  (update formatting)

Added in M0.8: breaks the ``work_pipeline → webhook_server`` coupling that
existed since the initial implementation.  Prior to M0.8 the pipeline imported
all these symbols from ``webhook_server`` — an HTTP-layer module — so that
test patches applied to ``assistant_os.webhook_server.*`` would fire.  The
gateway takes over that role: test patches should target
``assistant_os.integrations.work_gateway.*`` for the pipeline execution path.
"""
from __future__ import annotations

from .notion import (
    check_notion_available,
    get_notion_status,
    query_work_db,
    format_work_query_response,
    get_work_item_by_id,
    get_editable_field_options,
    search_work_items_by_title,
    search_work_items_with_filters,
)
from ..context_store import store_pending_plan
from ..parsers.work_update_parser import generate_update_preview

__all__ = [
    "check_notion_available",
    "get_notion_status",
    "query_work_db",
    "format_work_query_response",
    "get_work_item_by_id",
    "get_editable_field_options",
    "search_work_items_by_title",
    "search_work_items_with_filters",
    "store_pending_plan",
    "generate_update_preview",
]
