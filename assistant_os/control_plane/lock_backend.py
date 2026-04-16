"""Replaceable lock backend abstractions for the control plane."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time

from ..config import MEMORY_DIR


@dataclass(slots=True)
class LockBackendLease:
    """Backend-native lock lease information."""

    lock_id: str
    acquired: bool


class LockBackend:
    """Abstract backend interface for control-plane locking."""

    def acquire(self, lock_id: str, *, timeout_seconds: float = 0.0) -> LockBackendLease:
        raise NotImplementedError

    def release(self, lock_id: str) -> None:
        raise NotImplementedError

    def cleanup_unused(self) -> int:
        raise NotImplementedError

    def active_lock_ids(self) -> list[str]:
        raise NotImplementedError


class LocalProcessLockBackend(LockBackend):
    """Process-local backend used by default today."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.RLock()

    def _ensure_lock(self, lock_id: str) -> threading.Lock:
        with self._guard:
            if lock_id not in self._locks:
                self._locks[lock_id] = threading.Lock()
            return self._locks[lock_id]

    def get_lock_for_compat(self, lock_id: str) -> threading.Lock:
        return self._ensure_lock(lock_id)

    def acquire(self, lock_id: str, *, timeout_seconds: float = 0.0) -> LockBackendLease:
        lock = self._ensure_lock(lock_id)
        acquired = lock.acquire(timeout=max(timeout_seconds, 0.0))
        return LockBackendLease(lock_id=lock_id, acquired=acquired)

    def release(self, lock_id: str) -> None:
        with self._guard:
            lock = self._locks.get(lock_id)
        if lock is not None and lock.locked():
            lock.release()

    def cleanup_unused(self) -> int:
        removed = 0
        with self._guard:
            removable = [
                key
                for key, lock in self._locks.items()
                if not lock.locked()
            ]
            for key in removable:
                self._locks.pop(key, None)
                removed += 1
        return removed

    def active_lock_ids(self) -> list[str]:
        with self._guard:
            return [key for key, lock in self._locks.items() if lock.locked()]


class FileLockBackend(LockBackend):
    """Minimal file-based backend proving lock replacement beyond process memory."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or (MEMORY_DIR / "control_plane_locks")).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._guard = threading.RLock()
        self._held: set[str] = set()

    def _path_for(self, lock_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in lock_id).strip("._")
        return self._root / f"{safe or 'lock'}.lck"

    def acquire(self, lock_id: str, *, timeout_seconds: float = 0.0) -> LockBackendLease:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._path_for(lock_id)
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while True:
            try:
                with self._guard:
                    with path.open("x", encoding="utf-8") as handle:
                        handle.write(lock_id)
                    self._held.add(lock_id)
                return LockBackendLease(lock_id=lock_id, acquired=True)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    return LockBackendLease(lock_id=lock_id, acquired=False)
                time.sleep(0.01)

    def release(self, lock_id: str) -> None:
        path = self._path_for(lock_id)
        with self._guard:
            self._held.discard(lock_id)
            if path.exists():
                path.unlink()

    def cleanup_unused(self) -> int:
        removed = 0
        with self._guard:
            for path in self._root.glob("*.lck"):
                lock_id = path.read_text(encoding="utf-8") if path.exists() else ""
                if lock_id in self._held:
                    continue
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
        return removed

    def active_lock_ids(self) -> list[str]:
        with self._guard:
            return sorted(path.stem for path in self._root.glob("*.lck"))
