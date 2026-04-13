"""
host_agent.py — HOST domain executor for Phase 1 + Phase 2 + Phase 2.5 hardening.

Canonical identity
------------------
HOST_AGENT_ID = "host_launcher"

All operations use this identity for control_plane, _IN_FLIGHT, and audit.
The caller never supplies an agent_id.

Supported actions
-----------------
"open_app"        — launch app from APP_REGISTRY (absolute paths)
"close_pid"       — SIGTERM a process owned by this agent
"open_directory"  — open an allowed directory in explorer
"open_url"        — open an allowed URL in default browser (https only)

Invariants enforced (all actions)
----------------------------------
1. confirmed must be True
2. HOST_AGENT_ID must be ACTIVE in control_plane
3. Rate limit not exceeded (open_app, open_directory, open_url)
4. action-specific validation (registry / allowlist / ownership)
5. intent audit emitted BEFORE execution; HostAuditError → abort
6. execution (Popen or os.kill)
7. register_in_flight for launched processes
8. outcome audit AFTER execution
9. gate-level rejections are audited via emit_host_rejection

app_name, path, url are NEVER treated as shell commands.
No shell=True anywhere.

Phase 2.5 additions
-------------------
- HostErrorCode on every HostActionResult failure
- validate_allowed_directory() — public, dedicated, normcase+normpath
- validate_allowed_url()       — public, dedicated, scheme + domain check
- reconcile_in_flight()        — called by close_pid before liveness attempt
- Rate limiting                — sliding window per action type
- Rejection audit              — Gate 1/2 failures emit HostRejectionEvent
"""

from __future__ import annotations

import ntpath
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Optional
from urllib.parse import urlparse

from ..core.control_plane import (
    AgentStatus,
    deregister_in_flight,
    get_agent_status,
    get_in_flight,
    reconcile_in_flight,
    register_in_flight,
)
from .host_audit import (
    HostAuditError,
    HostErrorCode,
    emit_action_intent,
    emit_action_outcome,
    emit_host_intent,
    emit_host_outcome,
    emit_host_rejection,
)


# ---------------------------------------------------------------------------
# Canonical agent identity
# ---------------------------------------------------------------------------

HOST_AGENT_ID: str = "host_launcher"


# ---------------------------------------------------------------------------
# APP_REGISTRY — absolute paths only
# ---------------------------------------------------------------------------

APP_REGISTRY: dict[str, str] = {
    "notepad":  r"C:\Windows\System32\notepad.exe",
    "calc":     r"C:\Windows\System32\calc.exe",
    "explorer": r"C:\Windows\explorer.exe",
}


# ---------------------------------------------------------------------------
# ALLOWED_DIRECTORIES — validated via validate_allowed_directory()
# ---------------------------------------------------------------------------

ALLOWED_DIRECTORIES: list[str] = [
    r"C:\Users\Jorge\Desktop",
    r"C:\Users\Jorge\Documents",
    r"C:\Users\Jorge\Downloads",
]


# ---------------------------------------------------------------------------
# ALLOWED_URL_DOMAINS + ALLOWED_URL_SCHEMES
# ---------------------------------------------------------------------------

ALLOWED_URL_DOMAINS: list[str] = [
    "github.com",
    "google.com",
    "stackoverflow.com",
    "docs.python.org",
]

# Only HTTPS is allowed.  HTTP is intentionally excluded:
# - No confidentiality in transit
# - Opens MitM injection surface
# To allow HTTP in a future sprint, add it here with explicit justification.
ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"https"})


# ---------------------------------------------------------------------------
# ALLOWED_EXTENSIONS — Phase 3A read-only filesystem
# ---------------------------------------------------------------------------

# Only document/data formats.  Executables (.exe, .bat, .cmd, .ps1, .vbs, …)
# are intentionally excluded — opening them via rundll32 would still trigger
# execution.  To add a new extension, justify the addition here.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".pdf", ".json", ".csv",
})

MAX_READ_SIZE_BYTES: int = 1_048_576   # 1 MB hard cap for read_text_file
LIST_DIRECTORY_LIMIT: int = 100        # max entries returned by list_directory


