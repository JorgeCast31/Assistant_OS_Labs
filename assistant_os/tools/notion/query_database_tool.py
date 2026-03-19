"""
Tool — Notion Query Database

Wraps query_work_db() as a stateless Tool.

Input keys
----------
filters : dict  — Query filters (project, status, domain, etc.)
limit   : int   — Maximum number of results (default 20)

Output (ToolResult.data on success)
------------------------------------
items   : list  — Work items returned by Notion
total   : int   — Total number of matching items

Note on test patchability
--------------------------
query_work_db is lazy-imported from webhook_server (not directly from
integrations.notion) so that existing test patches applied to
assistant_os.webhook_server.query_work_db remain effective.
"""

from __future__ import annotations

from ..base.tool import Tool
from ..base.tool_result import ToolResult
from ..base.tool_error import ToolError

_PROVIDER = "notion"
_OPERATION = "query_database"


class QueryDatabaseTool(Tool):
    """Execute a filtered query against the Notion WORK database."""

    def execute(self, input: dict) -> ToolResult:
        """
        Args:
            input["filters"]: Query filter dict passed to query_work_db.
            input["limit"]:   Result limit (default 20).

        Returns:
            ToolResult with data={"items": [...], "total": n} on success.
        """
        from ...webhook_server import query_work_db

        filters = input.get("filters", {})
        limit = input.get("limit", 20)
        metadata = {"provider": _PROVIDER, "operation": _OPERATION}

        try:
            result = query_work_db(filters=filters, limit=limit)
        except Exception as exc:
            return ToolResult(
                ok=False,
                data=None,
                error=ToolError(
                    code="ToolException",
                    message=str(exc),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        # query_work_db signals failure via ok=False or raises.
        if not result.get("ok", True):
            return ToolResult(
                ok=False,
                data=None,
                error=ToolError(
                    code="NotionQueryFailed",
                    message=result.get("error", "Notion query returned an error"),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        return ToolResult(
            ok=True,
            data={
                "items": result.get("items", []),
                "total": result.get("total", 0),
            },
            error=None,
            metadata=metadata,
        )
