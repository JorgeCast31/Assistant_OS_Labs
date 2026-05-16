"""
HumanConfirmationRecord — immutable record of operator review signal.

Records that a human operator has reviewed a ConfirmablePreparedAction and
signalled confirm or reject. Does NOT grant execution authority, issue tokens,
satisfy any step in the authority chain (PolicyDecision → CapabilityToken →
OperationBinding → AuthorizedPlan → PoliceGate), or change execution_allowed.

Spec: S-HUMAN-CONFIRM-01
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


@dataclass(frozen=True, kw_only=True)
class HumanConfirmationRecord:
    """Immutable record of a single operator confirmation signal.

    execution_allowed is always False — this record does not authorize execution.
    """

    record_id: str = field(default_factory=_new_id)
    entry_id: str
    action_id: str
    confirmed: bool
    operator_note: str = ""
    recorded_at: datetime = field(default_factory=_now)
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ValueError("entry_id must be non-empty")
        if not self.action_id:
            raise ValueError("action_id must be non-empty")
        if self.execution_allowed is not False:
            raise ValueError(
                "execution_allowed must be False — confirmation does not authorize execution"
            )

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "entry_id": self.entry_id,
            "action_id": self.action_id,
            "confirmed": self.confirmed,
            "operator_note": self.operator_note,
            "recorded_at": self.recorded_at.isoformat(),
            "human_confirmation_status": "human_confirmed" if self.confirmed else "human_rejected",
            "execution_allowed": False,
            "can_execute_now": False,
        }


_lock = threading.Lock()
_store: dict[str, HumanConfirmationRecord] = {}


def record_human_confirmation(
    *,
    entry_id: str,
    action_id: str,
    confirmed: bool,
    operator_note: str = "",
) -> HumanConfirmationRecord:
    """Write a human confirmation signal. Thread-safe. Overwrites any prior record for entry_id."""
    record = HumanConfirmationRecord(
        entry_id=entry_id,
        action_id=action_id,
        confirmed=confirmed,
        operator_note=operator_note,
    )
    with _lock:
        _store[entry_id] = record
    return record


def get_human_confirmation(entry_id: str) -> HumanConfirmationRecord | None:
    """Return the recorded confirmation for entry_id, or None if not yet confirmed."""
    with _lock:
        return _store.get(entry_id)


def merge_confirmation_into_dict(entry_dict: dict) -> dict:
    """Overlay human_confirmation_status onto a prepared-action dict if a record exists.

    Reads queue_entry_id (or entry_id) from the dict, looks up the confirmation store,
    and returns a new dict with updated human_confirmation_status and recorded_at.

    Does not modify execution_allowed or can_execute_now — those remain False as
    enforced by the queue entry invariants.
    """
    entry_id = entry_dict.get("queue_entry_id") or entry_dict.get("entry_id")
    if not entry_id:
        return entry_dict
    record = get_human_confirmation(entry_id)
    if record is None:
        return entry_dict
    return {
        **entry_dict,
        "human_confirmation_status": "human_confirmed" if record.confirmed else "human_rejected",
        "confirmation_recorded_at": record.recorded_at.isoformat(),
        "operator_note": record.operator_note,
    }


def clear_human_confirmation_store_for_tests() -> None:
    """Reset in-memory store. For test isolation only."""
    with _lock:
        _store.clear()