# ---------------------------------------------------------------------------
# Rate limits  (Phase 2.5 — P5)
# ---------------------------------------------------------------------------

# (max_calls, window_seconds) per action type.
# close_pid is intentionally excluded: it is a cleanup operation, not
# an expansion of capability, and rate-limiting it could prevent kill_switch
# from completing cleanly.
_ACTION_RATE_LIMITS: dict[str, tuple[int, float]] = {
    "open_app":        (10, 60.0),
    "open_directory":  (10, 60.0),
    "open_url":        (10, 60.0),
    # Phase 3A — filesystem read-only
    "list_directory":  (20, 60.0),
    "open_file":       (10, 60.0),
    "read_text_file":  (20, 60.0),
}

# action → list of call timestamps (epoch seconds)
_action_timestamps: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


def _check_rate_limit(action: str) -> tuple[bool, str]:
    """
    Return (True, "") if within the rate limit for action.
    Return (False, reason) if the limit is exceeded.
    Actions without an entry in _ACTION_RATE_LIMITS are always allowed.
    Thread-safe via _rate_lock.
    """
    limit = _ACTION_RATE_LIMITS.get(action)
    if limit is None:
        return True, ""

    max_calls, window_seconds = limit
    now = time.time()
    cutoff = now - window_seconds

    with _rate_lock:
        timestamps = _action_timestamps.get(action, [])
        # Evict expired entries
        fresh = [t for t in timestamps if t > cutoff]
        if len(fresh) >= max_calls:
            _action_timestamps[action] = fresh
            return False, (
                f"rate limit exceeded for {action!r}: "
                f"max {max_calls} calls per {window_seconds:.0f}s"
            )
        fresh.append(now)
        _action_timestamps[action] = fresh
        return True, ""


# ---------------------------------------------------------------------------
# Request / Result contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HostActionRequest:
    """
    Input contract for a host action request.

    Fields
    ------
    execution_id : correlates audit events and _IN_FLIGHT entries
    action       : "open_app" | "close_pid" | "open_directory" | "open_url"
    confirmed    : must be True for execution to proceed
    app_name     : (open_app only) logical name — must be in APP_REGISTRY
    pid          : (close_pid only) PID to terminate — must be in _IN_FLIGHT
    path         : (open_directory only) directory path — must be in allowlist
    url          : (open_url only) URL — scheme https, domain in allowlist

    Note: agent_id is NOT a caller-supplied field.  The executor always
    operates under HOST_AGENT_ID = "host_launcher".
    """
    execution_id: str
    action:       str = "open_app"
    confirmed:    bool = False
    app_name:     str = ""
    pid:          Optional[int] = None
    path:         str = ""
    url:          str = ""


@dataclass
class HostActionResult:
    """
    Output contract for a host action attempt.

    Fields
    ------
    ok           : True iff action completed successfully
    action       : echoed from request
    pid          : PID of launched/closed process (None if not applicable)
    execution_id : echoed from request for correlation
    app_name     : echoed from request (open_app only)
    error        : human-readable reason for failure (None on success)
    error_code   : structured HostErrorCode (None on success)
    entries      : directory listing (list_directory only)
    content      : file text content (read_text_file only)
    """
    ok:           bool
    action:       str = ""
    pid:          Optional[int] = None
    execution_id: str = ""
    app_name:     str = ""
    error:        Optional[str] = None
    error_code:   Optional[HostErrorCode] = None
    entries:      Optional[list] = None
    content:      Optional[str] = None


# ---------------------------------------------------------------------------
# Path validation helper  (Phase 2.5 — P2)
# ---------------------------------------------------------------------------


