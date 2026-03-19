"""
Tool Architecture — ToolResult

Canonical output of every Tool.execute() call.

Fields
------
ok       : True when the tool call succeeded, False on any failure.
data     : Provider response payload on success; None on failure.
error    : ToolError on failure; None on success.
metadata : Non-critical diagnostic information (provider, operation,
           latency hints, etc.). Always present; defaults to empty dict.

Invariants
----------
ok=True  → error is None
ok=False → error is a ToolError instance
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .tool_error import ToolError


@dataclass
class ToolResult:
    ok: bool
    data: Optional[dict]
    error: Optional[ToolError]
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ok and self.error is not None:
            raise ValueError("ToolResult: ok=True but error is set")
        if not self.ok and self.error is None:
            raise ValueError("ToolResult: ok=False but error is None")
