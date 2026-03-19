"""
Tool Architecture — Tool base class

All tools inherit from Tool and implement execute().

A Tool is a stateless technical capability:
- It calls an external provider (API, database, LLM).
- It returns a ToolResult.
- It has no knowledge of domains, pipelines, or DomainResult.
- It performs no semantic interpretation.

Pipelines instantiate tools, call execute(), and interpret ToolResult
into DomainResult. The tool layer is invisible to the kernel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .tool_result import ToolResult


class Tool(ABC):
    """Abstract base class for all Assistant OS tools."""

    @abstractmethod
    def execute(self, input: dict) -> ToolResult:
        """
        Execute the tool with the given input parameters.

        Args:
            input: Provider-specific parameter dict. Each tool documents
                   its own expected keys.

        Returns:
            ToolResult with ok, data, error, and metadata.
        """
        raise NotImplementedError
