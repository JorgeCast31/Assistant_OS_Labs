from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional


class _DiskEvent:
    __slots__ = ("event_type", "_data")

    def __init__(self, data: dict) -> None:
        self.event_type: str = data.get("event_type", "")
        self._data: dict = data

    def to_dict(self) -> dict:
        return dict(self._data)

    def __repr__(self) -> str:
        return f"_DiskEvent(event_type={self.event_type!r}, seq={self._data.get('_seq')})"


class JsonlAuditStore:
    """Append-only JSONL audit record store."""

    def __init__(
        self,
        path: str | Path,
        *,
        load_existing: bool = True,
        create_parent: bool = True,
    ) -> None:
        self._path = Path(path)

        if not self._path.suffix:
            raise ValueError(
                f"JsonlAuditStore path must point to a file: {path!r}"
            )

        if create_parent and not self._path.parent.exists():
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise OSError(
                    "JsonlAuditStore could not create parent directory "
                    f"{str(self._path.parent)!r}: {exc}"
                ) from exc

        self._lock = threading.Lock()
        self._events: list[Any] = []
        self._seq: int = 0

        if load_existing and self._path.exists():
            self._load_existing()

    def emit(self, event: Any) -> None:
        with self._lock:
            self._seq += 1
            seq = self._seq

            try:
                event_dict = event.to_dict()
            except Exception:
                event_dict = {}

            record: dict = {
                "_seq": seq,
                "_written_at": _now(),
                **event_dict,
            }

            try:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, default=str) + "\n")
            except Exception:
                pass

            self._events.append(event)

    def events(self, event_type: Optional[str] = None) -> list[Any]:
        with self._lock:
            if event_type is None:
                return list(self._events)
            return [
                event
                for event in self._events
                if getattr(event, "event_type", None) == event_type
            ]

    def all_dicts(self) -> list[dict]:
        with self._lock:
            result = []
            for event in self._events:
                try:
                    result.append(event.to_dict())
                except Exception:
                    pass
            return result

    def count(self, event_type: Optional[str] = None) -> int:
        return len(self.events(event_type))

    def read_from_disk(self) -> list[dict]:
        records: list[dict] = []
        if not self._path.exists():
            return records
        with self._lock:
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                records.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
            except OSError:
                pass
        return records

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        records = []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError:
            return

        for record in records:
            self._events.append(_DiskEvent(record))
            seq = record.get("_seq")
            if isinstance(seq, int) and seq > self._seq:
                self._seq = seq


def _now() -> float:
    import time

    return time.time()
