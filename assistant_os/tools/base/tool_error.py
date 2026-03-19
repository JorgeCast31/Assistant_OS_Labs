"""
Tool Architecture — ToolError

Represents a technical failure returned by a Tool.

Fields
------
code     : Machine-readable error identifier (e.g. "NotionQueryFailed").
message  : Human-readable description of the failure.
provider : The external provider responsible (e.g. "notion", "google").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    provider: str
