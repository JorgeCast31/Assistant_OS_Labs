"""SPRINT-ALPHA-05.6: CognitiveUsageLedger tests.

Verifies:
1. Ledger records and lists recent records.
2. clear_for_tests clears records.
3. Conversational MSO mode with mocked provider tokens records tokens_in/tokens_out.
4. Conversational fallback records fallback_used=True with tokens null.
5. Planning mode records queue/prepared action id with tokens null.
6. Validation mode records read-only usage with tokens null.
7. Orchestration mode records governed usage with tokens null.
8. Invalid/None token values do not crash.
9. No execution flags are changed.
10. No productive authority primitives are imported/called.
"""
from __future__ import annotations

import inspect
import sys
import types

import pytest

from assistant_os.mso.capability_registry import reset_dynamic_capabilities
from assistant_os.mso.cognitive_usage_ledger import (
    CognitiveUsageRecord,
    clear_cognitive_usage_for_tests,
    list_recent_cognitive_usage,
    record_cognitive_usage,
)
from assistant_os.mso.task_registry import reset_task_registry
from assistant_os.surface_behavior import get_surface_behavior_response


class _AuditStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_audit_dict(self) -> dict:
        return dict(self._payload)


def _route(text: str, mso_context: dict | None = None, session_id: str | None = None) -> dict | None:
    return get_surface_behavior_response(
        surface="mso_direct",
        text=text,
        context_id="test-trace-001",
        identity=_AuditStub({"id": "test-user", "role": "operator"}),
        guard_result=_AuditStub({"passed": True}),
        session_id=session_id,
        mso_context=mso_context,
    )


@pytest.fixture(autouse=True)
def _reset_all_state():
    reset_dynamic_capabilities()
    reset_task_registry()
    clear_cognitive_usage_for_tests()
    try:
        from assistant_os.context_store import clear_store
        clear_store()
    except Exception:
        pass
    try:
        from assistant_os.mso.prepared_action_queue import clear_confirmable_action_queue_for_tests
        clear_confirmable_action_queue_for_tests()
    except Exception:
        pass
    yield
    reset_dynamic_capabilities()
    reset_task_registry()
    clear_cognitive_usage_for_tests()
    try:
        from assistant_os.context_store import clear_store
        clear_store()
    except Exception:
        pass
    try:
        from assistant_os.mso.prepared_action_queue import clear_confirmable_action_queue_for_tests
        clear_confirmable_action_queue_for_tests()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Test 1: Ledger records and lists recent records
# ---------------------------------------------------------------------------

def test_ledger_records_and_lists():
    rec = CognitiveUsageRecord(
        trace_id="trace-1",
        surface="mso_direct",
        interaction_mode="conversational",
        usage_kind="provider_call",
        tokens_in=42,
        tokens_out=7,
        zero_token_interaction=False,
    )
    returned = record_cognitive_usage(rec)
    assert returned is rec

    recent = list_recent_cognitive_usage(limit=10)
    assert len(recent) == 1
    entry = recent[0]
    assert entry["trace_id"] == "trace-1"
    assert entry["tokens_in"] == 42
    assert entry["tokens_out"] == 7
    assert entry["usage_kind"] == "provider_call"
    assert entry["zero_token_interaction"] is False
    assert "usage_id" in entry
    assert "created_at" in entry


# ---------------------------------------------------------------------------
# Test 2: clear_for_tests clears records
# ---------------------------------------------------------------------------

def test_clear_for_tests_clears_ledger():
    record_cognitive_usage(CognitiveUsageRecord(trace_id="x", surface="mso_direct"))
    record_cognitive_usage(CognitiveUsageRecord(trace_id="y", surface="mso_direct"))
    assert len(list_recent_cognitive_usage()) == 2

    clear_cognitive_usage_for_tests()
    assert list_recent_cognitive_usage() == []


# ---------------------------------------------------------------------------
# Test 3: Conversational mode with mocked provider tokens
# ---------------------------------------------------------------------------