def validate_allowed_directory(path: str) -> tuple[bool, str]:
    """
    Validate that path equals or is a subdirectory of an ALLOWED_DIRECTORIES entry.

    Cross-platform implementation — uses Windows path semantics regardless of the
    OS running the code (important for CI running on Linux).

    Algorithm
    ---------
    1. Reject empty path immediately.
    2. Normalize with ntpath.normpath: resolves ".." and "." components using
       Windows path rules on ANY platform, preventing traversal attacks at the
       string level (e.g. "C:\\allowed\\..\\..\\Windows" → "C:\\Windows").
       ntpath is part of the Python standard library and works on Linux/macOS.
    3. Wrap in PureWindowsPath for comparison:
       - Equality and is_relative_to() are case-insensitive (Windows semantics).
       - is_relative_to() is component-based, not string-prefix-based, so
         "C:\\JorgeEvil" does NOT match "C:\\Jorge" (adjacent-prefix safe).

    Why not os.path
    ---------------
    os.path.normcase is a no-op on Linux (does not lowercase).
    os.path.normpath treats "\\" as a literal character on Linux (not a separator).
    os.sep is "/" on Linux, breaking the "startswith(allowed + sep)" subdirectory check.
    ntpath + PureWindowsPath are cross-platform by design and always use Windows rules.

    Symlink / junction note
    -----------------------
    ntpath.normpath resolves ".." at the string level but does not follow symlinks.
    A symlink whose path string falls inside the allowlist would pass this check
    even if its target is outside.  This is a documented limitation.

    Returns (True, "") on success, (False, reason_string) on any failure.
    """
    if not path:
        return False, "path is empty"

    # ntpath.normpath resolves ".." and "." with Windows semantics on all platforms
    norm = PureWindowsPath(ntpath.normpath(path))

    for allowed in ALLOWED_DIRECTORIES:
        allowed_norm = PureWindowsPath(ntpath.normpath(allowed))
        # PureWindowsPath equality and is_relative_to() are case-insensitive
        # and component-based — no os.sep dependency
        if norm == allowed_norm or norm.is_relative_to(allowed_norm):
            return True, ""

    return False, f"path {path!r} is not within ALLOWED_DIRECTORIES"


# ---------------------------------------------------------------------------
# URL validation helper  (Phase 2.5 — P3)
# ---------------------------------------------------------------------------


def validate_allowed_url(url: str) -> tuple[bool, str, Optional[HostErrorCode]]:
    """
    Validate that url is safe to open: correct scheme, allowed domain.

    Validation order (fail-fast)
    ----------------------------
    1. Empty / unparseable → URL_INVALID
    2. Scheme not in ALLOWED_URL_SCHEMES → URL_SCHEME_NOT_ALLOWED
       (Only "https" is permitted.  "http" is intentionally excluded.)
    3. Hostname absent or empty → URL_INVALID
    4. Hostname not an exact match or subdomain of ALLOWED_URL_DOMAINS → URL_DOMAIN_NOT_ALLOWED

    Subdomain matching: "docs.github.com" matches "github.com" because
    "docs.github.com".endswith(".github.com") is True.
    We do NOT use substring matching on raw strings.

    Returns (True, "", None) on success.
    Returns (False, reason, HostErrorCode) on failure.
    """
    if not url:
        return False, "url is empty", HostErrorCode.URL_INVALID

    try:
        parsed = urlparse(url)
    except Exception as exc:
        return False, f"url {url!r} could not be parsed: {exc}", HostErrorCode.URL_INVALID

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        return (
            False,
            f"url scheme {scheme!r} is not in ALLOWED_URL_SCHEMES {sorted(ALLOWED_URL_SCHEMES)}",
            HostErrorCode.URL_SCHEME_NOT_ALLOWED,
        )

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False, "url has no hostname", HostErrorCode.URL_INVALID

    for domain in ALLOWED_URL_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            return True, "", None

    return (
        False,
        f"url domain {hostname!r} is not in ALLOWED_URL_DOMAINS",
        HostErrorCode.URL_DOMAIN_NOT_ALLOWED,
    )


# ---------------------------------------------------------------------------
# File path validation helper  (Phase 3A)
# ---------------------------------------------------------------------------


