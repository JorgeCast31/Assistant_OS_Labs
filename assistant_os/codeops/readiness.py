"""CODE domain readiness facade — read-only, fail-soft observability.

This module produces a non-authoritative ``CodeReadinessSummary`` that aggregates:

  * Code API transport reachability (lightweight probe of ``/health``).
  * Apply mode (from ``APPLY_EXECUTION_MODE`` config).
  * Runner backend availability (Docker daemon **ping only**, and ONLY when
    apply mode is ``"real"``).
  * Runner config echo (timeouts, resource limits, base image).
  * CODE-domain capability records from ``mso.capability_registry``.

INVARIANTS — never violated by this module
------------------------------------------
- ``get_code_readiness()`` does NOT execute code, run containers, or apply
  changes.
- ``get_code_readiness()`` does NOT call kernel, router, agents, or pipelines.
- ``get_code_readiness()`` does NOT mutate any state.
- The Docker probe NEVER instantiates a container — it uses ``docker info``
  only and runs with a tight timeout.
- When ``APPLY_EXECUTION_MODE`` is ``"stub"`` (default), the Docker probe is
  NOT invoked at all.
- All probes are fail-soft: they return structured failure, never raise.
- Output is JSON-serializable.
- Output never includes ``execution_mode``, ``GovernanceVerdict``, or
  ``PolicyDecision``.

This is observability, not authority. MSO remains the only source of authority.
"""

from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional, TypedDict


# ---------------------------------------------------------------------------
# Public contract
# ---------------------------------------------------------------------------

class CodeReadinessSummary(TypedDict, total=False):
    """Read-only readiness snapshot for the CODE domain.

    All fields are optional (``total=False``); a partial snapshot is valid
    when individual probes fail.  No field of this contract carries authority.
    """

    # Identity / metadata
    domain: str                              # always "CODE"
    feature_enabled: bool                    # CODE domain is always available
    last_health_check: str                   # ISO 8601 UTC
    note: str                                # invariant disclaimer

    # Code API transport
    code_api_reachable: bool
    code_api_url: str
    code_api_latency_ms: int
    code_api_error: Optional[str]

    # Apply mode (config-derived)
    apply_execution_mode: str                # "stub" | "real"
    apply_real_enabled: bool                 # mode == "real"

    # Runner backend (Docker daemon, ping-only)
    runner_backend_probed: bool              # True iff probe was attempted
    runner_backend_available: Optional[bool] # None when not probed
    runner_backend_latency_ms: Optional[int]
    runner_backend_error: Optional[str]

    # Runner config (read-only echo)
    runner_timeout_seconds: int
    runner_memory_limit: str
    runner_cpu_limit: str
    runner_base_image: str

    # CODE capabilities
    code_capabilities: list[dict[str, Any]]
    code_capability_allowed_count: int
    code_capability_confirm_only_count: int
    code_capability_blocked_count: int


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_NOTE = (
    "Readiness reflects source availability and configuration only — "
    "it is not authority. Capabilities are governed by MSO."
)

# Probe timeouts.  Kept tight so readiness never stalls callers.
_CODE_API_PROBE_TIMEOUT_S: float = 1.0
_RUNNER_PROBE_TIMEOUT_S: float = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open_url(url: str, timeout: float):
    """Thin wrapper around urllib.request.urlopen so tests can patch."""
    return urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 — local probe


def _get_apply_mode() -> str:
    """Return the current APPLY_EXECUTION_MODE from config.  Read each call."""
    from .. import config as _cfg
    mode = getattr(_cfg, "APPLY_EXECUTION_MODE", "stub")
    return mode if mode in ("stub", "real") else "stub"


def _get_code_api_url() -> str:
    """Build the Code API health-probe URL from configured port."""
    import os
    port = os.environ.get("CODE_API_PORT", "8000")
    return f"http://127.0.0.1:{port}/health"


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

def _probe_code_api() -> tuple[bool, int, Optional[str]]:
    """Probe the Code API ``/health`` endpoint.

    Returns ``(reachable, latency_ms, error_or_None)``.  Never raises.
    """
    url = _get_code_api_url()
    started = time.monotonic()
    try:
        with _open_url(url, _CODE_API_PROBE_TIMEOUT_S) as resp:
            status = getattr(resp, "status", None) or getattr(resp, "code", None)
            try:
                resp.read()  # drain so the connection can be released cleanly
            except Exception:  # noqa: BLE001
                pass
        latency = int((time.monotonic() - started) * 1000)
        if status is not None and 200 <= int(status) < 300:
            return True, latency, None
        return False, latency, f"unexpected status {status}"
    except urllib.error.URLError as exc:
        return False, 0, f"URLError: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return False, 0, f"{type(exc).__name__}: {exc}"


def _probe_runner_backend() -> tuple[bool, int, Optional[str]]:
    """Ping the Docker daemon — read-only, never instantiates a container.

    Uses ``docker info --format '{{.ServerVersion}}'`` with a tight timeout.
    Returns ``(available, latency_ms, error_or_None)``.  Never raises.

    NOTE: callers must only invoke this when ``APPLY_EXECUTION_MODE == 'real'``.
    """
    cmd = ["docker", "info", "--format", "{{.ServerVersion}}"]
    started = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_RUNNER_PROBE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, 0, "timeout while probing docker daemon"
    except FileNotFoundError as exc:
        return False, 0, f"docker CLI not found: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, 0, f"{type(exc).__name__}: {exc}"

    latency = int((time.monotonic() - started) * 1000)
    if result.returncode == 0:
        return True, latency, None
    err = (result.stderr or result.stdout or "").strip() or "non-zero exit"
    return False, latency, f"docker info failed: {err}"


