"""Configuration for the dedicated OpenClaw backend ingress service."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass

OPENCLAW_BACKEND_HOST: str = os.environ.get("OPENCLAW_BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
OPENCLAW_BACKEND_PORT: int = int(os.environ.get("OPENCLAW_BACKEND_PORT", "18790"))

OPENCLAW_AUTH_HEADER_NAME: str = os.environ.get("OPENCLAW_AUTH_HEADER_NAME", "X-OpenClaw-Token").strip()
OPENCLAW_EXPECTED_AUTH_TOKEN: str = (
    os.environ.get("OPENCLAW_EXPECTED_AUTH_TOKEN")
    or os.environ.get("WEBHOOK_TOKEN")
    or ""
).strip()
OPENCLAW_LOG_LEVEL: str = os.environ.get("OPENCLAW_LOG_LEVEL", "INFO").strip().upper() or "INFO"

# Runtime binding is intentionally optional for this sprint; when disabled,
# execution requests fail explicitly with runtime_unavailable.
OPENCLAW_RUNTIME_ENABLED: bool = os.environ.get("OPENCLAW_RUNTIME_ENABLED", "false").strip().lower() == "true"

SERVICE_VERSION: str = os.environ.get("OPENCLAW_BACKEND_VERSION", "b1")

# Startup preflight policy: fail startup if backend is alive but not execution-ready.
OPENCLAW_STARTUP_REQUIRE_READY: bool = (
    os.environ.get("OPENCLAW_STARTUP_REQUIRE_READY", "true").strip().lower() == "true"
)

# Evidence hygiene configuration.
_OPENCLAW_EVIDENCE_DIR_RAW: str = os.environ.get("OPENCLAW_EVIDENCE_DIR", "").strip()
OPENCLAW_EVIDENCE_DIR: Path = (
    Path(_OPENCLAW_EVIDENCE_DIR_RAW).expanduser()
    if _OPENCLAW_EVIDENCE_DIR_RAW
    else (Path(tempfile.gettempdir()) / "openclaw_backend_evidence")
)
OPENCLAW_EVIDENCE_MAX_FILES: int = int(os.environ.get("OPENCLAW_EVIDENCE_MAX_FILES", "500"))
OPENCLAW_EVIDENCE_MAX_AGE_SECONDS: int = int(os.environ.get("OPENCLAW_EVIDENCE_MAX_AGE_SECONDS", "604800"))


def get_auth_config_error() -> str | None:
    """Return configuration error string, or None when auth config is valid."""
    if not OPENCLAW_AUTH_HEADER_NAME:
        return "OPENCLAW_AUTH_HEADER_NAME is required"
    if not OPENCLAW_EXPECTED_AUTH_TOKEN:
        return "OPENCLAW_EXPECTED_AUTH_TOKEN is required"
    return None