def validate_allowed_file_path(path: str) -> tuple[bool, str]:
    """
    Validate that path is a file within ALLOWED_DIRECTORIES.

    Reuses the same ntpath + PureWindowsPath normalisation as
    validate_allowed_directory, providing identical traversal protection.

    The check is is_relative_to (strict containment), not equality, because a
    file can never equal a directory root in a meaningful operation.

    Returns (True, "") on success, (False, reason) on failure.
    """
    if not path:
        return False, "path is empty"

    norm = PureWindowsPath(ntpath.normpath(path))

    for allowed in ALLOWED_DIRECTORIES:
        allowed_norm = PureWindowsPath(ntpath.normpath(allowed))
        if norm.is_relative_to(allowed_norm):
            return True, ""

    return False, f"path {path!r} is not within ALLOWED_DIRECTORIES"


# ---------------------------------------------------------------------------
# Per-action handlers (private)
# ---------------------------------------------------------------------------


def _handle_open_app(request: HostActionRequest) -> HostActionResult:
    """open_app: resolve from APP_REGISTRY, audit, Popen, register."""
    executable = APP_REGISTRY.get(request.app_name)
    if not executable:
        return HostActionResult(
            ok=False, action="open_app",
            execution_id=request.execution_id,
            app_name=request.app_name,
            error=f"app_name {request.app_name!r} not in APP_REGISTRY",
            error_code=HostErrorCode.INVALID_APP_NAME,
        )

    # Intent audit (uses Fase 1 events for open_app — backward compat)
    try:
        emit_host_intent(
            agent_id=HOST_AGENT_ID,
            app_name=request.app_name,
            execution_id=request.execution_id,
            executable=executable,
        )
    except HostAuditError as exc:
        return HostActionResult(
            ok=False, action="open_app",
            execution_id=request.execution_id,
            app_name=request.app_name,
            error=f"intent audit failed — launch aborted: {exc}",
            error_code=HostErrorCode.AUDIT_FAILURE,
        )

    proc = subprocess.Popen([executable])
    pid = proc.pid

    register_in_flight(HOST_AGENT_ID, pid, request.execution_id)

    emit_host_outcome(
        agent_id=HOST_AGENT_ID,
        app_name=request.app_name,
        execution_id=request.execution_id,
        executable=executable,
        pid=pid,
    )

    return HostActionResult(
        ok=True, action="open_app", pid=pid,
        execution_id=request.execution_id,
        app_name=request.app_name,
    )


def _handle_close_pid(request: HostActionRequest) -> HostActionResult:
    """
    close_pid: reconcile registry, verify ownership, SIGTERM, deregister.

    Phase 2.5: calls reconcile_in_flight() first so that stale PIDs are
    removed before the ownership check.  A PID that was in _IN_FLIGHT but
    whose process already died will be cleaned by reconcile and then correctly
    rejected with PROCESS_ALREADY_EXITED rather than triggering an unhandled
    OSError.
    """
    pid = request.pid
    if pid is None:
        return HostActionResult(
            ok=False, action="close_pid",
            execution_id=request.execution_id,
            error="close_pid requires a non-None pid",
            error_code=HostErrorCode.INVALID_PID,
        )

    # Reconcile first — remove dead PIDs so ownership check reflects reality
    reconcile_in_flight(HOST_AGENT_ID)

    # Ownership check — only pids registered under HOST_AGENT_ID are allowed
    records = get_in_flight(HOST_AGENT_ID)
    if not any(r["pid"] == pid for r in records):
        return HostActionResult(
            ok=False, action="close_pid",
            execution_id=request.execution_id,
            error=f"pid {pid} is not a managed process of {HOST_AGENT_ID!r}",
            error_code=HostErrorCode.PID_NOT_OWNED,
        )

    # Intent audit
    try:
        emit_action_intent(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action="close_pid",
            target=str(pid),
        )
    except HostAuditError as exc:
        return HostActionResult(
            ok=False, action="close_pid",
            execution_id=request.execution_id,
            error=f"intent audit failed — abort: {exc}",
            error_code=HostErrorCode.AUDIT_FAILURE,
        )

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        # Process exited in the window between reconcile and kill — safe to clean up
        deregister_in_flight(HOST_AGENT_ID, pid)
        emit_action_outcome(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action="close_pid",
            target=str(pid),
            result="already_exited",
            pid=pid,
        )
        return HostActionResult(
            ok=False, action="close_pid",
            execution_id=request.execution_id,
            pid=pid,
            error=f"pid {pid} had already exited before SIGTERM could be sent",
            error_code=HostErrorCode.PROCESS_ALREADY_EXITED,
        )

    deregister_in_flight(HOST_AGENT_ID, pid)

    emit_action_outcome(
        agent_id=HOST_AGENT_ID,
        execution_id=request.execution_id,
        action="close_pid",
        target=str(pid),
        result="terminated",
        pid=pid,
    )

    return HostActionResult(
        ok=True, action="close_pid", pid=pid,
        execution_id=request.execution_id,
    )