def test_conversational_mode_records_provider_tokens(monkeypatch):
    fake_provider_resp = {
        "status": "ok",
        "text": "Hello from mock provider",
        "provider_name": "anthropic",
        "model_name": "claude-haiku-4-5-20251001",
        "metadata": {"tokens_in": 100, "tokens_out": 25},
    }

    import assistant_os.surface_behavior as sb
    monkeypatch.setattr(sb, "_call_mso_cognitive", lambda *a, **kw: fake_provider_resp)

    resp = _route(
        "hello",
        mso_context={"agent_seat": "mso", "interaction_mode": "conversational", "cognition_tier": "economic"},
        session_id="sess-abc",
    )
    assert resp is not None
    assert resp.get("execution_allowed") is False
    assert resp.get("can_execute_now") is False

    recent = list_recent_cognitive_usage(limit=5)
    assert len(recent) == 1
    rec = recent[0]
    assert rec["interaction_mode"] == "conversational"
    assert rec["usage_kind"] == "provider_call"
    assert rec["fallback_used"] is False
    assert rec["zero_token_interaction"] is False
    assert rec["tokens_in"] == 100
    assert rec["tokens_out"] == 25
    assert rec["provider_used"] == "anthropic"
    assert rec["model_used"] == "claude-haiku-4-5-20251001"
    assert rec["session_id"] == "sess-abc"
    assert rec["agent_seat"] == "mso"
    assert rec["effective_agent_seat"] == "mso"


# ---------------------------------------------------------------------------
# Test 4: Conversational fallback records fallback_used=True with tokens null
# ---------------------------------------------------------------------------

def test_conversational_fallback_records_fallback():
    import assistant_os.surface_behavior as sb

    def _raise(*a, **kw):
        raise RuntimeError("provider offline")

    import unittest.mock as mock
    with mock.patch.object(sb, "_call_mso_cognitive", side_effect=_raise):
        resp = _route(
            "hello",
            mso_context={"agent_seat": "mso", "interaction_mode": "conversational", "cognition_tier": "economic"},
        )

    assert resp is not None
    assert resp.get("execution_allowed") is False

    recent = list_recent_cognitive_usage(limit=5)
    assert len(recent) == 1
    rec = recent[0]
    assert rec["usage_kind"] == "provider_fallback"
    assert rec["fallback_used"] is True
    assert rec["fallback_reason"] is not None
    assert rec["tokens_in"] is None
    assert rec["tokens_out"] is None
    assert rec["zero_token_interaction"] is False


# ---------------------------------------------------------------------------
# Test 5: Planning mode records queue/prepared action id with tokens null
# ---------------------------------------------------------------------------

def test_planning_mode_records_queue_ids():
    resp = _route(
        "deploy the database migration",
        mso_context={"agent_seat": "mso", "interaction_mode": "planning", "cognition_tier": "economic"},
    )
    assert resp is not None
    assert resp.get("execution_allowed") is False
    assert resp.get("can_execute_now") is False

    recent = list_recent_cognitive_usage(limit=5)
    assert len(recent) == 1
    rec = recent[0]
    assert rec["interaction_mode"] == "planning"
    assert rec["usage_kind"] == "mode_interaction"
    assert rec["zero_token_interaction"] is True
    assert rec["tokens_in"] is None
    assert rec["tokens_out"] is None
    assert rec["response_source"] == "mso_mode_planning_prepared"
    # queue_entry_id may or may not be set depending on routing, but should not crash
    assert "queue_entry_id" in rec
    assert "prepared_action_id" in rec


# ---------------------------------------------------------------------------
# Test 6: Validation mode records read-only usage with tokens null
# ---------------------------------------------------------------------------

def test_validation_mode_records_read_only():
    resp = _route(
        "show me the queue",
        mso_context={"agent_seat": "mso", "interaction_mode": "validation", "cognition_tier": "economic"},
    )
    assert resp is not None
    assert resp.get("execution_allowed") is False
    assert resp.get("can_execute_now") is False

    recent = list_recent_cognitive_usage(limit=5)
    assert len(recent) == 1
    rec = recent[0]
    assert rec["interaction_mode"] == "validation"
    assert rec["usage_kind"] == "mode_interaction"
    assert rec["zero_token_interaction"] is True
    assert rec["tokens_in"] is None
    assert rec["tokens_out"] is None
    assert rec["response_source"] == "mso_mode_validation_read_only"


