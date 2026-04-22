"""Interim best-effort audit emission for OpenClaw backend."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_AUDIT_FILE = Path(__file__).resolve().parents[2] / "logs" / "openclaw_audit.ndjson"


def emit_audit_event(event: dict[str, Any]) -> None:
    """Append one audit event as a JSON line; never raise to callers."""
    try:
        _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(event)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with _AUDIT_FILE.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line)
            handle.write("\n")
    except Exception:
        return