def _handle_open_directory(request: HostActionRequest) -> HostActionResult:
    """open_directory: validate path via validate_allowed_directory, Popen explorer, register."""
    ok, reason = validate_allowed_directory(request.path)
    if not ok:
        return HostActionResult(
            ok=False, action="open_directory",
            execution_id=request.execution_id,
            error=reason,
            error_code=HostErrorCode.DIRECTORY_NOT_ALLOWED,
        )

    try:
        emit_action_intent(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action="open_directory",
            target=request.path,
        )
    except HostAuditError as exc:
        return HostActionResult(
            ok=False, action="open_directory",
            execution_id=request.execution_id,
            error=f"intent audit failed — abort: {exc}",
            error_code=HostErrorCode.AUDIT_FAILURE,
        )

    proc = subprocess.Popen([APP_REGISTRY["explorer"], request.path])
    pid = proc.pid

    register_in_flight(HOST_AGENT_ID, pid, request.execution_id)

    emit_action_outcome(
        agent_id=HOST_AGENT_ID,
        execution_id=request.execution_id,
        action="open_directory",
        target=request.path,
        result="opened",
        pid=pid,
    )

    return HostActionResult(
        ok=True, action="open_directory", pid=pid,
        execution_id=request.execution_id,
    )


def _handle_open_url(request: HostActionRequest) -> HostActionResult:
    """open_url: validate via validate_allowed_url, open via rundll32 (no shell=True)."""
    ok, reason, code = validate_allowed_url(request.url)
    if not ok:
        return HostActionResult(
            ok=False, action="open_url",
            execution_id=request.execution_id,
            error=reason,
            error_code=code,
        )

    try:
        emit_action_intent(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action="open_url",
            target=request.url,
        )
    except HostAuditError as exc:
        return HostActionResult(
            ok=False, action="open_url",
            execution_id=request.execution_id,
            error=f"intent audit failed — abort: {exc}",
            error_code=HostErrorCode.AUDIT_FAILURE,
        )

    # Windows: open URL without shell=True via rundll32
    subprocess.Popen(["rundll32.exe", "url.dll,FileProtocolHandler", request.url])

    emit_action_outcome(
        agent_id=HOST_AGENT_ID,
        execution_id=request.execution_id,
        action="open_url",
        target=request.url,
        result="opened",
        pid=None,  # rundll32 is ephemeral; no meaningful pid to track
    )

    return HostActionResult(
        ok=True, action="open_url",
        execution_id=request.execution_id,
    )


# ---------------------------------------------------------------------------
# Phase 3A — read-only filesystem handlers
# ---------------------------------------------------------------------------


