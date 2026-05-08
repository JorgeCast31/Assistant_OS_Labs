from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Generic, TypeVar

from assistant_os.missions.candidate_audit import CandidateAuditRecord
from assistant_os.audit.jsonl_store import JsonlAuditStore
from assistant_os.police.models import PoliceAuditEvent


T = TypeVar("T")


class _PersistableRecord:
    def __init__(self, record: object) -> None:
        self._record = record
        self.event_type = str(_record_to_dict(record).get("event_type", ""))

    def to_dict(self) -> dict[str, object]:
        return _record_to_dict(self._record)


class _TypedAuditEventStore(Generic[T]):
    """Append-only observation store backed by the shared JSONL audit writer."""

    record_type: type[T]

    def __init__(self, path: Path | str) -> None:
        self._store = JsonlAuditStore(path)

    def emit(self, record: T) -> None:
        if not isinstance(record, self.record_type):
            expected = self.record_type.__name__
            actual = type(record).__name__
            raise TypeError(f"expected {expected}, got {actual}")
        self._store.emit(_PersistableRecord(record))

    def read_all(self) -> list[dict[str, object]]:
        return list(self._store.read_from_disk())


class PoliceAuditEventStore(_TypedAuditEventStore[PoliceAuditEvent]):
    """Append-only observation store for PoliceAuditEvent records."""

    record_type = PoliceAuditEvent


class CandidateAuditRecordStore(_TypedAuditEventStore[CandidateAuditRecord]):
    """Append-only observation store for CandidateAuditRecord records."""

    record_type = CandidateAuditRecord


def _record_to_dict(record: object) -> dict[str, object]:
    if hasattr(record, "to_dict"):
        data = record.to_dict()
    elif is_dataclass(record):
        data = asdict(record)
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {str(key): _jsonable(value) for key, value in data.items()}


def _jsonable(value: Any) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