# ---------------------------------------------------------------------------
# Capability summary
# ---------------------------------------------------------------------------

def _summarize_code_capabilities() -> list[dict[str, Any]]:
    """Return a list of CODE-domain capability records as plain dicts.

    Reads from :mod:`mso.capability_registry` — does not invent capabilities.
    """
    from ..mso.capability_registry import list_registered_capabilities
    summary: list[dict[str, Any]] = []
    for record in list_registered_capabilities():
        domain = getattr(record, "domain", None)
        if domain != "CODE":
            continue
        summary.append({
            "action": getattr(record, "action", None),
            "domain": domain,
            "mode": getattr(record, "mode", None),
            "allowed": bool(getattr(record, "allowed", True)),
            "notes": getattr(record, "notes", "") or "",
        })
    return summary


def _count_capabilities(caps: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Return (allowed, confirm_only, blocked) counts derived from caps."""
    allowed = 0
    confirm_only = 0
    blocked = 0
    for cap in caps:
        mode = cap.get("mode")
        is_allowed = bool(cap.get("allowed", True))
        if mode == "deny" or not is_allowed:
            blocked += 1
        elif mode == "confirm_only":
            confirm_only += 1
        elif mode == "allow":
            allowed += 1
        # plan_only or unknown modes are not counted in any bucket.
    return allowed, confirm_only, blocked


# ---------------------------------------------------------------------------
# Public producer
# ---------------------------------------------------------------------------

def get_code_readiness() -> CodeReadinessSummary:
    """Return a read-only, fail-soft readiness snapshot for the CODE domain.

    Never raises.  If a probe or registry read fails, the corresponding field
    surfaces a structured failure (false / None / error string).
    """
    from .. import config as _cfg

    summary: CodeReadinessSummary = {
        "domain": "CODE",
        "feature_enabled": True,
        "last_health_check": _now_iso(),
        "note": _NOTE,
    }

    # --- Apply mode (config) ---
    try:
        apply_mode = _get_apply_mode()
    except Exception as exc:  # noqa: BLE001
        apply_mode = "stub"
        summary["apply_execution_mode"] = apply_mode
        summary["apply_real_enabled"] = False
        # Fall through; runner probe will be skipped.
    else:
        summary["apply_execution_mode"] = apply_mode
        summary["apply_real_enabled"] = (apply_mode == "real")

    # --- Code API probe (always attempted, fail-soft) ---
    try:
        url = _get_code_api_url()
    except Exception:  # noqa: BLE001
        url = ""
    summary["code_api_url"] = url
    try:
        reachable, latency, err = _probe_code_api()
    except Exception as exc:  # noqa: BLE001
        # _probe_code_api should not raise, but we defend in depth.
        reachable, latency, err = False, 0, f"probe crashed: {exc}"
    summary["code_api_reachable"] = reachable
    summary["code_api_latency_ms"] = latency
    summary["code_api_error"] = err

    # --- Runner backend probe (only when apply_mode == 'real') ---
    if summary.get("apply_real_enabled"):
        try:
            available, runner_latency, runner_err = _probe_runner_backend()
        except Exception as exc:  # noqa: BLE001
            available, runner_latency, runner_err = False, 0, f"probe crashed: {exc}"
        summary["runner_backend_probed"] = True
        summary["runner_backend_available"] = available
        summary["runner_backend_latency_ms"] = runner_latency
        summary["runner_backend_error"] = runner_err
    else:
        summary["runner_backend_probed"] = False
        summary["runner_backend_available"] = None
        summary["runner_backend_latency_ms"] = None
        summary["runner_backend_error"] = (
            "probe skipped: APPLY_EXECUTION_MODE is 'stub' (no docker probe in stub mode)"
        )

    # --- Runner config echo (read-only) ---
    summary["runner_timeout_seconds"] = int(getattr(_cfg, "RUNNER_TIMEOUT_SECONDS", 0) or 0)
    summary["runner_memory_limit"] = str(getattr(_cfg, "RUNNER_MEMORY_LIMIT", "") or "")
    summary["runner_cpu_limit"] = str(getattr(_cfg, "RUNNER_CPU_LIMIT", "") or "")
    summary["runner_base_image"] = str(getattr(_cfg, "RUNNER_BASE_IMAGE", "") or "")

    # --- CODE capabilities (registry-derived) ---
    try:
        caps = _summarize_code_capabilities()
    except Exception:  # noqa: BLE001
        caps = []
    summary["code_capabilities"] = caps
    allowed, confirm, blocked = _count_capabilities(caps)
    summary["code_capability_allowed_count"] = allowed
    summary["code_capability_confirm_only_count"] = confirm
    summary["code_capability_blocked_count"] = blocked

    return summary


__all__ = [
    "CodeReadinessSummary",
    "get_code_readiness",
]
