"""Confirm flow readiness — passive observability over context_store.

S-CONFIRM-FLOW-01 Phase A.

This module produces a non-authoritative ``ConfirmFlowSummary`` that exposes:

  * Aggregate counts of pending confirmation plans.
  * Time-to-expire signals (oldest age, nearest expiry).
  * A compact, capped list of pending entries — metadata only.

INVARIANTS — never violated by this module
------------------------------------------
- ``get_confirm_flow_summary()`` does NOT execute any pending plan.
- ``get_confirm_flow_summary()`` does NOT call ``remove_pending_plan``,
  ``cleanup_expired``, or ``store_pending_plan``.
- ``get_confirm_flow_summary()`` does NOT call kernel, router, agents,
  pipelines, runner, or governance engines.
- The compact list NEVER contains the ``plan`` field (which may carry
  user/business payload) or the ``raw_text`` field (original user input).
- All probes are fail-soft: errors yield a structured zero-summary, never
  raise. This includes the case where ``_read_store_snapshot`` itself
  raises (defense-in-depth).
- Output is JSON-serializable.
- Output never includes ``execution_mode``, ``GovernanceVerdict``,
  ``PolicyDecision``, or any "authorized"/"safe_to_apply"/"ready_to_confirm"
  field.

This is observability, not authority. Confirmation consumption remains the
responsibility of the per-domain confirm endpoints; MSO is the only source
of authority for whether a plan may be confirmed at all.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Tuple, TypedDict


# ---------------------------------------------------------------------------
# Public contract
# ---------------------------------------------------------------------------

class CompactPendingEntry(TypedDict, total=False):
    """Compact pending-plan metadata — never carries payload."""

    context_id: str
    operation: str
    created_at: str
    expires_at: str
    age_seconds: int
    time_to_expire_seconds: int
    expired: bool


class ConfirmFlowSummary(TypedDict, total=False):
    """Read-only readiness snapshot for the confirm flow queue."""

    source: str                              # always "confirm_flow"
    feature_enabled: bool                    # always True (queue is always observable)
    last_health_check: str                   # ISO 8601 UTC
    note: str                                # invariant disclaimer

    pending_count: int
    expired_pending_count: int
    oldest_age_seconds: Optional[int]
    nearest_expiry_seconds: Optional[int]
    pending: list[CompactPendingEntry]

    # Fail-soft fields (only present when an error occurred)
    error: Optional[str]


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_NOTE = (
    "Confirm flow queue is observability only — confirmation is governed by "
    "MSO/policy and consumed by domain confirmation endpoints. Readiness is "
    "not authority."
)

_DEFAULT_LIST_LIMIT: int = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 string. Returns None on any failure (fail-soft)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _read_store_snapshot() -> Tuple[dict[str, dict[str, Any]], Optional[str]]:
    """Return a shallow copy of the in-memory context_store dict.

    Reads under the store's RLock to get a consistent view, then copies
    so we never mutate or hand out references to the live store.

    Returns ``(store_snapshot, error_or_None)``. Never raises in normal use,
    but callers must still wrap calls defensively (a regression or test mock
    could re-introduce raising behavior).
    """
    try:
        from .. import context_store as _cs
        with _cs._lock:  # type: ignore[attr-defined]
            return dict(_cs._store), None  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        return {}, f"{type(exc).__name__}: {exc}"


def _is_expired(stored: dict[str, Any], now: datetime) -> bool:
    """True if expires_at is parseable and earlier than now."""
    expires_dt = _parse_iso(stored.get("expires_at"))
    if expires_dt is None:
        return False
    return expires_dt <= now


def _to_compact_entry(context_id: str, stored: dict[str, Any],
                       now: datetime) -> CompactPendingEntry:
    """Project a stored entry to a compact metadata-only entry.

    Never copies ``plan`` or ``raw_text``. Computes age and time-to-expire
    relative to ``now``.
    """
    created_at_str = stored.get("created_at") if isinstance(stored.get("created_at"), str) else ""
    expires_at_str = stored.get("expires_at") if isinstance(stored.get("expires_at"), str) else ""
    operation = stored.get("operation") if isinstance(stored.get("operation"), str) else ""

    created_dt = _parse_iso(created_at_str)
    expires_dt = _parse_iso(expires_at_str)

    age_seconds = 0
    if created_dt is not None:
        age_seconds = max(0, int((now - created_dt).total_seconds()))

    time_to_expire = 0
    if expires_dt is not None:
        time_to_expire = int((expires_dt - now).total_seconds())

    return CompactPendingEntry(
        context_id=context_id,
        operation=operation,
        created_at=created_at_str,
        expires_at=expires_at_str,
        age_seconds=age_seconds,
        time_to_expire_seconds=time_to_expire,
        expired=(expires_dt is not None and expires_dt <= now),
    )


def _safe_read_snapshot() -> Tuple[dict[str, dict[str, Any]], Optional[str]]:
    """Defense-in-depth wrapper around _read_store_snapshot.

    Even though _read_store_snapshot is itself fail-soft, a regression or a
    test mock could re-introduce raising behavior. The producer MUST never
    raise, so we wrap every call site here.
    """
    try:
        return _read_store_snapshot()
    except Exception as exc:  # noqa: BLE001
        return {}, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Public producer
# ---------------------------------------------------------------------------

def list_pending_summary(*, limit: int = _DEFAULT_LIST_LIMIT) -> list[CompactPendingEntry]:
    """Return up to ``limit`` compact pending entries, oldest-first.

    NEVER includes ``plan`` or ``raw_text``. Sorted by age descending
    (oldest at index 0) so consumers can show the most-aged first.
    """
    if limit <= 0:
        return []
    snapshot, _err = _safe_read_snapshot()
    now = _now_utc()
    entries: list[CompactPendingEntry] = []
    for ctx_id, stored in snapshot.items():
        if not isinstance(stored, dict):
            continue
        try:
            entries.append(_to_compact_entry(str(ctx_id), stored, now))
        except Exception:  # noqa: BLE001 — fail-soft, skip this entry
            continue
    # Oldest first — largest age_seconds at index 0.
    entries.sort(key=lambda e: e.get("age_seconds", 0), reverse=True)
    return entries[:limit]


def get_confirm_flow_summary(*, limit: int = _DEFAULT_LIST_LIMIT) -> ConfirmFlowSummary:
    """Return a read-only, fail-soft summary of the confirm flow queue.

    Never raises. On store-read failure, returns a structured zero-summary
    with the error string surfaced via the ``error`` field.
    """
    summary: ConfirmFlowSummary = {
        "source": "confirm_flow",
        "feature_enabled": True,
        "last_health_check": _now_iso(),
        "note": _NOTE,
        "pending_count": 0,
        "expired_pending_count": 0,
        "oldest_age_seconds": None,
        "nearest_expiry_seconds": None,
        "pending": [],
    }

    snapshot, err = _safe_read_snapshot()
    if err is not None:
        summary["error"] = err
        return summary

    now = _now_utc()
    pending_count = 0
    expired_count = 0
    oldest_age: Optional[int] = None
    nearest_expiry: Optional[int] = None
    compact_entries: list[CompactPendingEntry] = []

    for ctx_id, stored in snapshot.items():
        if not isinstance(stored, dict):
            continue
        pending_count += 1
        try:
            entry = _to_compact_entry(str(ctx_id), stored, now)
        except Exception:  # noqa: BLE001 — fail-soft per-entry
            continue
        compact_entries.append(entry)
        if entry.get("expired"):
            expired_count += 1
        # Aggregate age/expiry signals across ALL entries (not just the capped list).
        age = entry.get("age_seconds", 0)
        if oldest_age is None or age > oldest_age:
            oldest_age = age
        tte = entry.get("time_to_expire_seconds", 0)
        if nearest_expiry is None or tte < nearest_expiry:
            nearest_expiry = tte

    compact_entries.sort(key=lambda e: e.get("age_seconds", 0), reverse=True)

    summary["pending_count"] = pending_count
    summary["expired_pending_count"] = expired_count
    summary["oldest_age_seconds"] = oldest_age
    summary["nearest_expiry_seconds"] = nearest_expiry
    summary["pending"] = compact_entries[: max(0, int(limit))]

    return summary


__all__ = [
    "CompactPendingEntry",
    "ConfirmFlowSummary",
    "get_confirm_flow_summary",
    "list_pending_summary",
]
