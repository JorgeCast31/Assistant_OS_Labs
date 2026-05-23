"""Tests that mso_store supports isolated root override.

These tests MUST fail (ImportError on get_mso_store_root) until the override
seam is implemented in assistant_os/storage/mso_store.py.
"""
import pytest


def test_get_mso_store_root_returns_default_when_env_unset(monkeypatch):
    """Production default is returned when ASSISTANT_OS_MSO_STORE_ROOT is not set."""
    monkeypatch.delenv("ASSISTANT_OS_MSO_STORE_ROOT", raising=False)

    from assistant_os.storage.mso_store import get_mso_store_root
    from assistant_os.config import MEMORY_DIR

    assert get_mso_store_root() == MEMORY_DIR / "mso_store"


def test_get_mso_store_root_reads_env_override(monkeypatch, tmp_path):
    """get_mso_store_root() returns the env-override path when set."""
    override = tmp_path / "custom_store"
    monkeypatch.setenv("ASSISTANT_OS_MSO_STORE_ROOT", str(override))

    from assistant_os.storage.mso_store import get_mso_store_root

    assert get_mso_store_root() == override


def test_two_store_roots_do_not_share_records(monkeypatch, tmp_path):
    """Records written at root A are invisible when the root is switched to root B."""
    root_a = tmp_path / "store_a"
    root_b = tmp_path / "store_b"

    from assistant_os.mso.contracts import SovereignIntent
    from assistant_os.storage.mso_store import clear_mso_store, persist_intent, query_records

    def _intent(intent_id: str) -> SovereignIntent:
        return SovereignIntent(
            intent_id=intent_id,
            session_id="s",
            user_request_ref=f"r:{intent_id}",
            interpreted_goal="isolation test",
            priority="normal",
            persistence_recommendation="persist_trace_only",
            risk_posture_hint="normal",
            delegation_recommendation="none",
            justification_summary="test",
            timestamp="2026-01-01T00:00:00+00:00",
        )

    monkeypatch.setenv("ASSISTANT_OS_MSO_STORE_ROOT", str(root_a))
    clear_mso_store()
    persist_intent(_intent("intent-a1"))
    assert len(query_records(kind="intents")) == 1

    monkeypatch.setenv("ASSISTANT_OS_MSO_STORE_ROOT", str(root_b))
    assert len(query_records(kind="intents")) == 0, "Root B must not see Root A records"


def test_clear_mso_store_only_clears_configured_root(monkeypatch, tmp_path):
    """clear_mso_store() removes records only at the currently configured root."""
    root_a = tmp_path / "store_a"
    root_b = tmp_path / "store_b"

    from assistant_os.mso.contracts import SovereignIntent
    from assistant_os.storage.mso_store import clear_mso_store, persist_intent, query_records

    def _intent(intent_id: str) -> SovereignIntent:
        return SovereignIntent(
            intent_id=intent_id,
            session_id="s",
            user_request_ref=f"r:{intent_id}",
            interpreted_goal="clear test",
            priority="normal",
            persistence_recommendation="persist_trace_only",
            risk_posture_hint="normal",
            delegation_recommendation="none",
            justification_summary="test",
            timestamp="2026-01-01T00:00:00+00:00",
        )

    monkeypatch.setenv("ASSISTANT_OS_MSO_STORE_ROOT", str(root_a))
    clear_mso_store()
    persist_intent(_intent("intent-in-a"))
    assert len(query_records(kind="intents")) == 1

    monkeypatch.setenv("ASSISTANT_OS_MSO_STORE_ROOT", str(root_b))
    clear_mso_store()
    persist_intent(_intent("intent-in-b"))
    assert len(query_records(kind="intents")) == 1

    monkeypatch.setenv("ASSISTANT_OS_MSO_STORE_ROOT", str(root_a))
    clear_mso_store()
    assert len(query_records(kind="intents")) == 0, "Root A should be empty after clear"

    monkeypatch.setenv("ASSISTANT_OS_MSO_STORE_ROOT", str(root_b))
    assert len(query_records(kind="intents")) == 1, "Root B must still have its record"
