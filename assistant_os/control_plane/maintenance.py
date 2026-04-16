"""Operational maintenance actions for the control plane."""

from __future__ import annotations

from dataclasses import asdict
import logging
import uuid

from ..contracts import now_iso
from ..mso.contracts import MaintenanceActionRecord, OperationalSignal, OperatorContext
from ..storage.mso_store import (
    cleanup_expired_records,
    get_store_status,
    list_recent_control_plane_maintenance,
    list_recent_control_plane_signals,
    persist_control_plane_maintenance,
    persist_control_plane_signal,
)
from .locks import lock_manager
from .token_service import cleanup_expired_tokens, summarize_operator_tokens

logger = logging.getLogger("assistant_os.control_plane")


def _persist_maintenance(
    *,
    action_type: str,
    trigger: str,
    status: str,
    detail: str,
    result: dict,
    operator_context: OperatorContext | None = None,
    trace_id: str = "",
) -> MaintenanceActionRecord:
    record = MaintenanceActionRecord(
        action_id=f"maintenance:{uuid.uuid4()}",
        action_type=action_type,
        trigger=trigger,
        created_at=now_iso(),
        status=status,
        trace_id=trace_id,
        operator_id=operator_context.operator_id if operator_context else "",
        request_id=operator_context.request_id if operator_context else "",
        detail=detail,
        result=result,
    )
    persist_control_plane_maintenance(record)
    return record


def emit_operational_signal(
    *,
    source: str,
    severity: str,
    code: str,
    detail: str,
    related_action_id: str = "",
    trace_id: str = "",
) -> OperationalSignal:
    signal = OperationalSignal(
        signal_id=f"signal:{uuid.uuid4()}",
        source=source,
        severity=severity,
        code=code,
        detail=detail,
        created_at=now_iso(),
        related_action_id=related_action_id,
        trace_id=trace_id,
    )
    persist_control_plane_signal(signal)
    logger.warning(
        "control_plane.signal.emitted",
        extra={
            "event": "control_plane.signal.emitted",
            "source": source,
            "severity": severity,
            "code": code,
        },
    )
    return signal


def run_maintenance_cycle(
    *,
    trigger: str,
    operator_context: OperatorContext | None = None,
    trace_id: str = "",
    now_ts: str = "",
) -> dict:
    warnings: list[str] = []
    token_cleanup = cleanup_expired_tokens(now_ts=now_ts)
    store_cleanup = cleanup_expired_records(now_ts=now_ts)
    cleaned_locks = lock_manager.cleanup_unused_locks()
    token_summary = summarize_operator_tokens()
    store_status = get_store_status()
    if token_summary["expired_active_tokens"] > 0:
        warnings.append("expired_active_tokens_detected")
    if store_status["expired_record_count"] > 0:
        warnings.append("expired_store_records_detected")
    result = {
        "cleaned_tokens": token_cleanup["count"],
        "cleaned_store_records": store_cleanup,
        "cleaned_lock_slots": cleaned_locks,
        "token_summary": token_summary,
        "store_status": store_status,
        "warnings": warnings,
    }
    record = _persist_maintenance(
        action_type="maintenance_cycle",
        trigger=trigger,
        status="ok" if not warnings else "warning",
        detail="control-plane maintenance cycle completed",
        result=result,
        operator_context=operator_context,
        trace_id=trace_id,
    )
    signals = []
    if token_summary["expired_active_tokens"] > 0:
        signals.append(
            asdict(
                emit_operational_signal(
                    source="maintenance_cycle",
                    severity="warning",
                    code="expired_active_tokens_present",
                    detail="Expired active tokens remain after maintenance cycle",
                    related_action_id=record.action_id,
                    trace_id=trace_id,
                )
            )
        )
    return {
        "maintenance": asdict(record),
        "result": result,
        "signals": signals,
    }


def force_token_cleanup(
    *,
    now_ts: str = "",
    operator_context: OperatorContext | None = None,
    trace_id: str = "",
) -> dict:
    cleanup = cleanup_expired_tokens(now_ts=now_ts)
    record = _persist_maintenance(
        action_type="force_token_cleanup",
        trigger="operator" if operator_context else "internal",
        status="ok",
        detail="forced token cleanup completed",
        result=cleanup,
        operator_context=operator_context,
        trace_id=trace_id,
    )
    return {"maintenance": asdict(record), **cleanup}


def inspect_active_locks(*, operator_context: OperatorContext | None = None, trace_id: str = "") -> dict:
    locks = {
        "active_count": len(lock_manager.active_locks()),
        "active": lock_manager.active_locks(),
    }
    record = _persist_maintenance(
        action_type="inspect_active_locks",
        trigger="operator" if operator_context else "internal",
        status="ok",
        detail="inspected active locks",
        result=locks,
        operator_context=operator_context,
        trace_id=trace_id,
    )
    return {"maintenance": asdict(record), **locks}


def force_lock_cleanup(*, operator_context: OperatorContext | None = None, trace_id: str = "") -> dict:
    cleaned = lock_manager.cleanup_unused_locks()
    result = {"cleaned_lock_slots": cleaned, "active_locks": lock_manager.active_locks()}
    record = _persist_maintenance(
        action_type="force_lock_cleanup",
        trigger="operator" if operator_context else "internal",
        status="ok",
        detail="forced lock cleanup completed",
        result=result,
        operator_context=operator_context,
        trace_id=trace_id,
    )
    if cleaned == 0:
        signal = emit_operational_signal(
            source="force_lock_cleanup",
            severity="info",
            code="no_stale_locks_cleaned",
            detail="Forced lock cleanup completed without removing stale locks",
            related_action_id=record.action_id,
            trace_id=trace_id,
        )
        return {"maintenance": asdict(record), **result, "signals": [asdict(signal)]}
    return {"maintenance": asdict(record), **result, "signals": []}


def recent_maintenance(limit: int = 10) -> list[dict]:
    return [item.get("payload", {}) for item in list_recent_control_plane_maintenance(limit=limit)]


def recent_signals(limit: int = 10) -> list[dict]:
    return [item.get("payload", {}) for item in list_recent_control_plane_signals(limit=limit)]
