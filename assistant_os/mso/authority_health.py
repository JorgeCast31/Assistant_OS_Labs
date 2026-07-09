"""Authority / Health Surface v0 — read-only, fail-soft readiness aggregator.

PR: Authority/Health Surface v0 (MSO AMBER-GO).

WHAT THIS IS: a single, observational snapshot that composes readiness signals
that already exist (authority status, police readiness, confirm-flow queue,
operational mode, capability path presence) into one structured JSON answer to:
"Is the system ready to act sovereignly, and if not, why not?"

WHAT THIS IS NOT: this module grants NO authority and performs NO execution.
It only reads.

INVARIANTS:
- get_authority_health_snapshot() NEVER executes, issues/consumes an action
  token, calls the Runner, mutates a store, or changes operational mode.
- Output ALWAYS carries can_execute_now/execution_allowed/authority_granted =
  False. This surface cannot flip them.
- Output NEVER contains secrets or env-var values — only NAME + presence bool.
- Every probe is fail-soft: an error yields NO_VERIFICADO, never a raise, never
  a silent GO.
- A missing/broken critical capability (Police, policy, capability path) can
  never be reported as GO.
- Output is JSON-serializable.

STATUS LEGEND: GO=verified present/healthy; AMBER=present-but-limited or
intentionally-not-enabled (safe); STOP=dangerous, must not proceed;
NO_VERIFICADO=could not be verified (never treated as GO).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

GO = "GO"
AMBER = "AMBER"
STOP = "STOP"
NO_VERIFICADO = "NO_VERIFICADO"

_VALID_STATUSES = (GO, AMBER, STOP, NO_VERIFICADO)

# Env var NAMES we report presence for (NEVER their values).
_ENV_NAMES_REPORTED = (
    "ANTHROPIC_API_KEY",
    "MSO_ENABLED",
    "MSO_SEAT_PROVIDER",
    "MSO_SEAT_MODEL",
    "ASSISTANT_LOCAL_LLM_ENABLED",
    "ASSISTANT_BUILD",
    "ASSISTANT_COMMIT",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(name: str, status: str, detail: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if status not in _VALID_STATUSES:
        status = NO_VERIFICADO
    row: dict[str, Any] = {"check": name, "status": status, "detail": detail}
    if extra:
        row["extra"] = extra
    return row


def _module_importable(dotted: str, attrs: tuple[str, ...] = ()) -> tuple[bool, str | None]:
    """Return (importable, error). Reports presence only."""
    try:
        import importlib

        mod = importlib.import_module(dotted)
        for a in attrs:
            if not hasattr(mod, a):
                return False, f"missing attribute: {a}"
        return True, None
    except Exception as exc:  # noqa: BLE001 fail-soft
        return False, f"{type(exc).__name__}: {exc}"


def _safe_call(fn: Callable[[], Any]) -> tuple[Any, str | None]:
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001 fail-soft
        return None, f"{type(exc).__name__}: {exc}"


def probe_operational_mode() -> dict[str, Any]:
    """Read-only operational mode / observer posture. Mode != MSO ACTIVE."""
    def _read() -> dict[str, Any]:
        from . import system_state as _ss

        mode, reason = _ss.get_operational_mode_override()
        return {"operational_mode": (mode or "NORMAL"), "reason": reason or ""}

    data, err = _safe_call(_read)
    if err is not None:
        return _check("operational_mode", NO_VERIFICADO,
                      f"Could not read operational mode: {err}")
    return _check("operational_mode", GO,
                  "Operational mode readable (observational). Mode is not MSO-active authority.",
                  extra=data)


def probe_police_available() -> dict[str, Any]:
    """CRITICAL: Police/Governor enforcement must be importable and wired."""
    ok, err = _module_importable("assistant_os.police.enforcement", ("check",))
    if ok:
        return _check("police_available", GO,
                      "police.enforcement.check present (enforcement wired).")
    return _check("police_available", STOP,
                  f"Police enforcement NOT available; sovereign execution must not proceed. {err or ''}".strip())


def probe_policy_enforcement() -> dict[str, Any]:
    """CRITICAL: deterministic policy engine must be importable."""
    ok, err = _module_importable("assistant_os.policy.policy_engine", ("evaluate_policy",))
    if ok:
        return _check("policy_enforcement", GO,
                      "policy_engine.evaluate_policy present (policy path wired).")
    return _check("policy_enforcement", STOP,
                  f"Policy enforcement NOT available. {err or ''}".strip())


def probe_capability_path() -> dict[str, Any]:
    """CRITICAL: capability token issue+verify path must be importable."""
    ok_i, err_i = _module_importable("assistant_os.capabilities.token_issuer", ("issue_token",))
    ok_v, err_v = _module_importable("assistant_os.capabilities.token_verifier",
                                     ("verify_token", "consume_token"))
    if ok_i and ok_v:
        return _check("capability_path", GO,
                      "Capability token issue+verify+consume path present (single-use tokens).")
    detail = "Capability path incomplete: " + "; ".join(
        x for x in (err_i and f"issuer:{err_i}", err_v and f"verifier:{err_v}") if x
    )
    return _check("capability_path", STOP, detail or "Capability path unavailable.")


def probe_authority_status() -> dict[str, Any]:
    """Embed the existing authority status summary (fail-soft)."""
    def _read() -> Any:
        from . import authority_status as _as

        return _as.get_authority_status()

    data, err = _safe_call(_read)
    if err is not None:
        return _check("authority_status", NO_VERIFICADO,
                      f"authority_status probe failed: {err}")
    return _check("authority_status", GO,
                  "Authority status summary readable.",
                  extra={"summary": data})


def probe_police_readiness() -> dict[str, Any]:
    """Embed a compact police-readiness summary (fail-soft)."""
    def _read() -> Any:
        from . import police_readiness as _pr

        recent = _pr.list_recent_police_readiness_reports(limit=50)
        items = [r.to_dict() if hasattr(r, "to_dict") else r for r in recent]
        return _pr.build_readiness_summary(items)

    data, err = _safe_call(_read)
    if err is not None:
        return _check("police_readiness", NO_VERIFICADO,
                      f"police_readiness probe failed: {err}")
    return _check("police_readiness", GO,
                  "Police readiness summary readable (observational).",
                  extra={"summary": data})


def probe_confirm_flow() -> dict[str, Any]:
    """Embed the confirm-flow queue summary (fail-soft)."""
    def _read() -> Any:
        from ..confirm_flow import readiness as _cf

        return _cf.get_confirm_flow_summary(limit=5)

    data, err = _safe_call(_read)
    if err is not None:
        return _check("confirm_flow_queue", NO_VERIFICADO,
                      f"confirm_flow probe failed: {err}")
    return _check("confirm_flow_queue", GO,
                  "Confirm-flow queue readable (observability, not authority).",
                  extra={"summary": data})


def probe_runner() -> dict[str, Any]:
    """Runner execution is intentionally NOT enabled. Report blocked (safe/AMBER)."""
    importable, _err = _module_importable("assistant_os.runners.runner_service")
    return _check("runner_execution", AMBER,
                  "Runner execution is NOT enabled (blocked by design). "
                  "No autonomous execution path is authorized from this surface.",
                  extra={"runner_module_importable": bool(importable),
                         "runner_available_for_execution": False})


def probe_durable_queue() -> dict[str, Any]:
    """No durable mission queue/scheduler. Report absent (AMBER, expected)."""
    return _check("durable_queue", AMBER,
                  "No durable mission queue/scheduler. Runtime registries are "
                  "in-memory (process-local) and do not survive restarts.",
                  extra={"durable_queue_present": False})


def probe_backend_identity() -> dict[str, Any]:
    """What backend does this process believe it is? Build/commit best-effort."""
    build = os.environ.get("ASSISTANT_BUILD")
    commit = os.environ.get("ASSISTANT_COMMIT")
    if build or commit:
        return _check("backend_identity", GO,
                      "Backend build/commit reported via environment.",
                      extra={"build": build or None, "commit": commit or None,
                             "backend_service": "assistant_os.webhook_server"})
    # Build stamp unset is a benign, EXPECTED absence (not an un-probeable
    # authority signal). Report AMBER so it does not drag overall to
    # NO_VERIFICADO; NO_VERIFICADO is reserved for genuinely un-probeable
    # signals. Populating ASSISTANT_BUILD/ASSISTANT_COMMIT promotes to GO.
    return _check("backend_identity", AMBER,
                  "Build identity not stamped (ASSISTANT_BUILD / ASSISTANT_COMMIT "
                  "unset). Expected until wired; not an authority signal.",
                  extra={"backend_service": "assistant_os.webhook_server",
                         "build": None, "commit": None})


def probe_backend_deploy() -> dict[str, Any]:
    """Backend deploy is not enabled; UI is observational. AMBER (expected)."""
    return _check("backend_deploy", AMBER,
                  "Backend deploy is NOT enabled. The Next.js UI is observational; "
                  "server-side proxies fail-closed to 'unavailable' when no local "
                  "backend is reachable.",
                  extra={"backend_deploy_enabled": False})


_DEFAULT_PROBES: tuple[Callable[[], dict[str, Any]], ...] = (
    probe_operational_mode,
    probe_police_available,
    probe_policy_enforcement,
    probe_capability_path,
    probe_authority_status,
    probe_police_readiness,
    probe_confirm_flow,
    probe_runner,
    probe_durable_queue,
    probe_backend_identity,
    probe_backend_deploy,
)

# Checks that must NEVER be silently GO when missing.
_CRITICAL_CHECKS = ("police_available", "policy_enforcement", "capability_path")


def _env_presence() -> dict[str, bool]:
    """Report presence-only for a fixed set of env NAMES. Never emits values."""
    return {name: (os.environ.get(name) not in (None, "")) for name in _ENV_NAMES_REPORTED}


def _overall(checks: list[dict[str, Any]]) -> str:
    statuses = {c.get("status") for c in checks}
    if STOP in statuses:
        return STOP
    for c in checks:
        if c.get("check") in _CRITICAL_CHECKS and c.get("status") != GO:
            return NO_VERIFICADO
    if NO_VERIFICADO in statuses:
        return NO_VERIFICADO
    if AMBER in statuses:
        return AMBER
    return GO


def get_authority_health_snapshot(
    *, probes: tuple[Callable[[], dict[str, Any]], ...] | None = None
) -> dict[str, Any]:
    """Return a read-only, fail-soft Authority/Health snapshot.

    Never raises. Never grants authority. can_execute_now is always False.
    """
    probe_fns = probes if probes is not None else _DEFAULT_PROBES

    checks: list[dict[str, Any]] = []
    for fn in probe_fns:
        try:
            row = fn()
            if not isinstance(row, dict) or "status" not in row:
                row = _check(getattr(fn, "__name__", "unknown_probe"),
                             NO_VERIFICADO, "probe returned malformed result")
            if row.get("status") not in _VALID_STATUSES:
                row["status"] = NO_VERIFICADO
            checks.append(row)
        except Exception as exc:  # noqa: BLE001 a probe must never break the surface
            checks.append(_check(getattr(fn, "__name__", "unknown_probe"),
                                 NO_VERIFICADO,
                                 f"probe raised: {type(exc).__name__}: {exc}"))

    overall = _overall(checks)

    blockers = [{"check": c["check"], "detail": c["detail"]}
                for c in checks if c.get("status") == STOP]
    warnings = [{"check": c["check"], "detail": c["detail"]}
                for c in checks if c.get("status") in (AMBER, NO_VERIFICADO)]

    snapshot: dict[str, Any] = {
        "surface": "authority_health",
        "version": "v0",
        "generated_at": _now_iso(),
        "note": ("Observational readiness surface. Grants no authority and "
                 "performs no execution. Readiness is not authority."),
        "overall": overall,
        "status_legend": {
            "GO": "verified present / healthy",
            "AMBER": "present-but-limited or intentionally-not-enabled (safe)",
            "STOP": "dangerous condition; must not proceed",
            "NO_VERIFICADO": "could not be verified; never treated as GO",
        },
        "authority_granted": False,
        "execution_allowed": False,
        "can_execute_now": False,
        "read_only": True,
        "observer": True,
        "runner_available": False,
        "durable_queue_present": False,
        "backend_deploy_enabled": False,
        "ui_is_observational": True,
        "env_presence": _env_presence(),
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
    }
    return snapshot


__all__ = [
    "GO",
    "AMBER",
    "STOP",
    "NO_VERIFICADO",
    "get_authority_health_snapshot",
]
