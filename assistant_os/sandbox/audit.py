"""
Audit layer — structured, log-safe events for the sandbox control plane.

Event taxonomy
--------------
    ExecutionEvent   — execution lifecycle (started / completed / failed / aborted)
    SecretAccessEvent— secret lifecycle   (resolved / provisioned / invalidated)
    RevocationEvent  — revocation intent  (execution_revoked)
    OutputEvent      — output governance  (output_truncated)
    ArtifactEvent    — artifact lifecycle (artifact_collected / artifact_rejected)

Redaction invariant
-------------------
NONE of these event types ever carry a secret value.
- SecretAccessEvent carries only the secret name and opaque ref_token.
- OutputEvent carries only sizes and classifications — never output content.
- All to_dict() outputs are safe for structured logs and audit trails.

AuditLog
--------
Thread-safe in-memory event log.  Consumers query by event type or dump
everything for inspection.  For MVP this is process-local and ephemeral;
a persistent audit store is a future concern.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

class AuditEventType:
    # Execution lifecycle
    EXECUTION_STARTED             = "execution_started"
    EXECUTION_COMPLETED           = "execution_completed"
    EXECUTION_FAILED              = "execution_failed"
    EXECUTION_ABORTED             = "execution_aborted"
    # Backend infrastructure failure — distinct from sandbox code failure.
    # Emitted when TerminationReason.INTERNAL_ERROR is set (backend.execute()
    # raised an unhandled exception).  Do NOT use EXECUTION_FAILED for this
    # case — audit consumers must be able to distinguish infrastructure
    # unavailability from sandbox code-level failures without inspecting
    # the termination_reason field.
    EXECUTION_BACKEND_UNAVAILABLE = "execution_backend_unavailable"

    # Secret access
    SECRET_RESOLVED     = "secret_resolved"
    SECRET_PROVISIONED  = "secret_provisioned"
    SECRET_INVALIDATED  = "secret_invalidated"

    # Revocation
    EXECUTION_REVOKED   = "execution_revoked"

    # Output governance
    OUTPUT_TRUNCATED    = "output_truncated"

    # Artifact lifecycle
    ARTIFACT_COLLECTED  = "artifact_collected"
    ARTIFACT_REJECTED   = "artifact_rejected"


# ---------------------------------------------------------------------------
# ExecutionEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionEvent:
    """
    Lifecycle event for an ExecutionRun.

    Fields
    ------
    event_type         : one of AuditEventType.EXECUTION_*
    execution_id       : identifies the run
    plan_id            : authorizing plan
    timestamp          : wall-clock time (seconds since epoch)
    status             : execution status at event time
    termination_reason : why execution ended (for completed/failed/aborted)
    runtime_profile    : e.g. "python3.11"
    container_id       : Docker container name if known, else empty string
    """

    event_type: str
    execution_id: str
    plan_id: str
    timestamp: float
    status: str
    termination_reason: str = "none"
    runtime_profile: str = "python3.11"
    container_id: str = ""
    authorized_plan_hash: str = ""
    policy_id: str = ""

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "termination_reason": self.termination_reason,
            "runtime_profile": self.runtime_profile,
            "container_id": self.container_id,
            "authorized_plan_hash": self.authorized_plan_hash,
            "policy_id": self.policy_id,
        }


# ---------------------------------------------------------------------------
# SecretAccessEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretAccessEvent:
    """
    Secret access or lifecycle event.

    NEVER includes the secret value.  Only the opaque ref_token and name
    are recorded.  ref_token is an opaque backend reference (e.g.
    "env:ANTHROPIC_API_KEY") — safe for logs since it is not the value.

    Fields
    ------
    event_type   : one of AuditEventType.SECRET_*
    secret_name  : env var name (e.g. "API_KEY") — not the value
    ref_token    : opaque backend reference — safe to log
    plan_id      : authorizing plan
    execution_id : execution this secret is associated with
    timestamp    : wall-clock time
    backend      : class name of the SecretBackend used
    required     : whether the secret was required
    """

    event_type: str
    secret_name: str    # env var name — NOT the value
    ref_token: str      # opaque reference — NOT the value
    plan_id: str
    execution_id: str
    timestamp: float
    backend: str = ""
    required: bool = True

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "secret_name": self.secret_name,
            "ref_token": self.ref_token,
            "plan_id": self.plan_id,
            "execution_id": self.execution_id,
            "timestamp": self.timestamp,
            "backend": self.backend,
            "required": self.required,
            # value: NEVER
        }


# ---------------------------------------------------------------------------
# RevocationEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevocationEvent:
    """
    Event emitted when an execution is revoked.

    Fields
    ------
    event_type   : AuditEventType.EXECUTION_REVOKED
    execution_id : execution that was revoked
    plan_id      : authorizing plan (empty if execution not yet registered)
    timestamp    : wall-clock time
    reason       : "manual" | "policy" | "unknown"
    """

    event_type: str
    execution_id: str
    plan_id: str
    timestamp: float
    reason: str = "manual"

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "timestamp": self.timestamp,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# OutputEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutputEvent:
    """
    Emitted when an output stream is truncated or suppressed by OutputPolicy.

    There is NO silent truncation — every size reduction must produce an event.

    Fields
    ------
    event_type       : AuditEventType.OUTPUT_TRUNCATED
    execution_id     : identifies the run
    plan_id          : authorizing plan
    timestamp        : wall-clock time
    stream           : "stdout" | "stderr"
    original_bytes   : byte count of the raw stream before policy was applied
    retained_bytes   : byte count actually stored (0 for blocked streams)
    policy_id        : output policy that caused the truncation
    classification   : stream classification from policy (e.g. "blocked")

    Note: this event never carries the output content itself.
    """

    event_type: str
    execution_id: str
    plan_id: str
    timestamp: float
    stream: str             # "stdout" | "stderr"
    original_bytes: int
    retained_bytes: int
    policy_id: str
    classification: str = ""

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "timestamp": self.timestamp,
            "stream": self.stream,
            "original_bytes": self.original_bytes,
            "retained_bytes": self.retained_bytes,
            "policy_id": self.policy_id,
            "classification": self.classification,
        }


# ---------------------------------------------------------------------------
# ArtifactEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactEvent:
    """
    Emitted when an artifact is collected from or rejected by ArtifactPolicy.

    Fields
    ------
    event_type       : AuditEventType.ARTIFACT_COLLECTED | ARTIFACT_REJECTED
    execution_id     : identifies the run
    plan_id          : authorizing plan
    timestamp        : wall-clock time
    artifact_path    : relative path from workspace root (e.g. "out/result.json")
    size_bytes       : file size at collection time (0 for rejected files)
    classification   : artifact classification (e.g. "output", "log", "data")
    rejection_reason : reason for rejection (only set for ARTIFACT_REJECTED)
    sha256           : hex-encoded SHA-256 of file contents (empty for rejected)
    """

    event_type: str
    execution_id: str
    plan_id: str
    timestamp: float
    artifact_path: str
    size_bytes: int
    classification: str = ""
    rejection_reason: str = ""
    sha256: str = ""

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "timestamp": self.timestamp,
            "artifact_path": self.artifact_path,
            "size_bytes": self.size_bytes,
            "classification": self.classification,
            "rejection_reason": self.rejection_reason,
            "sha256": self.sha256,
        }


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------


class AuditLog:
    """
    Thread-safe in-memory event log.

    All events emitted through this log are immutable frozen dataclasses.
    The log itself is safe for concurrent writes and reads.

    Usage
    -----
        log = AuditLog()
        log.emit(ExecutionEvent(event_type=..., ...))
        started = log.events(AuditEventType.EXECUTION_STARTED)
    """

    def __init__(self) -> None:
        self._events: list[Any] = []
        self._lock = threading.Lock()

    def emit(self, event: Any) -> None:
        """
        Record an audit event.  Thread-safe.

        The event object is expected to be a frozen dataclass with to_dict().
        Non-conforming objects are accepted but will fail at serialization time.
        """
        with self._lock:
            self._events.append(event)

    def events(self, event_type: Optional[str] = None) -> list[Any]:
        """
        Return a snapshot of all events (or filtered by event_type).

        Returns a copy — callers cannot mutate the internal list.
        """
        with self._lock:
            if event_type is None:
                return list(self._events)
            return [e for e in self._events if getattr(e, "event_type", None) == event_type]

    def all_dicts(self) -> list[dict]:
        """Return all events serialised to dicts.  Safe for logging."""
        with self._lock:
            return [e.to_dict() for e in self._events]

    def count(self, event_type: Optional[str] = None) -> int:
        """Return count of events, optionally filtered by type."""
        return len(self.events(event_type))

    def clear(self) -> None:
        """Discard all events.  Primarily useful in tests."""
        with self._lock:
            self._events.clear()
