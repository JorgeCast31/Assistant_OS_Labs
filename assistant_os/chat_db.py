"""
chat_db.py — M17

SQLite persistence for chat sessions and messages.
All I/O is isolated here. Thread-safe via module-level lock + WAL mode.
"""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import MEMORY_DIR

# ---------------------------------------------------------------------------
# Schema / connection
# ---------------------------------------------------------------------------

DB_PATH: Path = MEMORY_DIR / "chat_sessions.db"

_UNSET = object()   # Sentinel for "parameter not provided"
_lock  = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.text_factory = str  # explicit: TEXT values returned as Python str (UTF-8)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id         TEXT PRIMARY KEY,
            title      TEXT NOT NULL DEFAULT 'Nuevo chat',
            context_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id           TEXT PRIMARY KEY,
            session_id   TEXT NOT NULL
                         REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role         TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            sequence     INTEGER NOT NULL,
            created_at   TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON chat_messages(session_id, sequence);
    """)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _row_to_session(row: sqlite3.Row) -> dict:
    return {
        "id":         row["id"],
        "title":      row["title"],
        "context_id": row["context_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# Sessions CRUD
# ---------------------------------------------------------------------------

def list_sessions() -> list[dict]:
    """Return all sessions ordered by updated_at desc (no messages)."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM chat_sessions ORDER BY updated_at DESC"
    ).fetchall()
    return [_row_to_session(r) for r in rows]


def create_session(session_id: str, title: str = "Nuevo chat") -> dict:
    """Insert a new session and return it. Caller provides the id."""
    now = _now()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO chat_sessions (id, title, context_id, created_at, updated_at)"
            " VALUES (?, ?, NULL, ?, ?)",
            (session_id, title, now, now),
        )
        conn.commit()
    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return _row_to_session(row)


