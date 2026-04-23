from __future__ import annotations

from threading import Lock


class AuthorityConsumptionRegistry:
    """In-memory replay guard for consumed authority artifact signatures."""

    def __init__(self) -> None:
        self._consumed_signatures: set[str] = set()
        self._lock = Lock()

    def consume(self, signature: str) -> bool:
        """Mark a signature as consumed, returning False when already consumed."""
        normalized = signature.strip()
        if not normalized:
            return False
        with self._lock:
            if normalized in self._consumed_signatures:
                return False
            self._consumed_signatures.add(normalized)
            return True
