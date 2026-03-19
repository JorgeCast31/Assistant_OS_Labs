"""
Tool — Notion Update Page

Wraps update_work_item(page_id, changes, current_values) as a stateless Tool.

Input keys
----------
page_id        : str  — Notion page ID to update
changes        : dict — Field→value pairs to apply
current_values : dict — Current field values (for audit / conflict detection)

Output (ToolResult.data on success)
------------------------------------
notion_page_id  : str        — The updated page ID
changes_applied : list[dict] — Changes applied as [{field, from, to}, ...]

Note on test patchability
--------------------------
update_work_item is lazy-imported from webhook_server (not directly from
integrations.notion) so that existing test patches applied to
assistant_os.webhook_server.update_work_item remain effective.
"""

from __future__ import annotations

from ..base.tool import Tool
from ..base.tool_result import ToolResult
from ..base.tool_error import ToolError

_PROVIDER = "notion"
_OPERATION = "update_page"


class UpdatePageTool(Tool):
    """Update a Notion page's editable fields."""

    def execute(self, input: dict) -> ToolResult:
        """
        Args:
            input["page_id"]:        Notion page ID string.
            input["changes"]:        Dict of field→value to update.
            input["current_values"]: Dict of current field values (may be empty).

        Returns:
            ToolResult with data={"notion_page_id": ..., "changes_applied": ...} on success.
        """
        from ...webhook_server import update_work_item

        page_id = input.get("page_id", "")
        changes = input.get("changes", {})
        current_values = input.get("current_values", {})
        metadata = {"provider": _PROVIDER, "operation": _OPERATION}

        if not page_id:
            return ToolResult(
                ok=False,
                data=None,
                error=ToolError(
                    code="MissingPageId",
                    message="page_id is required",
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        try:
            result = update_work_item(
                page_id=page_id,
                changes=changes,
                current_values=current_values,
            )
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
                    code="NotionUpdateFailed",
                    message=result.get("error", "Notion update returned an error"),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        return ToolResult(
            ok=True,
            data={
                "notion_page_id": result.get("page_id", page_id),
                "changes_applied": result.get("changes_applied", []),
            },
            error=None,
            metadata=metadata,
        )
