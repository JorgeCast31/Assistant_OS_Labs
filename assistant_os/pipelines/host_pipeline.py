"""
HOST Domain Pipeline v1

Entry point: execute(plan, context_id) -> DomainResult

Sits between the kernel and host_agent.execute_host_action().
Validates the plan's domain_payload, builds a HostActionRequest, delegates
to the agent, and wraps the result in a canonical DomainResult.

Domain payload shape (HOST)
---------------------------
All fields are present in a well-formed payload; optional fields default
to their zero-values when absent.

    {
        "action":    str   — "open_app" | "close_pid" | "open_directory"
                            | "open_url" | "list_directory" | "open_file"
                            | "read_text_file"
                            | "write_text_file" | "append_text_file"
                            | "create_directory",
        "confirmed": bool  — must be True for execution to proceed,
        "app_name":  str   — required for "open_app",
        "pid":       int   — required for "close_pid",
        "path":      str   — required for "open_directory" | "list_directory"
                            | "open_file" | "read_text_file"
                            | "write_text_file" | "append_text_file"
                            | "create_directory",
        "url":       str   — required for "open_url",
        "content":   str   — required for "write_text_file" | "append_text_file",
    }

Invariants
----------
- Pipeline never raises; all error paths return DomainResult with ok=False.
- confirmed is read from domain_payload; Gate 1 in execute_host_action()
  provides defense-in-depth for direct calls that bypass the pipeline.
- execution_id = plan["plan_id"] for audit correlation.
- HOST_AGENT_ID is NEVER taken from the payload — it is fixed in host_agent.py.
- HOST remains the native deterministic machine lane.
- Deprecated HOST_EXECUTOR=openclaw configuration is ignored with explicit
  fallback metadata rather than creating a second lane inside HOST.
"""

from __future__ import annotations

from .. import config
from ..contracts import (
    DomainResult,
    make_domain_result,
    ACTION_HOST_OPEN_APP,
    ACTION_HOST_CLOSE_PID,
    ACTION_HOST_OPEN_DIRECTORY,
    ACTION_HOST_OPEN_URL,
    ACTION_HOST_LIST_DIRECTORY,
    ACTION_HOST_OPEN_FILE,
    ACTION_HOST_READ_TEXT_FILE,
    ACTION_HOST_WRITE_TEXT_FILE,   # Phase 5A/5B
    ACTION_HOST_APPEND_TEXT_FILE,  # Phase 5A/5B
    ACTION_HOST_CREATE_DIRECTORY,  # Phase 5A/5B
    RESULT_TYPE_HOST_ACTION,
    EXECUTION_STATUS_REAL,
)
from ..agents.host_agent import HostActionRequest, execute_host_action


# ---------------------------------------------------------------------------
# Dispatch table — kernel ACTION_* → agent-level action string
# ---------------------------------------------------------------------------

_PLAN_TO_AGENT_ACTION: dict[str, str] = {
    ACTION_HOST_OPEN_APP:        "open_app",
    ACTION_HOST_CLOSE_PID:       "close_pid",
    ACTION_HOST_OPEN_DIRECTORY:  "open_directory",
    ACTION_HOST_OPEN_URL:        "open_url",
    ACTION_HOST_LIST_DIRECTORY:  "list_directory",
    ACTION_HOST_OPEN_FILE:       "open_file",
    ACTION_HOST_READ_TEXT_FILE:  "read_text_file",
    # Phase 5A/5B — sandboxed write
    ACTION_HOST_WRITE_TEXT_FILE:  "write_text_file",
    ACTION_HOST_APPEND_TEXT_FILE: "append_text_file",
    ACTION_HOST_CREATE_DIRECTORY: "create_directory",
}

# Fields that MUST be present (and non-empty / non-None) per agent action.
# "confirmed" is always required and checked separately as a bool.
_REQUIRED_NON_EMPTY: dict[str, list[str]] = {
    "open_app":        ["app_name"],
    "close_pid":       [],           # pid validated separately (int check)
    "open_directory":  ["path"],
    "open_url":        ["url"],
    "list_directory":  ["path"],
    "open_file":       ["path"],
    "read_text_file":  ["path"],
    # Phase 5A/5B — sandboxed write
    # content is intentionally NOT required here for write_text_file:
    # an empty string is a valid write (create empty file).  The agent
    # enforces size and encoding; an absent "content" key defaults to "".
    "write_text_file":  ["path"],
    "append_text_file": ["path"],    # content="" is valid (no-op append)
    "create_directory": ["path"],
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def execute(plan: dict, context_id: str) -> DomainResult:
    """
    Execute a HOST domain plan.

    Never raises — all error paths produce a DomainResult with ok=False.
    """
    try:
        result = _dispatch(plan, context_id)
        result["execution_status"] = EXECUTION_STATUS_REAL
        return result
    except Exception as exc:  # pragma: no cover — belt-and-suspenders
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_HOST_ACTION,
            domain="HOST",
            message="Unexpected error in HOST pipeline",
            data={},
            error={"type": "HostPipelineError", "message": str(exc)},
        )


# ---------------------------------------------------------------------------
# Internal dispatch
# ---------------------------------------------------------------------------


