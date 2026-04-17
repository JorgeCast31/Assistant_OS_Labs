"""
OpenClaw adapter for the canonical HOST pipeline.

This module is intentionally narrow:
- It only accepts HostActionRequest + canonical plan metadata.
- It only supports the phase-1 HOST actions approved for OpenClaw.
- It owns all OpenClaw wire/protocol details behind one helper boundary.

The HOST pipeline remains the sole caller and preserves canonical contracts:
CanonicalRequest -> PolicyDecision -> ExecutionPlan -> HOST pipeline -> DomainResult

Protocol note
-------------
The live OpenClaw gateway protocol is intentionally NOT guessed here.
Until the documented JSON message schema is provided in-repo, the wire helper
raises a protocol-configuration error and the HOST pipeline falls back to the
native executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import config
from ..agents.host_agent import HostActionRequest, HostActionResult


OPENCLAW_ELIGIBLE_ACTIONS: frozenset[str] = frozenset({
    "list_directory",
    "read_text_file",
    "open_directory",
})


class OpenClawAdapterError(RuntimeError):
    """Base class for OpenClaw adapter failures."""


class OpenClawProtocolNotConfigured(OpenClawAdapterError):
    """Raised when the documented gateway wire schema has not been implemented."""


class OpenClawGatewayTimeout(OpenClawAdapterError):
    """Raised when the gateway round-trip exceeds the configured timeout."""


@dataclass(frozen=True)
class OpenClawExecutionContext:
    """Canonical metadata forwarded to the gateway envelope when available."""

    gateway_url: str
    timeout_seconds: float
    plan_id: str
    execution_id: str
    trace_id: str
    intent: str
    capability: Any = None


def is_openclaw_eligible(action: str) -> bool:
    """Return True if *action* is allowed through OpenClaw in phase 1."""
    return action in OPENCLAW_ELIGIBLE_ACTIONS


def build_execution_context(plan: dict, request: HostActionRequest) -> OpenClawExecutionContext:
    """Extract canonical metadata for the adapter without mutating the plan."""
    payload = plan.get("domain_payload") or {}
    capability = payload.get("capability")
    if capability is None:
        capability = plan.get("capability")
    if capability is None:
        capability = plan.get("capability_scope")

    return OpenClawExecutionContext(
        gateway_url=config.OPENCLAW_GATEWAY_URL,
        timeout_seconds=config.OPENCLAW_TIMEOUT_SECONDS,
        plan_id=plan.get("plan_id", ""),
        execution_id=request.execution_id,
        trace_id=plan.get("trace_id", ""),
        intent=payload.get("intent") or plan.get("action", ""),
        capability=capability,
    )


def execute_host_action_via_openclaw(
    request: HostActionRequest,
    *,
    plan: dict,
) -> HostActionResult:
    """
    Execute an eligible HOST action through OpenClaw.

    The adapter returns HostActionResult so the HOST pipeline can keep using
    the same wrapping logic and fallback path as the native executor.
    """
    if not is_openclaw_eligible(request.action):
        raise OpenClawAdapterError(
            f"action {request.action!r} is not eligible for OpenClaw phase-1 routing"
        )

    context = build_execution_context(plan, request)
    envelope = _build_gateway_envelope(request, context)
    response = _send_gateway_envelope(envelope, context=context)
    return _translate_gateway_response(response, request=request)


def _build_gateway_envelope(
    request: HostActionRequest,
    context: OpenClawExecutionContext,
) -> dict[str, Any]:
    """Build the canonical control-plane message for the OpenClaw gateway."""
    return {
        "type": "host_execution_request",
        "executor": "openclaw",
        "domain": "HOST",
        "action": request.action,
        "request": {
            "execution_id": request.execution_id,
            "confirmed": request.confirmed,
            "app_name": request.app_name,
            "pid": request.pid,
            "path": request.path,
            "url": request.url,
            "content": request.content,
        },
        "control": {
            "plan_id": context.plan_id,
            "execution_id": context.execution_id,
            "trace_id": context.trace_id,
            "intent": context.intent,
            "capability": context.capability,
            "timeout_seconds": context.timeout_seconds,
        },
    }


def _send_gateway_envelope(
    envelope: dict[str, Any],
    *,
    context: OpenClawExecutionContext,
) -> dict[str, Any]:
    """
    Send a JSON envelope to the OpenClaw WebSocket gateway.

    This is the only place where the gateway protocol should be implemented.
    The current phase intentionally stops short of inventing wire semantics.
    """
    raise OpenClawProtocolNotConfigured(
        "OpenClaw gateway wire helper is scaffolded but the documented "
        "WebSocket JSON protocol is not defined in this repository."
    )


def _translate_gateway_response(
    response: dict[str, Any],
    *,
    request: HostActionRequest,
) -> HostActionResult:
    """Translate a gateway JSON response into HostActionResult."""
    if not isinstance(response, dict):
        raise OpenClawAdapterError("gateway response must be a dict")

    ok = bool(response.get("ok"))
    error_code_raw = response.get("error_code")
    error_code = None
    if error_code_raw:
        from ..agents.host_audit import HostErrorCode

        try:
            error_code = HostErrorCode(error_code_raw)
        except ValueError as exc:
            raise OpenClawAdapterError(
                f"gateway returned unknown host error_code {error_code_raw!r}"
            ) from exc

    return HostActionResult(
        ok=ok,
        action=response.get("action", request.action),
        pid=response.get("pid"),
        execution_id=response.get("execution_id", request.execution_id),
        app_name=response.get("app_name", request.app_name),
        error=response.get("error"),
        error_code=error_code,
        entries=response.get("entries"),
        content=response.get("content"),
        bytes_written=response.get("bytes_written"),
        write_mode=response.get("write_mode"),
        atomic_replace_used=response.get("atomic_replace_used"),
    )
