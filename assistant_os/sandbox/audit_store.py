"""
AuditStore — append-only JSONL persistent audit store.

Design
------
AuditStore writes every emitted event to a local JSONL file (one JSON object
per line).  Records survive process restart: construct a new AuditStore with
the same path and existing records are available immediately via events() and
count().

Interface compatibility
-----------------------
AuditStore implements the same emit / events / all_dicts / count interface as
AuditLog, so it can be used as a drop-in replacement wherever an AuditLog is
accepted.  clear() is deliberately NOT provided — the store is append-only.

Record format (one JSON line per event)
----------------------------------------
{
  "_seq":        <int>   sequential 1-based event number,
  "_written_at": <float> wall-clock timestamp at write time,
  "event_type":  <str>   event type for fast filtering,
  ...                    all fields from event.to_dict()
}

The "_seq" field provides a lightweight integrity aid: any gap in sequence
numbers or out-of-order record indicates file corruption or tampering.

Thread safety
-------------
A single threading.Lock serialises both file I/O and in-memory list mutations.

Redaction invariant
-------------------
AuditStore never inspects or transforms event content.  Events must already be
safe for logging (i.e. no secret values) before being passed to emit().  The
caller (RunnerAPI, RevocationManager, etc.) is responsible for that invariant.

Separation from AuditLog
-------------------------
AuditLog is the in-memory, process-local event bus used during execution.
AuditStore is the persistence layer.  They can be used independently or the
same AuditStore instance can serve as audit_log= to capture and persist in one
step.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# _DiskEvent — lightweight wrapper for records loaded from the JSONL file
# ---------------------------------------------------------------------------

class _DiskEvent:
    """
    Thin wrapper around a dict loaded from JSONL so that loaded events have the
    same .event_type attribute and .to_dict() method as live event objects.
    """

    __slots__ = ("event_type", "_data")

    def __init__(self, data: dict) -> None:
        self.event_type: str = data.get("event_type", "")
        self._data: dict = data

    def to_dict(self) -> dict:
        return dict(self._data)

    def __repr__(self) -> str:
        return f"_DiskEvent(event_type={self.event_type!r}, seq={self._data.get('_seq')})"


# ---------------------------------------------------------------------------
# AuditStore
# ---------------------------------------------------------------------------

class AuditStore:
    """
    Append-only JSONL persistent audit store.

    Parameters
    ----------
    path            : Absolute or relative path to the JSONL file.  The parent
                      directory must already exist.
    load_existing   : If True (default), existing records are read into memory
                      on construction so events() / count() cover full history.

    Usage
    -----
        store = AuditStore("/var/log/assistantos/audit.jsonl")
        store.emit(ExecutionEvent(...))
        store.emit(SecretAccessEvent(...))
        # later, in a new process:
        store2 = AuditStore("/var/log/assistantos/audit.jsonl")
        records = store2.events(AuditEventType.EXECUTION_STARTED)
    """

    def __init__(
        self,
        path: "str | Path",
        *,
        load_existing: bool = True,
        create_parent: bool = True,
    ) -> None:
        self._path = Path(path)

        if not self._path.suffix:
            raise ValueError(
                f"AuditStore path must point to a file, not a directory: {path!r}"
            )

        if create_parent and not self._path.parent.exists():
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise OSError(
                    f"AuditStore could not create parent directory "
                    f"{str(self._path.parent)!r}: {exc}"
                ) from exc

        self._lock = threading.Lock()
        self._events: list[Any] = []   # mix of live objects and _DiskEvent wrappers
        self._seq: int = 0             # next sequence number to assign

        if load_existing and self._path.exists():
            self._load_existing()

    # ------------------------------------------------------------------
    # Public interface (compatible with AuditLog)
    # ------------------------------------------------------------------

    def emit(self, event: Any) -> None:
        """
        Record an audit event to both the in-memory list and the JSONL file.

        Thread-safe.  The event is expected to have a to_dict() method and an
        event_type attribute — exactly the contract of the frozen dataclasses in
        audit.py.

        Non-conforming objects are accepted but will produce malformed JSONL
        records and may cause errors at query time.
        """
        with self._lock:
            self._seq += 1
            seq = self._seq

            # Build the persisted record: system fields + flattened event dict.
            try:
                event_dict = event.to_dict()
            except Exception:
                event_dict = {}

            record: dict = {
                "_seq": seq,
                "_written_at": _now(),
            }
            record.update(event_dict)

            # Append to file first (persistence is the primary goal).
            try:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, default=str) + "\n")
            except Exception:
                pass  # Swallow file errors — never block execution for logging

            # Keep in-memory copy for fast querying.
            self._events.append(event)

    def events(self, event_type: Optional[str] = None) -> list[Any]:
        """
        Return a snapshot of all events, optionally filtered by event_type.

        Returns a copy — callers cannot mutate the internal list.
        """
        with self._lock:
            if event_type is None:
                return list(self._events)
            return [
                e for e in self._events
                if getattr(e, "event_type", None) == event_type
            ]

    def all_dicts(self) -> list[dict]:
        """
        Return all events serialised to dicts.

        For events loaded from disk, the full persisted record (including _seq
        and _written_at) is returned.  For live event objects emitted in this
        process, the event's own to_dict() is returned.
        """
        with self._lock:
            result = []
            for e in self._events:
                try:
                    result.append(e.to_dict())
                except Exception:
                    pass
            return result

    def count(self, event_type: Optional[str] = None) -> int:
        """Return count of events, optionally filtered by event_type."""
        return len(self.events(event_type))

    def read_from_disk(self) -> list[dict]:
        """
        Read and return all raw records from the JSONL file.

        Returns parsed dicts (each with _seq, _written_at, event_type, and
        all event fields).  Does not affect the in-memory state.

        Useful for cross-process audit queries and integrity checks.
        """
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
                                pass  # Skip corrupt lines
            except OSError:
                pass
        return records

    @property
    def path(self) -> Path:
        """Path to the backing JSONL file."""
        return self._path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_existing(self) -> None:
        """
        Load records from the existing JSONL file into memory.

        Called once at construction.  Must be called before the lock is
        acquired by any public method (i.e. during __init__ only).
        """
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
    """Wall-clock time in seconds since epoch."""
    import time
    return time.time()
