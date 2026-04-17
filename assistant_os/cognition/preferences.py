"""
Cognitive usage preference store.

Stores and retrieves the operator's cognitive usage policy:
  "auto"              — system decides (default)
  "prefer_local"      — prefer local provider when available
  "deterministic_only" — never use the local LLM, deterministic path only

State is held in memory for the process lifetime. Persisting across restarts
is not a requirement for M29 — the default from COGNITION_DEFAULT_POLICY
is always a safe starting point.

The local model has NO execution authority regardless of policy.
Policy only controls whether the advisory layer is consulted.
"""
from __future__ import annotations

import threading
from typing import Literal, TypedDict

from ..config import COGNITION_DEFAULT_POLICY

# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

CognitionPolicy = Literal["auto", "prefer_local", "deterministic_only"]

VALID_POLICIES: frozenset[str] = frozenset({"auto", "prefer_local", "deterministic_only"})


class PreferencesPayload(TypedDict):
    """Shape stored and returned for cognitive preferences."""

    policy: str
    set_by: str   # "user" | "default"


# ---------------------------------------------------------------------------
# In-memory store (process-scoped, thread-safe)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_store: PreferencesPayload = {
    "policy": COGNITION_DEFAULT_POLICY if COGNITION_DEFAULT_POLICY in VALID_POLICIES else "auto",
    "set_by": "default",
}


def get_preferences() -> PreferencesPayload:
    """Return current cognitive preferences."""
    with _lock:
        return dict(_store)  # type: ignore[return-value]


def set_preferences(policy: str) -> tuple[bool, str]:
    """
    Update the cognitive usage policy.

    Returns (ok, error_message).
    """
    if policy not in VALID_POLICIES:
        return False, f"Invalid policy '{policy}'. Must be one of: {', '.join(sorted(VALID_POLICIES))}"
    with _lock:
        _store["policy"] = policy
        _store["set_by"] = "user"
    return True, ""


def reset_preferences() -> None:
    """
    Reset preferences to the process-default values.

    Intended for test isolation only — not for production use.
    Calling this in production would silently discard operator policy choices.
    """
    with _lock:
        _store["policy"] = COGNITION_DEFAULT_POLICY if COGNITION_DEFAULT_POLICY in VALID_POLICIES else "auto"
        _store["set_by"] = "default"