# ---------------------------------------------------------------------------
# Test 7: Orchestration mode records governed usage with tokens null
# ---------------------------------------------------------------------------

def test_orchestration_mode_records_governed():
    resp = _route(
        "execute the plan",
        mso_context={"agent_seat": "mso", "interaction_mode": "orchestration", "cognition_tier": "economic"},
    )
    assert resp is not None
    assert resp.get("execution_allowed") is False
    assert resp.get("can_execute_now") is False

    recent = list_recent_cognitive_usage(limit=5)
    assert len(recent) == 1
    rec = recent[0]
    assert rec["interaction_mode"] == "orchestration"
    assert rec["usage_kind"] == "mode_interaction"
    assert rec["zero_token_interaction"] is True
    assert rec["tokens_in"] is None
    assert rec["tokens_out"] is None
    assert rec["response_source"] == "mso_mode_orchestration_governed"


# ---------------------------------------------------------------------------
# Test 8: Invalid/None token values do not crash
# ---------------------------------------------------------------------------

def test_none_token_values_do_not_crash():
    rec = CognitiveUsageRecord(
        trace_id="t",
        surface="mso_direct",
        tokens_in=None,
        tokens_out=None,
        latency_ms=None,
        fallback_reason=None,
        prepared_action_id=None,
        queue_entry_id=None,
    )
    returned = record_cognitive_usage(rec)
    assert returned is rec

    recent = list_recent_cognitive_usage()
    assert len(recent) == 1
    assert recent[0]["tokens_in"] is None
    assert recent[0]["tokens_out"] is None
    assert recent[0]["latency_ms"] is None


# ---------------------------------------------------------------------------
# Test 9: No execution flags are changed by any mode
# ---------------------------------------------------------------------------

def test_no_execution_flags_changed_by_any_mode(monkeypatch):
    import assistant_os.surface_behavior as sb
    monkeypatch.setattr(
        sb,
        "_call_mso_cognitive",
        lambda *a, **kw: {"status": "ok", "text": "hi", "provider_name": "p", "model_name": "m", "metadata": {}},
    )

    modes = ["conversational", "planning", "validation", "orchestration"]
    for mode in modes:
        clear_cognitive_usage_for_tests()
        resp = _route(
            "test input for execution check",
            mso_context={"agent_seat": "mso", "interaction_mode": mode, "cognition_tier": "economic"},
        )
        assert resp is not None, f"mode={mode} returned None"
        assert resp.get("execution_allowed") is False, f"execution_allowed True in mode={mode}"
        assert resp.get("can_execute_now") is False, f"can_execute_now True in mode={mode}"


# ---------------------------------------------------------------------------
# Test 10: No productive authority primitives imported/called in ledger module
# ---------------------------------------------------------------------------

def test_no_authority_primitives_in_ledger_module():
    import ast
    import pathlib
    import tokenize
    import io

    ledger_path = pathlib.Path(__file__).parent.parent / "assistant_os" / "mso" / "cognitive_usage_ledger.py"
    source = ledger_path.read_text()

    # Strip all comments and string literals (docstrings) by parsing only non-string tokens.
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    code_only_parts = []
    for tok_type, tok_string, *_ in tokens:
        if tok_type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code_only_parts.append(tok_string)
    code_only = " ".join(code_only_parts)

    forbidden = [
        "token_issuer",
        "CapabilityToken",
        "OperationBinding",
        "AuthorizedPlan",
        "PoliceGate",
        "RunnerAPI",
        "issue_token",
    ]
    for name in forbidden:
        assert name not in code_only, (
            f"Forbidden authority primitive {name!r} found in cognitive_usage_ledger.py code"
        )
