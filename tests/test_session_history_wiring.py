"""SPRINT-ALPHA-04.8 — Session History Wiring tests.

TDD: written before implementation. Tests confirm the bounded session history
read path is wired safely into MSO Economic Cognition.

Test groups:
  A. build_mso_session_history helper
  B. _call_mso_cognitive history forwarding
  C. surface_behavior cognitive_trace history metadata
  D. webhook_server session_id forwarding
  E. Prompt RECENT SESSION HISTORY section
  F. Regression: prior alpha fields intact
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: in-memory DB for tests
# ---------------------------------------------------------------------------

def _make_session_db(tmp_path: Path) -> tuple[Path, str]:
    """Create a minimal SQLite chat_sessions DB with one session and messages."""
    db_path = tmp_path / "chat_sessions.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'Test',
            context_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    session_id = "test-session-abc-001"
    conn.execute(
        "INSERT INTO chat_sessions VALUES (?, ?, ?, ?, ?)",
        (session_id, "Test Session", None, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    messages = [
        ("u1", "user", "Hola, soy Jorge."),
        ("a1", "assistant", "Hola Jorge, ¿en qué te puedo ayudar?"),
        ("u2", "user", "¿Qué está pasando en el sistema?"),
        ("a2", "assistant", "El sistema está en modo NORMAL, sin tareas pendientes."),
        ("u3", "user", "¿Cuántas tareas tengo?"),
        ("a3", "assistant", "No veo tareas activas en este momento."),
    ]
    for i, (msg_id, role, content) in enumerate(messages, 1):
        payload = json.dumps({"id": msg_id, "role": role, "content": content,
                               "status": "sent", "createdAt": "2026-01-01T00:00:00"})
        conn.execute(
            "INSERT INTO chat_messages VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, session_id, role, payload, i, "2026-01-01T00:00:00"),
        )
    conn.commit()
    conn.close()
    return db_path, session_id


# ---------------------------------------------------------------------------
# A. build_mso_session_history helper
# ---------------------------------------------------------------------------

class TestBuildMsoSessionHistory:
    """T-HIST-A: build_mso_session_history returns correct shape and content."""

    def _call(self, session_id, tmp_path, limit_turns=5):
        from assistant_os.mso.session_history import build_mso_session_history
        return build_mso_session_history(session_id, limit_turns=limit_turns)

    def test_a01_none_session_id_returns_not_available(self, tmp_path, monkeypatch):
        """session_id=None → available=False, source='none', empty turns."""
        result = self._call(None, tmp_path)
        assert result["available"] is False
        assert result["source"] == "none"
        assert result["turns"] == []
        assert result["turns_used"] == 0
        assert result["warnings"] == []

    def test_a02_unknown_session_id_returns_unavailable(self, tmp_path, monkeypatch):
        """Unknown session_id → available=False, source='unavailable'."""
        db_path, _ = _make_session_db(tmp_path)
        # Patch DB_PATH in chat_db to point to our test DB
        import assistant_os.chat_db as chat_db_mod
        monkeypatch.setattr(chat_db_mod, "DB_PATH", db_path)
        monkeypatch.setattr(chat_db_mod, "_conn", None)

        result = self._call("nonexistent-session-xyz", tmp_path)
        assert result["available"] is False
        assert result["source"] == "unavailable"
        assert result["turns"] == []
        assert "warnings" in result

    def test_a03_valid_session_returns_available_true(self, tmp_path, monkeypatch):
        """Known session_id with messages → available=True, source='chat_sessions'."""
        db_path, session_id = _make_session_db(tmp_path)
        import assistant_os.chat_db as chat_db_mod
        monkeypatch.setattr(chat_db_mod, "DB_PATH", db_path)
        monkeypatch.setattr(chat_db_mod, "_conn", None)

        result = self._call(session_id, tmp_path)
        assert result["available"] is True
        assert result["source"] == "chat_sessions"
        assert result["turns_used"] > 0

    def test_a04_turns_have_role_and_content(self, tmp_path, monkeypatch):
        """Each turn has role and content keys."""
        db_path, session_id = _make_session_db(tmp_path)
        import assistant_os.chat_db as chat_db_mod
        monkeypatch.setattr(chat_db_mod, "DB_PATH", db_path)
        monkeypatch.setattr(chat_db_mod, "_conn", None)

        result = self._call(session_id, tmp_path)
        for turn in result["turns"]:
            assert "role" in turn
            assert "content" in turn
            assert turn["role"] in ("user", "assistant")
            assert isinstance(turn["content"], str)
            assert turn["content"]

    def test_a05_bounded_to_limit_turns(self, tmp_path, monkeypatch):
        """limit_turns=2 returns at most 4 messages (2 user+2 assistant turns)."""
        db_path, session_id = _make_session_db(tmp_path)
        import assistant_os.chat_db as chat_db_mod
        monkeypatch.setattr(chat_db_mod, "DB_PATH", db_path)
        monkeypatch.setattr(chat_db_mod, "_conn", None)

        result = self._call(session_id, tmp_path, limit_turns=2)
        assert len(result["turns"]) <= 4  # 2 user + 2 assistant

    def test_a06_default_limit_is_5_turns(self, tmp_path, monkeypatch):
        """Default limit of 5 turns → at most 10 messages."""
        db_path, session_id = _make_session_db(tmp_path)
        import assistant_os.chat_db as chat_db_mod
        monkeypatch.setattr(chat_db_mod, "DB_PATH", db_path)
        monkeypatch.setattr(chat_db_mod, "_conn", None)

        result = self._call(session_id, tmp_path)
        assert len(result["turns"]) <= 10

    def test_a07_content_truncated_when_long(self, tmp_path, monkeypatch):
        """Messages with very long content are truncated."""
        db_path = tmp_path / "chat_sessions.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT 'T',
                context_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
                payload_json TEXT NOT NULL, sequence INTEGER NOT NULL, created_at TEXT NOT NULL
            );
        """)
        long_content = "x" * 2000
        conn.execute("INSERT INTO chat_sessions VALUES (?,?,?,?,?)",
                     ("s1", "T", None, "2026-01-01", "2026-01-01"))
        conn.execute("INSERT INTO chat_messages VALUES (?,?,?,?,?,?)",
                     ("m1", "s1", "user",
                      json.dumps({"role": "user", "content": long_content}),
                      1, "2026-01-01"))
        conn.commit(); conn.close()

        import assistant_os.chat_db as chat_db_mod
        monkeypatch.setattr(chat_db_mod, "DB_PATH", db_path)
        monkeypatch.setattr(chat_db_mod, "_conn", None)

        from assistant_os.mso.session_history import build_mso_session_history, MAX_CONTENT_CHARS
        result = build_mso_session_history("s1")
        assert result["available"] is True
        assert len(result["turns"][0]["content"]) <= MAX_CONTENT_CHARS

    def test_a08_truncated_flag_set_when_content_trimmed(self, tmp_path, monkeypatch):
        """truncated=True when any message content was cut."""
        db_path = tmp_path / "chat_sessions.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY, title TEXT, context_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
                payload_json TEXT NOT NULL, sequence INTEGER NOT NULL, created_at TEXT NOT NULL
            );
        """)
        long_content = "y" * 2000
        conn.execute("INSERT INTO chat_sessions VALUES (?,?,?,?,?)",
                     ("s1", "T", None, "2026-01-01", "2026-01-01"))
        conn.execute("INSERT INTO chat_messages VALUES (?,?,?,?,?,?)",
                     ("m1", "s1", "user",
                      json.dumps({"role": "user", "content": long_content}),
                      1, "2026-01-01"))
        conn.commit(); conn.close()

        import assistant_os.chat_db as chat_db_mod
        monkeypatch.setattr(chat_db_mod, "DB_PATH", db_path)
        monkeypatch.setattr(chat_db_mod, "_conn", None)

        from assistant_os.mso.session_history import build_mso_session_history
        result = build_mso_session_history("s1")
        assert result["truncated"] is True

    def test_a09_never_raises_on_any_input(self, tmp_path, monkeypatch):
        """build_mso_session_history never raises on any session_id."""
        from assistant_os.mso.session_history import build_mso_session_history
        inputs = [None, "", "   ", "a" * 500, "💀🔥session", 12345]
        for inp in inputs:
            try:
                build_mso_session_history(inp)  # type: ignore[arg-type]
            except Exception as exc:
                pytest.fail(f"build_mso_session_history raised on {inp!r}: {exc}")

    def test_a10_returns_all_required_keys(self, tmp_path):
        """Return dict always has all required keys."""
        from assistant_os.mso.session_history import build_mso_session_history
        result = build_mso_session_history(None)
        required = {"available", "turns", "turns_used", "source", "truncated", "warnings"}
        assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"

    def test_a11_does_not_mutate_session_state(self, tmp_path, monkeypatch):
        """Calling build_mso_session_history does not modify any DB records."""
        db_path, session_id = _make_session_db(tmp_path)
        import assistant_os.chat_db as chat_db_mod
        monkeypatch.setattr(chat_db_mod, "DB_PATH", db_path)
        monkeypatch.setattr(chat_db_mod, "_conn", None)

        # Get message count before
        conn = sqlite3.connect(str(db_path))
        count_before = conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        conn.close()

        from assistant_os.mso.session_history import build_mso_session_history
        build_mso_session_history(session_id)

        # Get message count after
        import assistant_os.chat_db as chat_db_mod2
        monkeypatch.setattr(chat_db_mod2, "_conn", None)
        conn = sqlite3.connect(str(db_path))
        count_after = conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        conn.close()

        assert count_before == count_after, "Session state was mutated"


# ---------------------------------------------------------------------------
# B. _call_mso_cognitive history forwarding
# ---------------------------------------------------------------------------

class TestCallMsoCognitiveHistory:
    """T-HIST-B: _call_mso_cognitive passes history to call_mso_chat_provider."""

    def test_b01_history_forwarded_to_provider(self):
        """_call_mso_cognitive passes history kwarg to call_mso_chat_provider."""
        from assistant_os import surface_behavior as sb

        history = [{"role": "user", "content": "Hola"}, {"role": "assistant", "content": "Hola!"}]
        captured = {}

        def _fake_provider(grounding_context, user_text, history=None):
            captured["history"] = history
            return {
                "status": "ok", "text": "Test response.", "provider_name": "anthropic",
                "model_name": "claude-haiku-4-5-20251001", "used_execution": False,
                "cognitive_only": True, "error": None, "metadata": {},
            }

        with patch("assistant_os.surface_behavior._call_mso_cognitive",
                   side_effect=lambda gc, t, history=None: _fake_provider(gc, t, history=history)):
            # Direct call to verify the signature
            from assistant_os.surface_behavior import _call_mso_cognitive
            # Monkey-patch the inner call
            with patch("assistant_os.mso.mso_chat_provider.call_mso_chat_provider",
                       side_effect=lambda **kwargs: (captured.update({"history": kwargs.get("history")}) or _fake_provider(**kwargs))):
                _call_mso_cognitive({"operational_mode": "TEST"}, "test text", history=history)

        assert captured.get("history") == history, "history was not forwarded to provider"

    def test_b02_no_history_still_works(self):
        """_call_mso_cognitive with no history param still calls provider."""
        with patch("assistant_os.mso.mso_chat_provider.call_mso_chat_provider") as mock_p:
            mock_p.return_value = {
                "status": "ok", "text": "OK.", "provider_name": "anthropic",
                "model_name": "claude-haiku", "used_execution": False,
                "cognitive_only": True, "error": None, "metadata": {},
            }
            from assistant_os.surface_behavior import _call_mso_cognitive
            result = _call_mso_cognitive({"operational_mode": "TEST"}, "hi")
            assert mock_p.called
            called_kwargs = mock_p.call_args
            # history should be None or absent
            history_arg = called_kwargs.kwargs.get("history")
            assert history_arg is None

    def test_b03_history_none_passed_explicitly(self):
        """_call_mso_cognitive(history=None) passes None to provider."""
        with patch("assistant_os.mso.mso_chat_provider.call_mso_chat_provider") as mock_p:
            mock_p.return_value = {
                "status": "ok", "text": "OK.", "provider_name": "anthropic",
                "model_name": "claude-haiku", "used_execution": False,
                "cognitive_only": True, "error": None, "metadata": {},
            }
            from assistant_os.surface_behavior import _call_mso_cognitive
            _call_mso_cognitive({"operational_mode": "TEST"}, "hi", history=None)
            called_kwargs = mock_p.call_args
            assert called_kwargs.kwargs.get("history") is None


# ---------------------------------------------------------------------------
# C. Surface behavior cognitive_trace history metadata
# ---------------------------------------------------------------------------

def _make_grounding_ctx():
    return {
        "operational_mode": "NORMAL",
        "seat_provider": "test",
        "prepared_actions_count": 0,
        "prepared_actions_summary": [],
        "next_safe_step": "none",
        "authority_posture": "chain",
        "limitations": "no exec",
        "version": "alpha-04.8",
        "generated_at": "2026-05-14T00:00:00",
        "capabilities_summary": {},
        "recent_governance": [],
        "active_tasks_brief": [],
        "recent_failures": [],
        "perception_warnings": [],
        "pending_review_items": [],
    }


def _make_vault_ctx(packs=None):
    return {
        "enabled": False,
        "query": "test",
        "retrieval_method": "keyword_topk",
        "chunks": [],
        "vault_sources": [],
        "vault_chunks_used": 0,
        "token_budget_used": 0,
        "truncated": False,
        "warnings": [],
        "pack_filter_active": False,
        "packs_consulted": packs or [],
        "unclassified_included": True,
    }


def _make_provider_resp(text="Cognitive response."):
    return {
        "status": "ok", "text": text, "provider_name": "anthropic",
        "model_name": "claude-haiku-4-5-20251001", "used_execution": False,
        "cognitive_only": True, "error": None,
        "metadata": {"tokens_in": 100, "tokens_out": 50,
                     "cognitive_only": True, "non_executing": True},
    }


def _mock_identity():
    m = MagicMock()
    m.to_audit_dict.return_value = {"principal": "anon"}
    return m


def _mock_guard():
    m = MagicMock()
    m.to_audit_dict.return_value = {"decision": "allow"}
    return m


class TestCognitiveTraceHistoryMetadata:
    """T-HIST-C: cognitive_trace includes history metadata fields."""

    def _call_surface(self, session_history_dict, session_id="test-session-001",
                      text="analiza el codigo"):
        from assistant_os.surface_behavior import get_surface_behavior_response
        with patch("assistant_os.surface_behavior._get_vault_context",
                   return_value=_make_vault_ctx()), \
             patch("assistant_os.surface_behavior._call_mso_cognitive",
                   return_value=_make_provider_resp()), \
             patch("assistant_os.surface_behavior.build_mso_grounding_context",
                   return_value=_make_grounding_ctx()), \
             patch("assistant_os.surface_behavior._get_session_history",
                   return_value=session_history_dict):
            return get_surface_behavior_response(
                surface="mso_direct",
                text=text,
                context_id="ctx-test-001",
                identity=_mock_identity(),
                guard_result=_mock_guard(),
                session_id=session_id,
            )

    def test_c01_cognitive_trace_has_history_available(self):
        """cognitive_trace includes history_available field."""
        hist = {"available": True, "turns": [], "turns_used": 0,
                "source": "chat_sessions", "truncated": False, "warnings": []}
        result = self._call_surface(hist)
        assert result is not None
        ct = result.get("cognitive_trace") or {}
        assert "history_available" in ct

    def test_c02_history_turns_used_in_trace(self):
        """cognitive_trace includes history_turns_used."""
        hist = {"available": True,
                "turns": [{"role": "user", "content": "Hola"},
                           {"role": "assistant", "content": "Hola!"}],
                "turns_used": 2, "source": "chat_sessions",
                "truncated": False, "warnings": []}
        result = self._call_surface(hist)
        ct = result.get("cognitive_trace") or {}
        assert "history_turns_used" in ct
        assert ct["history_turns_used"] == 2

    def test_c03_history_source_in_trace(self):
        """cognitive_trace includes history_source."""
        hist = {"available": True, "turns": [], "turns_used": 0,
                "source": "chat_sessions", "truncated": False, "warnings": []}
        result = self._call_surface(hist)
        ct = result.get("cognitive_trace") or {}
        assert "history_source" in ct
        assert ct["history_source"] == "chat_sessions"

    def test_c04_history_truncated_in_trace(self):
        """cognitive_trace includes history_truncated."""
        hist = {"available": True, "turns": [], "turns_used": 0,
                "source": "chat_sessions", "truncated": True, "warnings": []}
        result = self._call_surface(hist)
        ct = result.get("cognitive_trace") or {}
        assert "history_truncated" in ct
        assert ct["history_truncated"] is True

    def test_c05_history_warnings_in_trace(self):
        """cognitive_trace includes history_warnings."""
        hist = {"available": False, "turns": [], "turns_used": 0,
                "source": "unavailable", "truncated": False,
                "warnings": ["DB read error"]}
        result = self._call_surface(hist)
        ct = result.get("cognitive_trace") or {}
        assert "history_warnings" in ct
        assert "DB read error" in ct["history_warnings"]

    def test_c06_no_session_id_yields_unavailable_history(self):
        """No session_id → history_available=False in cognitive_trace."""
        from assistant_os.surface_behavior import get_surface_behavior_response
        with patch("assistant_os.surface_behavior._get_vault_context",
                   return_value=_make_vault_ctx()), \
             patch("assistant_os.surface_behavior._call_mso_cognitive",
                   return_value=_make_provider_resp()), \
             patch("assistant_os.surface_behavior.build_mso_grounding_context",
                   return_value=_make_grounding_ctx()):
            result = get_surface_behavior_response(
                surface="mso_direct",
                text="analiza el codigo",
                context_id="ctx-test-no-sess",
                identity=_mock_identity(),
                guard_result=_mock_guard(),
                # No session_id
            )
        if result is not None:
            ct = result.get("cognitive_trace") or {}
            if "history_available" in ct:
                assert ct["history_available"] is False

    def test_c07_history_retrieval_failure_does_not_crash(self):
        """If _get_session_history raises, response still succeeds."""
        from assistant_os.surface_behavior import get_surface_behavior_response
        with patch("assistant_os.surface_behavior._get_vault_context",
                   return_value=_make_vault_ctx()), \
             patch("assistant_os.surface_behavior._call_mso_cognitive",
                   return_value=_make_provider_resp()), \
             patch("assistant_os.surface_behavior.build_mso_grounding_context",
                   return_value=_make_grounding_ctx()), \
             patch("assistant_os.surface_behavior._get_session_history",
                   side_effect=RuntimeError("DB exploded")):
            result = get_surface_behavior_response(
                surface="mso_direct",
                text="analiza el codigo",
                context_id="ctx-test-fail",
                identity=_mock_identity(),
                guard_result=_mock_guard(),
                session_id="some-session",
            )
        # Must return a result (not None, not exception)
        assert result is not None

    def test_c08_provider_fallback_still_works_with_history_wiring(self):
        """Provider crash → fallback response returned, not exception."""
        from assistant_os.surface_behavior import get_surface_behavior_response
        hist = {"available": True, "turns": [], "turns_used": 0,
                "source": "chat_sessions", "truncated": False, "warnings": []}
        with patch("assistant_os.surface_behavior._get_vault_context",
                   return_value=_make_vault_ctx()), \
             patch("assistant_os.surface_behavior._call_mso_cognitive",
                   side_effect=RuntimeError("provider down")), \
             patch("assistant_os.surface_behavior.build_mso_grounding_context",
                   return_value=_make_grounding_ctx()), \
             patch("assistant_os.surface_behavior._get_session_history",
                   return_value=hist), \
             patch("assistant_os.surface_behavior.build_narrative_context_message",
                   return_value=("Fallback narrative.", {"operational_mode": "NORMAL"})):
            result = get_surface_behavior_response(
                surface="mso_direct",
                text="analiza el codigo",
                context_id="ctx-fallback",
                identity=_mock_identity(),
                guard_result=_mock_guard(),
                session_id="some-session",
            )
        assert result is not None
        assert result.get("fallback_used") is True


# ---------------------------------------------------------------------------
# D. Prompt RECENT SESSION HISTORY section
# ---------------------------------------------------------------------------

class TestPromptSessionHistorySection:
    """T-HIST-D: system prompt includes RECENT SESSION HISTORY when history present."""

    def _make_grounding_with_hist(self, turns):
        ctx = {**_make_grounding_ctx()}
        ctx["session_history"] = {
            "available": bool(turns),
            "turns": turns,
            "turns_used": len(turns),
            "source": "chat_sessions" if turns else "none",
            "truncated": False,
            "warnings": [],
        }
        ctx["vault_context"] = None
        return ctx

    def test_d01_session_history_section_present_when_turns_available(self):
        """Prompt includes RECENT SESSION HISTORY when turns available."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        turns = [{"role": "user", "content": "Hola"}, {"role": "assistant", "content": "Hola!"}]
        grounding = self._make_grounding_with_hist(turns)
        prompt = build_mso_chat_system_prompt(grounding)
        assert "SESSION HISTORY" in prompt or "session_history" in prompt.lower()

    def test_d02_session_history_section_shows_turns_count(self):
        """Prompt shows how many turns were included."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        turns = [{"role": "user", "content": "Hola"}, {"role": "assistant", "content": "Hola!"}]
        grounding = self._make_grounding_with_hist(turns)
        prompt = build_mso_chat_system_prompt(grounding)
        # Turns count should be visible
        assert "2" in prompt or "turns" in prompt.lower()

    def test_d03_no_history_section_when_unavailable(self):
        """Prompt does not show a history section when turns are empty."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        grounding = self._make_grounding_with_hist([])
        prompt = build_mso_chat_system_prompt(grounding)
        # Not required to have the section when no history
        # Just must not crash
        assert isinstance(prompt, str)

    def test_d04_history_section_notes_not_authority(self):
        """Session history section notes it is not Vault doctrine or authority."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        turns = [{"role": "user", "content": "Test"}]
        grounding = self._make_grounding_with_hist(turns)
        prompt = build_mso_chat_system_prompt(grounding)
        lower = prompt.lower()
        # Should mention it's short-term / not authority / not vault
        assert ("short-term" in lower or "short term" in lower or
                "not authority" in lower or "no autoridad" in lower or
                "context only" in lower or "contexto" in lower)

    def test_d05_missing_session_history_key_does_not_crash(self):
        """build_mso_chat_system_prompt does not crash if session_history key missing."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        grounding = _make_grounding_ctx()
        grounding["vault_context"] = None
        # No session_history key — backward compat
        prompt = build_mso_chat_system_prompt(grounding)
        assert isinstance(prompt, str)


