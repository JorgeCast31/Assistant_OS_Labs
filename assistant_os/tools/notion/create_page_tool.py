"""
Tool — Notion Create Page

Wraps create_work_item(work_request) as a stateless Tool.

Input keys
----------
work_request : dict — Work item specification passed to create_work_item

Output (ToolResult.data on success)
------------------------------------
page_id : str — Notion page ID of the created item
url     : str — Notion page URL
title   : str — Title of the created item

Note on test patchability
--------------------------
create_work_item is lazy-imported from webhook_server (not directly from
integrations.notion) so that existing test patches applied to
assistant_os.webhook_server.create_work_item remain effective.
"""

from __future__ import annotations

from ..base.tool import Tool
from ..base.tool_result import ToolResult
from ..base.tool_error import ToolError

_PROVIDER = "notion"
_OPERATION = "create_page"


class CreatePageTool(Tool):
    """Create a new page in the Notion WORK database."""

    def execute(self, input: dict) -> ToolResult:
        """
        Args:
            input["work_request"]: Dict describing the work item to create.

        Returns:
            ToolResult with data={"notion_page_id": ..., "item": ...} on success.
        """
        from ...webhook_server import create_work_item

        work_request = input.get("work_request", {})
        metadata = {"provider": _PROVIDER, "operation": _OPERATION}

        if not work_request:
            return ToolResult(
                ok=False,
                data=None,
                error=ToolError(
                    code="MissingWorkRequest",
                    message="work_request is required",
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        try:
            result = create_work_item(work_request)
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

        if not result.get("ok", True):
            return ToolResult(
                ok=False,
                data=None,
                error=ToolError(
                    code="NotionCreateFailed",
                    message=result.get("error", "Notion create returned an error"),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        return ToolResult(
            ok=True,
            data={
                "page_id": result.get("page_id", ""),
                "url": result.get("url", ""),
                "title": result.get("title", ""),
            },
            error=None,
            metadata=metadata,
        )
