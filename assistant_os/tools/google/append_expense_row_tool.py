"""
Tool — Google Sheets Append Expense Row

Wraps append_expense_row() as a stateless Tool.

Input keys (all correspond 1-to-1 with append_expense_row parameters)
----------------------------------------------------------------------
fecha        : str   — Date in YYYY-MM-DD format
descripcion  : str   — Description of expense
factura      : str   — Invoice/receipt ID (empty string if none)
responsable  : str   — Canonical responsable value
monto        : float — Amount
moneda       : str   — "USD" or "PAB"
itbms        : bool  — Whether ITBMS tax applies
categoria    : str   — Canonical category value
metodo_pago  : str   — Payment method (default "")
notas        : str   — Notes (default "")
fuente       : str   — Source label, e.g. "chat" or "Texto" (default "Texto")
link_archivo : str   — File link (default "")
expense_id   : str   — Session/expense ID (default "")

Output (ToolResult.data on success)
------------------------------------
row_number : int — Row number in the sheet where the expense was appended

Note on imports
---------------
append_expense_row is imported from webhook_server (not directly from
integrations.sheets) so that existing test patches on
assistant_os.webhook_server.append_expense_row remain effective.
"""

from __future__ import annotations

from ..base.tool import Tool
from ..base.tool_result import ToolResult
from ..base.tool_error import ToolError

_PROVIDER = "google_sheets"
_OPERATION = "append_expense_row"


class AppendExpenseRowTool(Tool):
    """Append a single expense row to Google Sheets."""

    def execute(self, input: dict) -> ToolResult:
        """
        Args:
            input: Dict with keys matching append_expense_row parameters.
                   See module docstring for full key list.

        Returns:
            ToolResult with data={"row_number": n} on success.
        """
        from ...webhook_server import append_expense_row

        metadata = {"provider": _PROVIDER, "operation": _OPERATION}

        try:
            result = append_expense_row(
                fecha=input.get("fecha", ""),
                descripcion=input.get("descripcion", ""),
                factura=input.get("factura", ""),
                responsable=input.get("responsable", ""),
                monto=float(input.get("monto", 0)),
                moneda=input.get("moneda", "USD"),
                itbms=bool(input.get("itbms", False)),
                categoria=input.get("categoria", ""),
                metodo_pago=input.get("metodo_pago", "") or "",
                notas=input.get("notas", ""),
                fuente=input.get("fuente", "Texto"),
                link_archivo=input.get("link_archivo", ""),
                expense_id=input.get("expense_id", ""),
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

        if not result.get("ok"):
            return ToolResult(
                ok=False,
                data=None,
                error=ToolError(
                    code="SheetsAppendFailed",
                    message=result.get("error", "Sheets append returned an error"),
                    provider=_PROVIDER,
                ),
                metadata=metadata,
            )

        return ToolResult(
            ok=True,
            data={"row_number": result.get("row_number")},
            error=None,
            metadata=metadata,
        )
