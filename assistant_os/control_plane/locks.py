"""Explicit control-plane lock abstraction for governed admin actions."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import time

from .lock_backend import LocalProcessLockBackend, LockBackend


class LockConflictError(RuntimeError):
    """Raised when a named control-plane lock cannot be acquired immediately."""


@dataclass(slots=True)
class LockLease:
    """Represents an acquired control-plane lock lease."""

    lock_id: str
    owner_id: str
    acquired_at: float


class ControlPlaneLockManager:
    """Process-local lock manager with explicit conflict and ownership semantics."""

    def __init__(self, *, backend: LockBackend | None = None) -> None:
        self._backend = backend or LocalProcessLockBackend()
        self._leases: dict[str, LockLease] = {}
        from threading import RLock

        self._guard = RLock()

    def _get_lock(self, key: str):
        """Compatibility shim retained for existing tests."""

        compat = getattr(self._backend, "get_lock_for_compat", None)
        if compat is None:
            raise RuntimeError("Current lock backend does not expose compatibility access")
        return compat(key)

    def set_backend(self, backend: LockBackend) -> None:
        with self._guard:
            if self._leases:
                raise LockConflictError("Cannot swap lock backend while leases are active")
            self._backend = backend

    def backend_name(self) -> str:
        return type(self._backend).__name__

    def acquire(
        self,
        key: str,
        *,
        owner_id: str = "",
        timeout_seconds: float = 0.0,
    ) -> LockLease:
        from threading import get_ident

        lease_owner = owner_id or f"thread:{get_ident()}"
        backend_lease = self._backend.acquire(key, timeout_seconds=max(timeout_seconds, 0.0))
        if not backend_lease.acquired:
            raise LockConflictError(f"Control-plane lock conflict for {key}")
        lease = LockLease(
            lock_id=key,
            owner_id=lease_owner,
            acquired_at=time.time(),
        )
        with self._guard:
            self._leases[key] = lease
        return lease

    def release(self, key: str, *, owner_id: str = "") -> None:
        with self._guard:
            lease = self._leases.get(key)
            if lease is None:
                return
            if owner_id and lease.owner_id != owner_id:
                raise LockConflictError(
                    f"Control-plane lock {key} is owned by {lease.owner_id}, not {owner_id}"
                )
            self._leases.pop(key, None)
        self._backend.release(key)

    @contextmanager
    def hold(
        self,
        key: str,
        *,
        owner_id: str = "",
        timeout_seconds: float = 0.0,
    ):
        lease = self.acquire(key, owner_id=owner_id, timeout_seconds=timeout_seconds)
        try:
            yield lease
        finally:
            self.release(key, owner_id=lease.owner_id)

    def active_locks(self) -> list[dict[str, object]]:
        with self._guard:
            return [asdict(lease) for lease in self._leases.values()]

    def cleanup_unused_locks(self) -> int:
        with self._guard:
            return self._backend.cleanup_unused()


lock_manager = ControlPlaneLockManager()


def configure_lock_backend(backend: LockBackend) -> None:
    lock_manager.set_backend(backend)


def reset_lock_backend() -> None:
    lock_manager.set_backend(LocalProcessLockBackend())