def _handle_list_directory(request: HostActionRequest) -> HostActionResult:
    """
    list_directory: scan a permitted directory, return up to LIST_DIRECTORY_LIMIT entries.

    Validation order
    ----------------
    1. validate_allowed_directory → DIRECTORY_NOT_ALLOWED
    2. os.path.isdir              → DIRECTORY_NOT_FOUND
    3. emit_action_intent         → AUDIT_FAILURE aborts
    4. os.scandir (no-exec, no recursion)
    5. emit_action_outcome

    symlinks are reported as their apparent type (follow_symlinks=False so
    a symlink pointing outside the allowlist does not yield readable content).
    """
    ok, reason = validate_allowed_directory(request.path)
    if not ok:
        return HostActionResult(
            ok=False, action="list_directory",
            execution_id=request.execution_id,
            error=reason,
            error_code=HostErrorCode.DIRECTORY_NOT_ALLOWED,
        )

    norm_path = ntpath.normpath(request.path)

    if not os.path.isdir(norm_path):
        return HostActionResult(
            ok=False, action="list_directory",
            execution_id=request.execution_id,
            error=f"directory {request.path!r} does not exist",
            error_code=HostErrorCode.DIRECTORY_NOT_FOUND,
        )

    try:
        emit_action_intent(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action="list_directory",
            target=request.path,
        )
    except HostAuditError as exc:
        return HostActionResult(
            ok=False, action="list_directory",
            execution_id=request.execution_id,
            error=f"intent audit failed — abort: {exc}",
            error_code=HostErrorCode.AUDIT_FAILURE,
        )

    entries: list = []
    try:
        with os.scandir(norm_path) as it:
            for entry in it:
                if len(entries) >= LIST_DIRECTORY_LIMIT:
                    break
                is_dir = entry.is_dir(follow_symlinks=False)
                entry_type = "dir" if is_dir else "file"
                try:
                    size = entry.stat(follow_symlinks=False).st_size if not is_dir else None
                except OSError:
                    size = None
                extension = (
                    os.path.splitext(entry.name)[1].lower()
                    if not is_dir else None
                )
                entries.append({
                    "name":      entry.name,
                    "type":      entry_type,
                    "size":      size,
                    "extension": extension,
                })
    except OSError as exc:
        return HostActionResult(
            ok=False, action="list_directory",
            execution_id=request.execution_id,
            error=f"could not read directory: {exc}",
            error_code=HostErrorCode.DIRECTORY_NOT_FOUND,
        )

    emit_action_outcome(
        agent_id=HOST_AGENT_ID,
        execution_id=request.execution_id,
        action="list_directory",
        target=request.path,
        result=f"listed:{len(entries)}",
        pid=None,
    )

    return HostActionResult(
        ok=True, action="list_directory",
        execution_id=request.execution_id,
        entries=entries,
    )


