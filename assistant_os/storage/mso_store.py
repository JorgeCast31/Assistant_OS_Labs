"""Persistent store for sovereign and cognitive execution artifacts."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any

from ..config import MEMORY_DIR
from ..contracts import now_iso

# Production default. Never changes at runtime.
MSO_STORE_ROOT: Path = MEMORY_DIR / "mso_store"

_MSO_STORE_ROOT_ENV = "ASSISTANT_OS_MSO_STORE_ROOT"

# Subdirectory names for each entity kind (relative to the store root).
_ENTITY_KIND_SUBDIRS: dict[str, str] = {
    "cycles": "cycles",
    "translator_rejections": "translator_rejections",
    "intents": "intents",
    "delegations": "delegations",
    "capabilities": "capabilities",
    "reports": "reports",
    "escalations": "escalations",
    "worker_security_events": "worker_security_events",
    "security_responses": "security_responses",
    "restrictions": "restrictions",
    "operator_actions": "operator_actions",
    "operator_tokens": "operator_tokens",
    "control_plane_bootstrap": "control_plane_bootstrap",
    "control_plane_maintenance": "control_plane_maintenance",
    "control_plane_signals": "control_plane_signals",
}

_lock = RLock()


def get_mso_store_root() -> Path:
    """Return the active mso_store root.

    Reads ASSISTANT_OS_MSO_STORE_ROOT from the environment if set; otherwise
    returns the production default (MSO_STORE_ROOT). No caching — safe to call
    after os.environ is patched in tests.
    """
    env_val = os.environ.get(_MSO_STORE_ROOT_ENV, "").strip()
    if env_val:
        return Path(env_val)
    return MSO_STORE_ROOT


def _get_entity_dirs() -> dict[str, Path]:
    """Return entity-kind → directory mapping for the current store root."""
    root = get_mso_store_root()
    return {kind: root / subdir for kind, subdir in _ENTITY_KIND_SUBDIRS.items()}


_RETENTION_DAYS = {
    "cycles": 30,
    "translator_rejections": 30,
    "intents": 30,
    "delegations": 14,
    "capabilities": 14,
    "reports": 14,
    "escalations": 30,
    "worker_security_events": 30,
    "security_responses": 30,
    "restrictions": 45,
    "operator_actions": 45,
    "operator_tokens": 30,
    "control_plane_bootstrap": 90,
    "control_plane_maintenance": 45,
    "control_plane_signals": 45,
}
_last_cleanup_at = ""


def _ensure_dirs() -> None:
    for path in _get_entity_dirs().values():
        path.mkdir(parents=True, exist_ok=True)


def _payload(obj: Any) -> dict[str, Any]:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return dict(obj)
    raise TypeError(f"Unsupported MSO store payload type: {type(obj).__name__}")


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_record_id(kind: str, data: dict[str, Any]) -> str:
    keys = {
        "cycles": "cycle_id",
        "translator_rejections": "rejection_id",
        "intents": "intent_id",
        "delegations": "task_id",
        "capabilities": "capability_id",
        "reports": "report_id",
        "escalations": "escalation_id",
        "worker_security_events": "event_id",
        "security_responses": "response_id",
        "restrictions": "restriction_id",
        "operator_actions": "action_id",
        "operator_tokens": "token_id",
        "control_plane_bootstrap": "bootstrap_id",
        "control_plane_maintenance": "action_id",
        "control_plane_signals": "signal_id",
    }
    return str(data.get(keys[kind], ""))


def _extract_trace_id(kind: str, data: dict[str, Any]) -> str:
    if kind == "intents":
        return f"intent:{data.get('intent_id', '')}"
    return str(data.get("trace_id", ""))


def _extract_source_timestamp(kind: str, data: dict[str, Any]) -> str:
    keys = {
        "cycles": "created_at",
        "translator_rejections": "created_at",
        "intents": "timestamp",
        "delegations": "expiry",
        "capabilities": "issued_at",
        "reports": "completed_at",
        "escalations": "timestamp",
        "worker_security_events": "created_at",
        "security_responses": "created_at",
        "restrictions": "created_at",
        "operator_actions": "timestamp",
        "operator_tokens": "issued_at",
        "control_plane_bootstrap": "created_at",
        "control_plane_maintenance": "created_at",
        "control_plane_signals": "created_at",
    }
    return str(data.get(keys[kind], "")) or now_iso()


def _compute_retention_until(kind: str, data: dict[str, Any], *, stored_at: str) -> str:
    expiry_key = {
        "delegations": "expiry",
        "capabilities": "expires_at",
    }.get(kind, "")
    if expiry_key and data.get(expiry_key):
        return str(data[expiry_key])
    base = _parse_iso(stored_at) or _now_dt()
    return (base + timedelta(days=_RETENTION_DAYS[kind])).isoformat()


def _record_envelope(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    stored_at = now_iso()
    record_id = _extract_record_id(kind, data)
    return {
        "_meta": {
            "kind": kind,
            "record_id": record_id,
            "trace_id": _extract_trace_id(kind, data),
            "stored_at": stored_at,
            "source_timestamp": _extract_source_timestamp(kind, data),
            "retention_until": _compute_retention_until(kind, data, stored_at=stored_at),
        },
        "payload": data,
    }


def _write_record(kind: str, record_id: str, obj: Any) -> str:
    _ensure_dirs()
    safe_record_id = re.sub(r'[^A-Za-z0-9._-]+', "_", record_id).strip("._") or "record"
    path = _get_entity_dirs()[kind] / f"{safe_record_id}.json"
    envelope = _record_envelope(kind, _payload(obj))
    with _lock:
        path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _iter_records(kind: str) -> list[dict[str, Any]]:
    root = _get_entity_dirs()[kind]
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    with _lock:
        for path in root.glob("*.json"):
            try:
                items.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    return items


def _sorted_records(kind: str) -> list[dict[str, Any]]:
    return sorted(
        _iter_records(kind),
        key=lambda item: item.get("_meta", {}).get("stored_at", ""),
        reverse=True,
    )


def _read_recent(kind: str, limit: int = 10) -> list[dict[str, Any]]:
    return _sorted_records(kind)[:limit]


def query_records(
    *,
    kind: str,
    limit: int = 20,
    trace_id: str = "",
    since: str = "",
) -> list[dict[str, Any]]:
    items = _sorted_records(kind)
    if trace_id:
        items = [item for item in items if item.get("_meta", {}).get("trace_id") == trace_id]
    if since:
        items = [item for item in items if item.get("_meta", {}).get("stored_at", "") >= since]
    return items[:limit]


def persist_cycle_record(cycle) -> str:
    return _write_record("cycles", _payload(cycle)["cycle_id"], cycle)


def persist_translator_rejection(rejection) -> str:
    return _write_record("translator_rejections", _payload(rejection)["rejection_id"], rejection)


def persist_intent(intent) -> str:
    return _write_record("intents", _payload(intent)["intent_id"], intent)


def persist_delegation_task(task) -> str:
    return _write_record("delegations", _payload(task)["task_id"], task)


def persist_execution_capability(capability) -> str:
    return _write_record("capabilities", _payload(capability)["capability_id"], capability)


def persist_execution_report(report) -> str:
    return _write_record("reports", _payload(report)["report_id"], report)


def persist_escalation_request(escalation) -> str:
    return _write_record("escalations", _payload(escalation)["escalation_id"], escalation)


def persist_worker_security_event(event) -> str:
    return _write_record("worker_security_events", _payload(event)["event_id"], event)


def persist_security_response(response) -> str:
    return _write_record("security_responses", _payload(response)["response_id"], response)


def persist_restriction(restriction) -> str:
    return _write_record("restrictions", _payload(restriction)["restriction_id"], restriction)


def persist_operator_action(action) -> str:
    return _write_record("operator_actions", _payload(action)["action_id"], action)


def persist_operator_token(token) -> str:
    return _write_record("operator_tokens", _payload(token)["token_id"], token)


def persist_control_plane_bootstrap(record) -> str:
    return _write_record("control_plane_bootstrap", _payload(record)["bootstrap_id"], record)


def persist_control_plane_maintenance(record) -> str:
    return _write_record("control_plane_maintenance", _payload(record)["action_id"], record)


def persist_control_plane_signal(signal) -> str:
    return _write_record("control_plane_signals", _payload(signal)["signal_id"], signal)


def list_recent_cycles(limit: int = 10) -> list[dict[str, Any]]:
    return _read_recent("cycles", limit)


def list_recent_translator_rejections(limit: int = 10) -> list[dict[str, Any]]:
    return _read_recent("translator_rejections", limit)


def list_recent_intents(limit: int = 10) -> list[dict[str, Any]]:
    return _read_recent("intents", limit)


def list_recent_delegations(limit: int = 10) -> list[dict[str, Any]]:
    return _read_recent("delegations", limit)


def list_recent_reports(limit: int = 10) -> list[dict[str, Any]]:
    return _read_recent("reports", limit)


def list_recent_escalations(limit: int = 10) -> list[dict[str, Any]]:
    return _read_recent("escalations", limit)


def list_recent_worker_security_events(limit: int = 10) -> list[dict[str, Any]]:
    return _read_recent("worker_security_events", limit)


def list_recent_security_responses(limit: int = 10) -> list[dict[str, Any]]:
    return _read_recent("security_responses", limit)


def list_recent_restrictions(limit: int = 10) -> list[dict[str, Any]]:
    return _read_recent("restrictions", limit)


def list_recent_operator_actions(
    limit: int = 10,
    *,
    operator_id: str = "",
    restriction_id: str = "",
    action_type: str = "",
) -> list[dict[str, Any]]:
    items = _sorted_records("operator_actions")
    if operator_id:
        items = [item for item in items if item.get("payload", {}).get("operator_id") == operator_id]
    if restriction_id:
        items = [item for item in items if item.get("payload", {}).get("target_restriction_id") == restriction_id]
    if action_type:
        items = [item for item in items if item.get("payload", {}).get("action_type") == action_type]
    return items[:limit]


def list_operator_tokens(limit: int = 50, *, operator_id: str = "", is_active: bool | None = None) -> list[dict[str, Any]]:
    items = _sorted_records("operator_tokens")
    if operator_id:
        items = [item for item in items if item.get("payload", {}).get("operator_id") == operator_id]
    if is_active is not None:
        items = [item for item in items if bool(item.get("payload", {}).get("is_active")) is is_active]
    return items[:limit]


def list_control_plane_bootstrap_records(limit: int = 20) -> list[dict[str, Any]]:
    return _read_recent("control_plane_bootstrap", limit)


def list_recent_control_plane_maintenance(limit: int = 20) -> list[dict[str, Any]]:
    return _read_recent("control_plane_maintenance", limit)


def list_recent_control_plane_signals(limit: int = 20) -> list[dict[str, Any]]:
    return _read_recent("control_plane_signals", limit)


def cleanup_expired_records(*, now_ts: str = "") -> dict[str, int]:
    global _last_cleanup_at

    now_dt = _parse_iso(now_ts) or _now_dt()
    entity_dirs = _get_entity_dirs()
    deleted_counts = {kind: 0 for kind in entity_dirs}
    with _lock:
        for kind, root in entity_dirs.items():
            if not root.exists():
                continue
            for path in root.glob("*.json"):
                try:
                    envelope = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                retention_until = _parse_iso(envelope.get("_meta", {}).get("retention_until", ""))
                if retention_until is None or retention_until > now_dt:
                    continue
                try:
                    path.unlink()
                    deleted_counts[kind] += 1
                except OSError:
                    continue
        _last_cleanup_at = now_iso()
    return deleted_counts


def get_store_status() -> dict[str, Any]:
    counts: dict[str, int] = {}
    expired_count = 0
    now_dt = _now_dt()
    oldest = ""
    newest = ""
    for kind in _get_entity_dirs():
        records = _iter_records(kind)
        counts[kind] = len(records)
        for record in records:
            meta = record.get("_meta", {})
            stored_at = meta.get("stored_at", "")
            if stored_at and (not oldest or stored_at < oldest):
                oldest = stored_at
            if stored_at and stored_at > newest:
                newest = stored_at
            retention_until = _parse_iso(meta.get("retention_until", ""))
            if retention_until is not None and retention_until <= now_dt:
                expired_count += 1
    return {
        "root": str(get_mso_store_root()),
        "counts": counts,
        "total_records": sum(counts.values()),
        "retention_days": dict(_RETENTION_DAYS),
        "expired_record_count": expired_count,
        "oldest_record_at": oldest,
        "newest_record_at": newest,
        "last_cleanup_at": _last_cleanup_at,
    }


def clear_mso_store() -> None:
    global _last_cleanup_at
    if not get_mso_store_root().exists():
        return
    with _lock:
        for root in _get_entity_dirs().values():
            if not root.exists():
                continue
            for path in root.glob("*"):
                try:
                    path.unlink()
                except OSError:
                    continue
        _last_cleanup_at = ""