def _dispatch(plan: dict, context_id: str) -> DomainResult:
    plan_action = plan.get("action", "")
    agent_action = _PLAN_TO_AGENT_ACTION.get(plan_action)

    if agent_action is None:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_HOST_ACTION,
            domain="HOST",
            message=f"Unknown HOST action: {plan_action!r}",
            data={"plan_action": plan_action},
            error={
                "type": "UnknownHostAction",
                "message": f"No handler for HOST action: {plan_action!r}",
            },
        )

    payload = plan.get("domain_payload")
    if not isinstance(payload, dict):
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_HOST_ACTION,
            domain="HOST",
            message="domain_payload is missing or not a dict",
            data={"plan_action": plan_action},
            error={
                "type": "InvalidHostPayload",
                "message": "domain_payload must be a dict",
            },
        )

    # Validate "confirmed" — must be present and True
    if "confirmed" not in payload:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_HOST_ACTION,
            domain="HOST",
            message="domain_payload missing required field: 'confirmed'",
            data={"agent_action": agent_action, "missing_fields": ["confirmed"]},
            error={
                "type": "InvalidHostPayload",
                "message": "Missing required field: 'confirmed'",
            },
        )

    # Validate action-specific required non-empty fields
    required_nonempty = _REQUIRED_NON_EMPTY.get(agent_action, [])
    missing = [f for f in required_nonempty if not payload.get(f)]
    if agent_action == "close_pid" and payload.get("pid") is None:
        missing.append("pid")
    if missing:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_HOST_ACTION,
            domain="HOST",
            message=f"Missing required payload fields for {agent_action!r}: {missing}",
            data={"agent_action": agent_action, "missing_fields": missing},
            error={
                "type": "InvalidHostPayload",
                "message": f"Missing fields for {agent_action!r}: {missing}",
            },
        )

    execution_id = plan.get("plan_id") or context_id

    request = HostActionRequest(
        execution_id=execution_id,
        action=agent_action,
        confirmed=bool(payload.get("confirmed", False)),
        app_name=payload.get("app_name", ""),
        pid=payload.get("pid"),
        path=payload.get("path", ""),
        url=payload.get("url", ""),
        content=payload.get("content", ""),  # Phase 5A/5B: write/append content
    )

    executor_name = "native"
    executor_notice = _deprecated_host_executor_notice()
    agent_result = execute_host_action(request)

    return _wrap_agent_result(
        agent_result,
        plan,
        agent_action,
        executor_name=executor_name,
        executor_notice=executor_notice,
    )


def _deprecated_host_executor_notice() -> str:
    """Return an explicit deprecation notice for legacy HOST OpenClaw config."""
    if config.HOST_EXECUTOR == "openclaw":
        return (
            "Deprecated HOST_EXECUTOR=openclaw ignored; "
            "OpenClaw belongs to the MACHINE_OPERATOR lane."
        )
    return ""


def _wrap_agent_result(
    agent_result,
    plan: dict,
    agent_action: str,
    *,
    executor_name: str,
    executor_notice: str = "",
) -> DomainResult:
    """
    Convert HostActionResult -> DomainResult.

    Deprecated HOST OpenClaw configuration only surfaces explicit deprecation
    metadata; native HOST execution remains authoritative.
    """
    data: dict = {
        "action":       agent_result.action,
        "execution_id": agent_result.execution_id,
    }
    if executor_name != "native" or executor_notice:
        data["executor"] = executor_name
    if agent_result.pid is not None:
        data["pid"] = agent_result.pid
    if agent_result.app_name:
        data["app_name"] = agent_result.app_name
    if agent_result.entries is not None:
        data["entries"] = agent_result.entries
    if agent_result.content is not None:
        data["content"] = agent_result.content
    if agent_result.error_code is not None:
        data["error_code"] = agent_result.error_code.value
    # Phase 5A/5B — write action result fields (never include file content)
    if agent_result.bytes_written is not None:
        data["bytes_written"] = agent_result.bytes_written
    if agent_result.write_mode is not None:
        data["write_mode"] = agent_result.write_mode
    # Phase 5C — atomic write observability
    if agent_result.atomic_replace_used is not None:
        data["atomic_replace_used"] = agent_result.atomic_replace_used
    if executor_notice:
        data["executor_deprecation_notice"] = executor_notice
    # Include path for write actions so the caller knows what was written.
    # Never include the content itself — only metadata.
    _domain_payload = plan.get("domain_payload") or {}
    if agent_action in ("write_text_file", "append_text_file", "create_directory"):
        path = _domain_payload.get("path", "")
        if path:
            data["path"] = path

    plan_id  = plan.get("plan_id")
    trace_id = plan.get("trace_id")

    if agent_result.ok:
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_HOST_ACTION,
            domain="HOST",
            message=f"HOST {agent_action} completed",
            data=data,
            plan_id=plan_id,
            trace_id=trace_id,
        )

    error_type = (
        agent_result.error_code.value
        if agent_result.error_code
        else "HostActionFailed"
    )
    return make_domain_result(
        ok=False,
        result_type=RESULT_TYPE_HOST_ACTION,
        domain="HOST",
        message=agent_result.error or f"HOST {agent_action} failed",
        data=data,
        error={
            "type": error_type,
            "message": agent_result.error or f"HOST {agent_action} failed",
        },
        plan_id=plan_id,
        trace_id=trace_id,
    )