def get_session(session_id: str) -> Optional[dict]:
    """Return session metadata (no messages). None if not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return _row_to_session(row) if row else None


def get_session_with_messages(session_id: str) -> Optional[dict]:
    """Return session + its messages list. None if not found."""
    conn  = _get_conn()
    srow  = conn.execute(
        "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if srow is None:
        return None
    session  = _row_to_session(srow)
    msg_rows = conn.execute(
        "SELECT payload_json FROM chat_messages"
        " WHERE session_id = ? ORDER BY sequence",
        (session_id,),
    ).fetchall()
    session["messages"] = [json.loads(r["payload_json"]) for r in msg_rows]
    return session


def update_session(
    session_id: str,
    *,
    title: Any = _UNSET,
    context_id: Any = _UNSET,
    messages: Any = _UNSET,
) -> Optional[dict]:
    """
    Update session fields. Only provided (non-UNSET) fields are changed.
    If `messages` is provided, replaces all messages for the session.
    Returns updated session (no messages) or None if not found.
    """
    with _lock:
        conn = _get_conn()
        if conn.execute(
            "SELECT 1 FROM chat_sessions WHERE id = ?", (session_id,)
        ).fetchone() is None:
            return None

        now = _now()
        if title is not _UNSET:
            conn.execute(
                "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, session_id),
            )
        if context_id is not _UNSET:
            conn.execute(
                "UPDATE chat_sessions SET context_id = ?, updated_at = ? WHERE id = ?",
                (context_id, now, session_id),
            )
        if messages is not _UNSET and messages is not None:
            conn.execute(
                "DELETE FROM chat_messages WHERE session_id = ?", (session_id,)
            )
            for seq, msg in enumerate(messages, 1):
                role = msg.get("role", "user") if isinstance(msg, dict) else "user"
                created_at = (
                    msg.get("createdAt") or msg.get("created_at") or now
                    if isinstance(msg, dict) else now
                )
                conn.execute(
                    "INSERT INTO chat_messages"
                    " (id, session_id, role, payload_json, sequence, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        _new_id(), session_id, role,
                        json.dumps(msg, ensure_ascii=False),
                        seq, created_at,
                    ),
                )
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        conn.commit()

    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return _row_to_session(row)


def delete_session(session_id: str) -> bool:
    """Delete session and cascade-delete its messages. Returns True if deleted."""
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "DELETE FROM chat_sessions WHERE id = ?", (session_id,)
        )
        conn.commit()
    return cur.rowcount > 0


def append_message(session_id: str, role: str, payload: dict) -> dict:
    """
    Append a single message to a session.
    payload is a dict matching the PersistedChatMessage shape (camelCase keys).
    """
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq"
            " FROM chat_messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        seq        = row["next_seq"]
        msg_id     = _new_id()
        now        = _now()
        conn.execute(
            "INSERT INTO chat_messages"
            " (id, session_id, role, payload_json, sequence, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, session_id, role, json.dumps(payload, ensure_ascii=False), seq, now),
        )
        conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        conn.commit()
    return {"id": msg_id, "session_id": session_id, "role": role,
            "payload": payload, "sequence": seq, "created_at": now}


def session_count() -> int:
    """Return total number of sessions (used for migration check)."""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0]


# ---------------------------------------------------------------------------
# M22 — Search helpers
# ---------------------------------------------------------------------------

def _extract_snippet(text: str, query: str, half: int = 110) -> str:
    """
    Return a ~220-char snippet centred on the first occurrence of query.
    Falls back to the first 220 chars if the query isn't found in text.
    Adds ellipsis markers when the snippet doesn't start/end at a boundary.
    """
    lower_t = text.lower()
    lower_q = query.lower()
    idx = lower_t.find(lower_q)
    if idx == -1:
        raw = text[:half * 2]
        return raw + ("\u2026" if len(text) > half * 2 else "")
    start = max(0, idx - half)
    end   = min(len(text), idx + len(query) + half)
    snippet = text[start:end]
    if start > 0:
        snippet = "\u2026" + snippet.lstrip()
    if end < len(text):
        snippet = snippet.rstrip() + "\u2026"
    return snippet


def _score_result(query: str, visible_text: str, session_title: str, role: str) -> int:
    """
    Simple relevance score used for post-fetch re-ranking.
    Higher is more relevant.  Tie-break preserves SQL created_at DESC order.

    Scoring:
      +20  query found in session title
      + 5  role == 'user'  (direct user input tends to be more readable)
      + 2  per query word (≥ 2 chars) found in visible_text
    """
    q_lower = query.lower()
    score = 0
    if q_lower in session_title.lower():
        score += 20
    if role == "user":
        score += 5
    for word in q_lower.split():
        if len(word) >= 2 and word in visible_text.lower():
            score += 2
    return score


def search_messages(query: str, limit: int = 50) -> list[dict]:
    """
    M22 — Full-text search across all persisted messages.

    Uses SQLite LIKE on payload_json (case-insensitive via COLLATE NOCASE).
    Results are re-ranked by a simple relevance score (title match > user role
    > word coverage) and then by recency within the same score tier.

    Each result's `text` field is a snippet centred on the first match,
    not a raw prefix of the payload.
    """
    conn = _get_conn()
    pattern = f"%{query}%"
    rows = conn.execute(
        """
        SELECT
            m.id          AS message_id,
            m.session_id,
            m.role,
            m.payload_json,
            m.created_at,
            s.title       AS session_title
        FROM  chat_messages  m
        JOIN  chat_sessions  s ON s.id = m.session_id
        WHERE m.payload_json LIKE ? COLLATE NOCASE
        ORDER BY m.created_at DESC
        LIMIT ?
        """,
        (pattern, limit),
    ).fetchall()

    results = []
    for row in rows:
        # Extract human-readable text; fall back to raw JSON on error
        raw = row["payload_json"]
        visible = raw
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                visible = str(
                    payload.get("content")
                    or payload.get("text")
                    or raw
                )
        except Exception:
            pass

        score   = _score_result(query, visible, row["session_title"], row["role"])
        snippet = _extract_snippet(visible, query)

        results.append({
            "messageId":    row["message_id"],
            "sessionId":    row["session_id"],
            "sessionTitle": row["session_title"],
            "text":         snippet,
            "createdAt":    row["created_at"],
            "_score":       score,
        })

    # Re-rank: score DESC; within same score keep SQL's created_at DESC order
    # (Python's sort is stable, so equal-score items stay in arrival order)
    results.sort(key=lambda r: -r["_score"])
    for r in results:
        del r["_score"]

    return results
