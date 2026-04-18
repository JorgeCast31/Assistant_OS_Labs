"""
Historical HOST-scoped OpenClaw scaffold.

This module is quarantined and non-authoritative.
OpenClaw is doctrinally part of the MACHINE_OPERATOR lane, not HOST.

No active pipeline should treat this module as a supported runtime path.
If called, it raises an explicit deprecation error rather than attempting any
execution or protocol shaping.
"""

from __future__ import annotations

from ..agents.host_agent import HostActionRequest, HostActionResult


class OpenClawAdapterError(RuntimeError):
    """Base class for quarantined historical HOST OpenClaw failures."""


class OpenClawDeprecatedInHost(OpenClawAdapterError):
    """Raised when historical HOST OpenClaw scaffolding is invoked."""


class OpenClawProtocolNotConfigured(OpenClawDeprecatedInHost):
    """Compatibility alias for the retired HOST-scoped scaffold."""


def execute_host_action_via_openclaw(
    request: HostActionRequest,
    *,
    plan: dict,
) -> HostActionResult:
    """Deprecated historical shim; HOST must not route OpenClaw anymore."""
    raise OpenClawDeprecatedInHost(
        "OpenClaw no longer routes through HOST; use the MACHINE_OPERATOR lane."
    )
