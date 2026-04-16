"""
host_audit.py — Structured audit events for HOST domain execution.

Two event types
---------------
HostIntentEvent  — emitted BEFORE subprocess.Popen; records launch intent.
HostOutcomeEvent — emitted AFTER subprocess.Popen; records pid and result.

Invariants
----------
- Intent MUST be emitted before any Popen call.
- If emit_host_intent() raises HostAuditError, the caller MUST abort the launch.
- Outcome is emitted after a successful Popen; pid is always included.
- HOST_AUDIT_LOG is module-level and thread-safe (same AuditLog impl as sandbox).

No secret values, no user content, no output content is ever stored in these events.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..sandbox.audit import AuditLog


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class HostAuditError(Exception):
    """
    Raised when intent audit emission fails.
    Caller must treat this as a hard abort — do NOT proceed to Popen.
    """


# ---------------------------------------------------------------------------
# Error taxonomy  (Phase 2.5)
# ---------------------------------------------------------------------------


class HostErrorCode(str, Enum):
    """
    Structured error codes for all HOST domain rejection and failure paths.

    Values are lowercase strings so they serialize cleanly to JSON/logs without
    further transformation.  Distinct codes allow callers to branch on cause
    without parsing free-form error messages.
    """
    # Gate failures (shared across all actions)
    CONFIRMED_REQUIRED      = "confirmed_required"
    CONTROL_PLANE_BLOCKED   = "control_plane_blocked"
    AUDIT_FAILURE           = "audit_failure"
    UNKNOWN_ACTION          = "unknown_action"
    RATE_LIMIT_EXCEEDED     = "rate_limit_exceeded"

    # open_app
    INVALID_APP_NAME        = "invalid_app_name"

    # close_pid
    INVALID_PID             = "invalid_pid"
    PID_NOT_OWNED           = "pid_not_owned"
    PROCESS_ALREADY_EXITED  = "process_already_exited"

    # open_directory / list_directory
    DIRECTORY_NOT_ALLOWED   = "directory_not_allowed"
    DIRECTORY_NOT_FOUND     = "directory_not_found"

    # open_url
    URL_INVALID             = "url_invalid"
    URL_SCHEME_NOT_ALLOWED  = "url_scheme_not_allowed"
    URL_DOMAIN_NOT_ALLOWED  = "url_domain_not_allowed"

    # open_file / read_text_file
    FILE_NOT_ALLOWED        = "file_not_allowed"
    EXTENSION_NOT_ALLOWED   = "extension_not_allowed"
    FILE_NOT_FOUND          = "file_not_found"
    FILE_TOO_LARGE          = "file_too_large"
    INVALID_ENCODING        = "invalid_encoding"

    # write_text_file / append_text_file / create_directory (Phase 5A)
    WRITE_NOT_ALLOWED       = "write_not_allowed"
    DIRECTORY_ALREADY_EXISTS = "directory_already_exists"
    PATH_CONFLICT           = "path_conflict"

    # symlink / junction rejection (Phase 5D)
    # Emitted when the target path or any parent component is a symlink or
    # NTFS junction.  Symlinks are unconditionally blocked in write sandbox
    # paths because they can redirect writes outside the sandbox boundary.
    SYMLINK_NOT_ALLOWED     = "symlink_not_allowed"


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------


class HostAuditEventType:
    # Fase 1 — open_app specific (kept for backward compat)
    HOST_INTENT  = "host_intent"
    HOST_OUTCOME = "host_outcome"
    # Fase 2 — generic action events (close_pid, open_directory, open_url)
    HOST_ACTION_INTENT  = "host_action_intent"
    HOST_ACTION_OUTCOME = "host_action_outcome"
    # Phase 2.5 — gate-level rejections (confirmed, CP status, rate limit)
    HOST_REJECTION = "host_rejection"


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HostIntentEvent:
    """
    Audit event emitted before host process launch.

    Fields
    ------
    event_type   : HostAuditEventType.HOST_INTENT
    agent_id     : agent initiating the launch
    execution_id : correlates with _IN_FLIGHT and outcome event
    app_name     : logical name from the allowlist (e.g. "notepad")
    executable   : resolved executable (e.g. "notepad.exe")
    timestamp    : wall-clock seconds since epoch
    """
    event_type:   str
    agent_id:     str
    execution_id: str
    app_name:     str
    executable:   str
    timestamp:    float

    def to_dict(self) -> dict:
        return {
            "event_type":   self.event_type,
            "agent_id":     self.agent_id,
            "execution_id": self.execution_id,
            "app_name":     self.app_name,
            "executable":   self.executable,
            "timestamp":    self.timestamp,
        }


@dataclass(frozen=True)
class HostOutcomeEvent:
    """
    Audit event emitted after successful host process launch.

    Fields
    ------
    event_type   : HostAuditEventType.HOST_OUTCOME
    agent_id     : agent that launched the process
    execution_id : matches the corresponding HostIntentEvent
    app_name     : logical name from the allowlist
    executable   : resolved executable
    pid          : PID returned by subprocess.Popen
    timestamp    : wall-clock seconds since epoch
    """
    event_type:   str
    agent_id:     str
    execution_id: str
    app_name:     str
    executable:   str
    pid:          int
    timestamp:    float

    def to_dict(self) -> dict:
        return {
            "event_type":   self.event_type,
            "agent_id":     self.agent_id,
            "execution_id": self.execution_id,
            "app_name":     self.app_name,
            "executable":   self.executable,
            "pid":          self.pid,
            "timestamp":    self.timestamp,
        }


# ---------------------------------------------------------------------------
# Module-level audit log
# ---------------------------------------------------------------------------

HOST_AUDIT_LOG: AuditLog = AuditLog()


# ---------------------------------------------------------------------------
# Emission helpers
# ---------------------------------------------------------------------------


def emit_host_intent(
    *,
    agent_id:     str,
    app_name:     str,
    execution_id: str,
    executable:   str,
) -> None:
    """
    Emit a HostIntentEvent to HOST_AUDIT_LOG.

    MUST be called before subprocess.Popen.
    Raises HostAuditError on any failure — caller MUST abort launch.
    """
    try:
        event = HostIntentEvent(
            event_type=HostAuditEventType.HOST_INTENT,
            agent_id=agent_id,
            execution_id=execution_id,
            app_name=app_name,
            executable=executable,
            timestamp=time.time(),
        )
        HOST_AUDIT_LOG.emit(event)
    except Exception as exc:
        raise HostAuditError(f"failed to emit host intent: {exc}") from exc


def emit_host_outcome(
    *,
    agent_id:     str,
    app_name:     str,
    execution_id: str,
    executable:   str,
    pid:          int,
) -> None:
    """
    Emit a HostOutcomeEvent to HOST_AUDIT_LOG.

    Called after subprocess.Popen returns successfully.
    Includes the pid so audit trail is complete.
    """
    event = HostOutcomeEvent(
        event_type=HostAuditEventType.HOST_OUTCOME,
        agent_id=agent_id,
        execution_id=execution_id,
        app_name=app_name,
        executable=executable,
        pid=pid,
        timestamp=time.time(),
    )
    HOST_AUDIT_LOG.emit(event)


# ---------------------------------------------------------------------------
# Fase 2 — generic action events (close_pid, open_directory, open_url)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HostActionIntentEvent:
    """
    Generic intent event for Fase 2 actions.

    Fields
    ------
    event_type   : HostAuditEventType.HOST_ACTION_INTENT
    agent_id     : always HOST_AGENT_ID
    execution_id : correlates with outcome event
    action       : "close_pid" | "open_directory" | "open_url"
    target       : action-specific target (str(pid), path, or url)
    timestamp    : wall-clock seconds since epoch
    """
    event_type:   str
    agent_id:     str
    execution_id: str
    action:       str
    target:       str
    timestamp:    float

    def to_dict(self) -> dict:
        return {
            "event_type":   self.event_type,
            "agent_id":     self.agent_id,
            "execution_id": self.execution_id,
            "action":       self.action,
            "target":       self.target,
            "timestamp":    self.timestamp,
        }


@dataclass(frozen=True)
class HostActionOutcomeEvent:
    """
    Generic outcome event for Fase 2 actions.

    Fields
    ------
    event_type   : HostAuditEventType.HOST_ACTION_OUTCOME
    agent_id     : always HOST_AGENT_ID
    execution_id : matches the corresponding HostActionIntentEvent
    action       : "close_pid" | "open_directory" | "open_url"
    target       : action-specific target
    result       : "terminated" | "opened" | "failed"
    pid          : PID if a process was launched (None for close_pid/open_url)
    timestamp    : wall-clock seconds since epoch
    """
    event_type:   str
    agent_id:     str
    execution_id: str
    action:       str
    target:       str
    result:       str
    pid:          Optional[int]
    timestamp:    float

    def to_dict(self) -> dict:
        return {
            "event_type":   self.event_type,
            "agent_id":     self.agent_id,
            "execution_id": self.execution_id,
            "action":       self.action,
            "target":       self.target,
            "result":       self.result,
            "pid":          self.pid,
            "timestamp":    self.timestamp,
        }


def emit_action_intent(
    *,
    agent_id:     str,
    execution_id: str,
    action:       str,
    target:       str,
) -> None:
    """
    Emit a HostActionIntentEvent to HOST_AUDIT_LOG.

    MUST be called before execution of any Fase 2 action.
    Raises HostAuditError on any failure — caller MUST abort execution.
    """
    try:
        event = HostActionIntentEvent(
            event_type=HostAuditEventType.HOST_ACTION_INTENT,
            agent_id=agent_id,
            execution_id=execution_id,
            action=action,
            target=target,
            timestamp=time.time(),
        )
        HOST_AUDIT_LOG.emit(event)
    except Exception as exc:
        raise HostAuditError(f"failed to emit action intent: {exc}") from exc


def emit_action_outcome(
    *,
    agent_id:     str,
    execution_id: str,
    action:       str,
    target:       str,
    result:       str,
    pid:          Optional[int] = None,
) -> None:
    """
    Emit a HostActionOutcomeEvent to HOST_AUDIT_LOG.

    Called after the action completes (process launched, pid killed, dir opened).
    """
    event = HostActionOutcomeEvent(
        event_type=HostAuditEventType.HOST_ACTION_OUTCOME,
        agent_id=agent_id,
        execution_id=execution_id,
        action=action,
        target=target,
        result=result,
        pid=pid,
        timestamp=time.time(),
    )
    HOST_AUDIT_LOG.emit(event)


# ---------------------------------------------------------------------------
# Phase 2.5 — rejection audit (gate failures)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HostRejectionEvent:
    """
    Audit event emitted when a request is rejected at a gate (Gate 1: confirmed,
    Gate 2: CP status, rate limit, or unknown action).

    Invariant 4 requires that CP-level rejections are audited, not just returned
    silently as error results.

    Fields
    ------
    event_type   : HostAuditEventType.HOST_REJECTION
    agent_id     : always HOST_AGENT_ID
    execution_id : echoed from the rejected request
    action       : the action that was attempted
    reason       : human-readable rejection reason
    error_code   : structured HostErrorCode value
    timestamp    : wall-clock seconds since epoch
    """
    event_type:   str
    agent_id:     str
    execution_id: str
    action:       str
    reason:       str
    error_code:   HostErrorCode
    timestamp:    float

    def to_dict(self) -> dict:
        return {
            "event_type":   self.event_type,
            "agent_id":     self.agent_id,
            "execution_id": self.execution_id,
            "action":       self.action,
            "reason":       self.reason,
            "error_code":   self.error_code.value,
            "timestamp":    self.timestamp,
        }


def emit_host_rejection(
    *,
    agent_id:     str,
    execution_id: str,
    action:       str,
    reason:       str,
    error_code:   HostErrorCode,
) -> None:
    """
    Emit a HostRejectionEvent to HOST_AUDIT_LOG.

    Called by execute_host_action whenever a gate-level rejection fires
    (confirmed=False, agent not ACTIVE, rate limit exceeded, unknown action).

    Unlike emit_host_intent, this function does NOT raise on failure — rejection
    audit is best-effort; the rejection itself is the primary response.
    """
    try:
        event = HostRejectionEvent(
            event_type=HostAuditEventType.HOST_REJECTION,
            agent_id=agent_id,
            execution_id=execution_id,
            action=action,
            reason=reason,
            error_code=error_code,
            timestamp=time.time(),
        )
        HOST_AUDIT_LOG.emit(event)
    except Exception:
        pass  # best-effort; never suppress the calling rejection path