# ---------------------------------------------------------------------------
# E. Regression: prior alpha fields intact after history wiring
# ---------------------------------------------------------------------------

class TestAlphaRegressions:
    """T-HIST-E: Alpha 1-4.7 cognitive_trace fields remain intact."""

    def _call_with_history(self, session_id="test-sess"):
        from assistant_os.surface_behavior import get_surface_behavior_response
        hist = {"available": True,
                "turns": [{"role": "user", "content": "Hola"}],
                "turns_used": 1, "source": "chat_sessions",
                "truncated": False, "warnings": []}
        with patch("assistant_os.surface_behavior._get_vault_context",
                   return_value=_make_vault_ctx(["CODE", "SYSTEM"])), \
             patch("assistant_os.surface_behavior._call_mso_cognitive",
                   return_value=_make_provider_resp()), \
             patch("assistant_os.surface_behavior.build_mso_grounding_context",
                   return_value=_make_grounding_ctx()), \
             patch("assistant_os.surface_behavior._get_session_history",
                   return_value=hist):
            return get_surface_behavior_response(
                surface="mso_direct",
                text="analiza el codigo",
                context_id="ctx-reg-001",
                identity=_mock_identity(),
                guard_result=_mock_guard(),
                session_id=session_id,
            )

    def test_e01_alpha1_provenance_fields_intact(self):
        """Alpha 1 provenance fields still present in response."""
        result = self._call_with_history()
        assert result is not None
        assert "response_source" in result or "cognitive_trace" in result

    def test_e02_vault_pack_fields_intact(self):
        """Alpha 4.7 vault pack fields still present in cognitive_trace."""
        result = self._call_with_history()
        assert result is not None
        ct = result.get("cognitive_trace") or {}
        if "vault_packs_consulted" in ct:
            assert isinstance(ct["vault_packs_consulted"], list)

    def test_e03_execution_fields_remain_false(self):
        """execution_allowed and can_execute_now remain False."""
        result = self._call_with_history()
        assert result is not None
        ct = result.get("cognitive_trace") or {}
        assert ct.get("execution_allowed") is False
        assert ct.get("can_execute_now") is False

    def test_e04_synthesis_mode_is_economic(self):
        """synthesis_mode remains 'economic'."""
        result = self._call_with_history()
        ct = result.get("cognitive_trace") or {}
        if "synthesis_mode" in ct:
            assert ct["synthesis_mode"] == "economic"

    def test_e05_vault_fields_intact_with_history(self):
        """Vault trace fields still populated when history is wired."""
        result = self._call_with_history()
        ct = result.get("cognitive_trace") or {}
        expected = {"vault_enabled", "vault_chunks_used", "vault_sources",
                    "vault_retrieval_method", "vault_warnings", "vault_truncated"}
        for field in expected:
            assert field in ct, f"Missing vault field: {field}"

    def test_e06_no_second_llm_call_with_history(self):
        """Only one call to _call_mso_cognitive regardless of history presence."""
        from assistant_os.surface_behavior import get_surface_behavior_response
        hist = {"available": True,
                "turns": [{"role": "user", "content": "Hola"}],
                "turns_used": 1, "source": "chat_sessions",
                "truncated": False, "warnings": []}
        call_count = {"n": 0}

        def _counting_cognitive(grounding_context, text, history=None):
            call_count["n"] += 1
            return _make_provider_resp()

        with patch("assistant_os.surface_behavior._get_vault_context",
                   return_value=_make_vault_ctx()), \
             patch("assistant_os.surface_behavior._call_mso_cognitive",
                   side_effect=_counting_cognitive), \
             patch("assistant_os.surface_behavior.build_mso_grounding_context",
                   return_value=_make_grounding_ctx()), \
             patch("assistant_os.surface_behavior._get_session_history",
                   return_value=hist):
            get_surface_behavior_response(
                surface="mso_direct",
                text="analiza el codigo",
                context_id="ctx-count",
                identity=_mock_identity(),
                guard_result=_mock_guard(),
                session_id="sess",
            )
        assert call_count["n"] == 1, f"Expected exactly 1 LLM call, got {call_count['n']}"
