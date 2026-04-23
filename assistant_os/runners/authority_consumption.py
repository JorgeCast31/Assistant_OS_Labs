from __future__ import annotations

from threading import Lock


class AuthorityConsumptionRegistry:
    """In-memory consumed-signature registry for replay prevention."""

    def __init__(self) -> None:
        self._consumed_signatures: set[str] = set()
        self._lock = Lock()

    def is_consumed(self, signature: str) -> bool:
        normalized = signature.strip()
        if not normalized:
            return True
        with self._lock:
            return normalized in self._consumed_signatures

    def mark_consumed(self, signature: str) -> None:
        normalized = signature.strip()
        if not normalized:
            return
        with self._lock:
            self._consumed_signatures.add(normalized)
