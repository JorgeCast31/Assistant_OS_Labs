"""Fail-safe bounded session history reader for MSO Economic Cognition.

build_mso_session_history() never raises — all errors produce an unavailable
result with warnings. Safe to call in the hot path of mso_direct cognitive
generation.

Read-only: this module never writes to the session store.
"""

from __future__ import annotations

MAX_CONTENT_CHARS: int = 400
_DEFAULT_LIMIT_TURNS: int = 5


def build_mso_session_history(
    session_id: str | None,
    limit_turns: int = _DEFAULT_LIMIT_TURNS,
    max_content_chars: int = MAX_CONTENT_CHARS,
) -> dict:
    """Build a bounded, read-only session history dict for MSO cognitive generation.

    Reads from chat_db. Returns at most ``limit_turns * 2`` messages (user +
    assistant alternating). Truncates individual message content to
    ``max_content_chars`` characters.

    Returned shape::

        {
          "available": bool,
          "turns": [{"role": "user"|"assistant", "content": str}, ...],
          "turns_used": int,
          "source": "chat_sessions" | "unavailable" | "none",
          "truncated": bool,
          "warnings": [...],
        }

    Never raises. session_id=None → available=False, source='none'.
    Unknown session → available=False, source='unavailable'.
    DB error → available=False with warning.
    """
    if not session_id or not isinstance(session_id, str) or not session_id.strip():
        return _unavailable("none")

    try:
        from assistant_os.chat_db import get_session_with_messages
        session = get_session_with_messages(session_id.strip())
    except Exception as exc:
        return _unavailable("unavailable", warning=f"DB read error: {exc}")

    if session is None:
        return _unavailable("unavailable")

    raw_messages: list[dict] = session.get("messages") or []
    if not raw_messages:
        return {
            "available": True,
            "turns": [],
            "turns_used": 0,
            "source": "chat_sessions",
            "truncated": False,
            "warnings": [],
        }

    # Take the last limit_turns * 2 messages (each "turn" = one message)
    max_messages = limit_turns * 2
    tail = raw_messages[-max_messages:]

    turns: list[dict[str, str]] = []
    truncated = False

    for msg in tail:
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        if len(content) > max_content_chars:
            content = content[:max_content_chars].rstrip()
            truncated = True
        turns.append({"role": role, "content": content})

    return {
        "available": True,
        "turns": turns,
        "turns_used": len(turns),
        "source": "chat_sessions",
        "truncated": truncated,
        "warnings": [],
    }


def _unavailable(source: str, warning: str = "") -> dict:
    return {
        "available": False,
        "turns": [],
        "turns_used": 0,
        "source": source,
        "truncated": False,
        "warnings": [warning] if warning else [],
    }