def _handle_open_file(request: HostActionRequest) -> HostActionResult:
    """
    open_file: open a whitelisted file with its default application.

    Uses rundll32 url.dll,FileProtocolHandler — same pattern as open_url,
    no shell=True, no direct execution of the file bytes.

    Validation order
    ----------------
    1. validate_allowed_file_path → FILE_NOT_ALLOWED
    2. extension in ALLOWED_EXTENSIONS → EXTENSION_NOT_ALLOWED
    3. os.path.isfile              → FILE_NOT_FOUND
    4. emit_action_intent         → AUDIT_FAILURE aborts
    5. subprocess.Popen([rundll32, handler, path])
    6. emit_action_outcome

    rundll32 is ephemeral; pid is not tracked in _IN_FLIGHT.
    """
    ok, reason = validate_allowed_file_path(request.path)
    if not ok:
        return HostActionResult(
            ok=False, action="open_file",
            execution_id=request.execution_id,
            error=reason,
            error_code=HostErrorCode.FILE_NOT_ALLOWED,
        )

    ext = os.path.splitext(request.path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return HostActionResult(
            ok=False, action="open_file",
            execution_id=request.execution_id,
            error=f"extension {ext!r} is not in ALLOWED_EXTENSIONS",
            error_code=HostErrorCode.EXTENSION_NOT_ALLOWED,
        )

    norm_path = ntpath.normpath(request.path)

    if not os.path.isfile(norm_path):
        return HostActionResult(
            ok=False, action="open_file",
            execution_id=request.execution_id,
            error=f"file {request.path!r} does not exist",
            error_code=HostErrorCode.FILE_NOT_FOUND,
        )

    try:
        emit_action_intent(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action="open_file",
            target=request.path,
        )
    except HostAuditError as exc:
        return HostActionResult(
            ok=False, action="open_file",
            execution_id=request.execution_id,
            error=f"intent audit failed — abort: {exc}",
            error_code=HostErrorCode.AUDIT_FAILURE,
        )

    # Open via rundll32 — no shell=True, no direct execution of file bytes
    subprocess.Popen(["rundll32.exe", "url.dll,FileProtocolHandler", norm_path])

    emit_action_outcome(
        agent_id=HOST_AGENT_ID,
        execution_id=request.execution_id,
        action="open_file",
        target=request.path,
        result="opened",
        pid=None,  # rundll32 is ephemeral
    )

    return HostActionResult(
        ok=True, action="open_file",
        execution_id=request.execution_id,
    )


def _handle_read_text_file(request: HostActionRequest) -> HostActionResult:
    """
    read_text_file: read a small text file and return its content as a string.

    Validation order
    ----------------
    1. validate_allowed_file_path → FILE_NOT_ALLOWED
    2. extension in ALLOWED_EXTENSIONS → EXTENSION_NOT_ALLOWED
    3. os.path.isfile              → FILE_NOT_FOUND
    4. os.path.getsize ≤ MAX_READ_SIZE_BYTES → FILE_TOO_LARGE
    5. emit_action_intent         → AUDIT_FAILURE aborts
    6. open(utf-8)                → INVALID_ENCODING on UnicodeDecodeError
    7. emit_action_outcome

    No write, no exec.  Content never leaves the return value.
    """
    ok, reason = validate_allowed_file_path(request.path)
    if not ok:
        return HostActionResult(
            ok=False, action="read_text_file",
            execution_id=request.execution_id,
            error=reason,
            error_code=HostErrorCode.FILE_NOT_ALLOWED,
        )

    ext = os.path.splitext(request.path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return HostActionResult(
            ok=False, action="read_text_file",
            execution_id=request.execution_id,
            error=f"extension {ext!r} is not in ALLOWED_EXTENSIONS",
            error_code=HostErrorCode.EXTENSION_NOT_ALLOWED,
        )

    norm_path = ntpath.normpath(request.path)

    if not os.path.isfile(norm_path):
        return HostActionResult(
            ok=False, action="read_text_file",
            execution_id=request.execution_id,
            error=f"file {request.path!r} does not exist",
            error_code=HostErrorCode.FILE_NOT_FOUND,
        )

    try:
        size = os.path.getsize(norm_path)
    except OSError as exc:
        return HostActionResult(
            ok=False, action="read_text_file",
            execution_id=request.execution_id,
            error=f"could not stat file: {exc}",
            error_code=HostErrorCode.FILE_NOT_FOUND,
        )

    if size > MAX_READ_SIZE_BYTES:
        return HostActionResult(
            ok=False, action="read_text_file",
            execution_id=request.execution_id,
            error=(
                f"file size {size} bytes exceeds MAX_READ_SIZE_BYTES "
                f"({MAX_READ_SIZE_BYTES})"
            ),
            error_code=HostErrorCode.FILE_TOO_LARGE,
        )

    try:
        emit_action_intent(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action="read_text_file",
            target=request.path,
        )
    except HostAuditError as exc:
        return HostActionResult(
            ok=False, action="read_text_file",
            execution_id=request.execution_id,
            error=f"intent audit failed — abort: {exc}",
            error_code=HostErrorCode.AUDIT_FAILURE,
        )

    try:
        with open(norm_path, encoding="utf-8") as fh:
            content = fh.read()
    except UnicodeDecodeError as exc:
        emit_action_outcome(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action="read_text_file",
            target=request.path,
            result="encoding_error",
            pid=None,
        )
        return HostActionResult(
            ok=False, action="read_text_file",
            execution_id=request.execution_id,
            error=f"file is not valid utf-8: {exc}",
            error_code=HostErrorCode.INVALID_ENCODING,
        )

    emit_action_outcome(
        agent_id=HOST_AGENT_ID,
        execution_id=request.execution_id,
        action="read_text_file",
        target=request.path,
        result="read",
        pid=None,
    )

    return HostActionResult(
        ok=True, action="read_text_file",
        execution_id=request.execution_id,
        content=content,
    )


# ---------------------------------------------------------------------------
# Public executor — dispatcher
# ---------------------------------------------------------------------------

_ACTION_HANDLERS = {
    "open_app":        _handle_open_app,
    "close_pid":       _handle_close_pid,
    "open_directory":  _handle_open_directory,
    "open_url":        _handle_open_url,
    # Phase 3A — read-only filesystem
    "list_directory":  _handle_list_directory,
    "open_file":       _handle_open_file,
    "read_text_file":  _handle_read_text_file,
}


def execute_host_action(request: HostActionRequest) -> HostActionResult:
    """
    Execute a host action under strict control.

    Gates (checked in order, all actions):
      Gate 1 — confirmed must be True
      Gate 2 — HOST_AGENT_ID must be ACTIVE in control_plane
      Gate 3 — rate limit not exceeded (action-specific)

    Gate rejections emit HostRejectionEvent (best-effort audit).
    Per-action validation and audit are in the individual handlers.
    Returns HostActionResult — never raises.

    Identity: always operates under HOST_AGENT_ID = "host_launcher".
    """

    # --- Gate 1: confirmed ---
    if not request.confirmed:
        reason = "execution requires confirmed=True"
        emit_host_rejection(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action=request.action,
            reason=reason,
            error_code=HostErrorCode.CONFIRMED_REQUIRED,
        )
        return HostActionResult(
            ok=False, action=request.action,
            execution_id=request.execution_id,
            app_name=request.app_name,
            error=reason,
            error_code=HostErrorCode.CONFIRMED_REQUIRED,
        )

    # --- Gate 2: HOST_AGENT_ID must be ACTIVE ---
    status = get_agent_status(HOST_AGENT_ID)
    if status != AgentStatus.ACTIVE:
        reason = f"agent {HOST_AGENT_ID!r} is not ACTIVE (status={status.value})"
        emit_host_rejection(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action=request.action,
            reason=reason,
            error_code=HostErrorCode.CONTROL_PLANE_BLOCKED,
        )
        return HostActionResult(
            ok=False, action=request.action,
            execution_id=request.execution_id,
            app_name=request.app_name,
            error=reason,
            error_code=HostErrorCode.CONTROL_PLANE_BLOCKED,
        )

    # --- Gate 3: rate limit ---
    rate_ok, rate_reason = _check_rate_limit(request.action)
    if not rate_ok:
        emit_host_rejection(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action=request.action,
            reason=rate_reason,
            error_code=HostErrorCode.RATE_LIMIT_EXCEEDED,
        )
        return HostActionResult(
            ok=False, action=request.action,
            execution_id=request.execution_id,
            app_name=request.app_name,
            error=rate_reason,
            error_code=HostErrorCode.RATE_LIMIT_EXCEEDED,
        )

    # --- Dispatch ---
    handler = _ACTION_HANDLERS.get(request.action)
    if handler is None:
        reason = f"unknown action {request.action!r}"
        emit_host_rejection(
            agent_id=HOST_AGENT_ID,
            execution_id=request.execution_id,
            action=request.action,
            reason=reason,
            error_code=HostErrorCode.UNKNOWN_ACTION,
        )
        return HostActionResult(
            ok=False, action=request.action,
            execution_id=request.execution_id,
            error=reason,
            error_code=HostErrorCode.UNKNOWN_ACTION,
        )

    return handler(request)


# ---------------------------------------------------------------------------
# Test helper — NOT for production use
# ---------------------------------------------------------------------------


def _reset_host_agent_state_for_tests() -> None:
    """
    Clear rate-limit timestamps.  ONLY for use in test teardown/setup.
    Must be called alongside control_plane._reset_state_for_tests() and
    HOST_AUDIT_LOG.clear() for full isolation.
    """
    with _rate_lock:
        _action_timestamps.clear()
