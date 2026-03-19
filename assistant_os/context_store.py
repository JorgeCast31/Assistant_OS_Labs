"""
Context Store - Persistent store for pending confirmation plans.

Stores plans that require confirmation before execution.
Data is persisted to disk (context_store.json) so pending plans survive
server restarts. In-memory dict is the primary structure; disk is synced
on every mutation.

Usage:
    from .context_store import store_pending_plan, get_pending_plan, remove_pending_plan

    # When generating a plan that needs confirmation
    context_id = store_pending_plan(plan, operation="WORK_CREATE", text="crear tarea X")

    # When user confirms
    stored = get_pending_plan(context_id)
    if stored:
        plan = stored["plan"]
        # execute plan...
        remove_pending_plan(context_id)
"""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict, Optional

_log = logging.getLogger(__name__)
from .contracts import Plan
from .config import MEMORY_DIR


# TTL in seconds (15 minutes default)
CONTEXT_TTL_SECONDS = 15 * 60

# Persistence file path
CONTEXT_STORE_FILE: Path = MEMORY_DIR / "context_store.json"


class StoredContext(TypedDict):
    """A stored pending plan awaiting confirmation."""
    plan: Plan                    # The plan to execute
    operation: str                # Operation type (WORK_CREATE, WORK_DELETE, etc.)
    raw_text: str                 # Original user input
    created_at: str               # ISO timestamp
    expires_at: str               # ISO timestamp when this expires


# ---------------------------------------------------------------------------
# Disk persistence helpers
# ---------------------------------------------------------------------------

def _load_store_from_disk() -> dict[str, StoredContext]:
    """
    Load store from disk. Returns empty dict on any error (missing file,
    corrupted JSON, unexpected structure). Never raises.

    Logs a warning to stderr when the file exists but cannot be parsed so that
    data loss is visible at server startup rather than silently discarded.
    """
    if not CONTEXT_STORE_FILE.exists():
        return {}
    try:
        content = CONTEXT_STORE_FILE.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, dict):
            return data  # type: ignore[return-value]
        _log.warning(
            "context_store.json has unexpected root type %s — starting with empty store",
            type(data).__name__,
        )
    except (json.JSONDecodeError, IOError, OSError) as exc:
        _log.warning(
            "context_store.json could not be loaded (%s: %s) — "
            "starting with empty store; pending confirmations may be lost",
            type(exc).__name__,
            exc,
        )
    return {}


def _save_store_to_disk(store: dict[str, StoredContext]) -> None:
    """
    Persist store to disk using atomic write (write .tmp → rename).
    Must be called while holding _lock. Never raises — failures are silent
    to avoid breaking confirmation flows over a transient I/O error.
    """
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = CONTEXT_STORE_FILE.with_suffix(".tmp")
        content = json.dumps(store, indent=2, ensure_ascii=False)
        tmp_file.write_text(content, encoding="utf-8")
        # Windows requires removing the target before rename
        if os.name == "nt" and CONTEXT_STORE_FILE.exists():
            CONTEXT_STORE_FILE.unlink()
        tmp_file.rename(CONTEXT_STORE_FILE)
    except Exception:
        pass  # Disk persistence is best-effort; in-memory state is authoritative


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Thread-safe store
_lock = threading.Lock()
_store: dict[str, StoredContext] = _load_store_from_disk()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return current time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> datetime:
    """Parse ISO timestamp to datetime."""
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def _is_expired(stored: StoredContext) -> bool:
    """Check if a stored context is expired."""
    expires_at = _parse_iso(stored["expires_at"])
    now = datetime.now(timezone.utc)
    return now > expires_at


# ---------------------------------------------------------------------------
# Public API (interface unchanged)
# ---------------------------------------------------------------------------

def store_pending_plan(
    context_id: str,
    plan: Plan,
    operation: str,
    raw_text: str = "",
) -> str:
    """
    Store a plan pending confirmation.

    Args:
        context_id: The unique context ID for this plan
        plan: The Plan to store
        operation: Operation type (WORK_CREATE, WORK_DELETE, etc.)
        raw_text: Original user input

    Returns:
        The context_id for retrieval
    """
    now = datetime.now(timezone.utc)
    expires_at = datetime.fromtimestamp(now.timestamp() + CONTEXT_TTL_SECONDS, tz=timezone.utc)

    stored: StoredContext = {
        "plan": dict(plan),  # Copy to avoid mutation
        "operation": operation,
        "raw_text": raw_text,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }

    with _lock:
        _store[context_id] = stored
        _save_store_to_disk(_store)

    return context_id


def get_pending_plan(context_id: str) -> Optional[StoredContext]:
    """
    Retrieve a stored plan by context_id.

    Returns None if not found or expired.
    """
    with _lock:
        stored = _store.get(context_id)

    if stored is None:
        return None

    if _is_expired(stored):
        # Clean up expired entry
        remove_pending_plan(context_id)
        return None

    return stored


def remove_pending_plan(context_id: str) -> bool:
    """
    Remove a stored plan after execution or expiry.

    Returns True if removed, False if not found.
    """
    with _lock:
        if context_id in _store:
            del _store[context_id]
            _save_store_to_disk(_store)
            return True
        return False


def cleanup_expired() -> int:
    """
    Remove all expired entries from the store.

    Returns the number of entries removed.
    """
    to_remove = []

    with _lock:
        for ctx_id, stored in _store.items():
            if _is_expired(stored):
                to_remove.append(ctx_id)

        for ctx_id in to_remove:
            del _store[ctx_id]

        if to_remove:
            _save_store_to_disk(_store)

    return len(to_remove)


def get_store_size() -> int:
    """Return current number of stored contexts."""
    with _lock:
        return len(_store)


def clear_store() -> int:
    """
    Clear all stored contexts (for testing).

    Returns the number of entries cleared.
    """
    with _lock:
        count = len(_store)
        _store.clear()
        _save_store_to_disk(_store)
        return count
