"""Startup preflight helper for OpenClaw backend operability checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import config
from .runtime import create_default_runtime_dispatcher


def _python_env_ready() -> bool:
    executable = (sys.executable or "").strip()
    if not executable:
        return False
    path = Path(executable)
    return path.exists() and path.is_file()


def collect_preflight_report(require_ready: bool = True) -> dict[str, Any]:
    dispatcher = create_default_runtime_dispatcher()
    try:
        readiness = dispatcher.readiness()
        python_env_ready = _python_env_ready()
        auth_error = config.get_auth_config_error()
        errors: list[str] = []
        if not python_env_ready:
            errors.append("python environment is not ready")
        if auth_error:
            errors.append(auth_error)
        if require_ready and not readiness.get("runtime_usable", False):
            errors.append("runtime is not ready")
        return {
            "ok": not errors,
            "require_ready": require_ready,
            "python_executable": sys.executable,
            "python_env_ready": python_env_ready,
            "auth_configured": auth_error is None,
            "auth_error": auth_error,
            "errors": errors,
            **readiness,
        }
    finally:
        dispatcher.close_all()


def run_preflight(require_ready: bool = True) -> int:
    report = collect_preflight_report(require_ready=require_ready)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def main() -> None:
    code = run_preflight(require_ready=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
