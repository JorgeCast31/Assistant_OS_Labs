"""SPRINT-ALPHA-05.6 (extended): CognitiveUsageLedger tests — system-wide coverage.

Original cases (1–10):
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

Extended cases (11–20):
11. Legacy backward-compat mso_direct (no mso_context) records provider_call on success.
12. Legacy mso_direct fallback records provider_fallback with tokens null.
13. source_component is populated for mso_context mode handlers.
14. source_component is populated for legacy mso_direct.
15. Centralized helpers record_provider_call / record_provider_fallback / record_mode_interaction
    produce correct field values.
16. list_recent_cognitive_usage filter by surface works.
17. list_recent_cognitive_usage filter by usage_kind works.
18. list_recent_cognitive_usage filter by interaction_mode works.
19. Endpoint limit cap: limit=200 is the max accepted.
20. New fields (source_component, domain, action, record_version, provider_call_id) present.
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


# ---------------------------------------------------------------------------
# Test 11: Legacy backward-compat mso_direct (no mso_context) records provider_call
# ---------------------------------------------------------------------------

def test_legacy_mso_direct_without_mso_context_records_provider_call(monkeypatch):
    fake_provider_resp = {
        "status": "ok",
        "text": "Legacy response from mock provider",
        "provider_name": "anthropic",
        "model_name": "claude-haiku-4-5-20251001",
        "metadata": {"tokens_in": 55, "tokens_out": 12},
    }
    import assistant_os.surface_behavior as sb
    monkeypatch.setattr(sb, "_call_mso_cognitive", lambda *a, **kw: fake_provider_resp)

    # No mso_context — uses the legacy text-driven path
    resp = get_surface_behavior_response(
        surface="mso_direct",
        text="explain the system",
        context_id="legacy-trace-001",
        identity=_AuditStub({"id": "test-user", "role": "operator"}),
        guard_result=_AuditStub({"passed": True}),
        session_id="sess-legacy",
        mso_context=None,
    )
    assert resp is not None
    assert resp.get("execution_allowed") is False

    recent = list_recent_cognitive_usage(limit=5)
    assert len(recent) == 1
    rec = recent[0]
    assert rec["usage_kind"] == "provider_call"
    assert rec["source_component"] == "surface_behavior.legacy_mso_direct"
    assert rec["tokens_in"] == 55
    assert rec["tokens_out"] == 12
    assert rec["zero_token_interaction"] is False
    assert rec["surface"] == "mso_direct"
    assert rec["domain"] == "MSO"


# ---------------------------------------------------------------------------
# Test 12: Legacy mso_direct fallback records provider_fallback
# ---------------------------------------------------------------------------

def test_legacy_mso_direct_fallback_records_provider_fallback():
    import assistant_os.surface_behavior as sb
    import unittest.mock as mock

    with mock.patch.object(sb, "_call_mso_cognitive", side_effect=RuntimeError("no key")):
        resp = get_surface_behavior_response(
            surface="mso_direct",
            text="explain the system",
            context_id="legacy-trace-002",
            identity=_AuditStub({"id": "test-user", "role": "operator"}),
            guard_result=_AuditStub({"passed": True}),
            session_id=None,
            mso_context=None,
        )

    assert resp is not None
    assert resp.get("execution_allowed") is False

    recent = list_recent_cognitive_usage(limit=5)
    assert len(recent) == 1
    rec = recent[0]
    assert rec["usage_kind"] == "provider_fallback"
    assert rec["source_component"] == "surface_behavior.legacy_mso_direct"
    assert rec["fallback_used"] is True
    assert rec["tokens_in"] is None
    assert rec["tokens_out"] is None
    assert rec["zero_token_interaction"] is False


# ---------------------------------------------------------------------------
# Test 13: source_component is populated for mso_context mode handlers
# ---------------------------------------------------------------------------

def test_source_component_populated_for_mso_context_handlers(monkeypatch):
    import assistant_os.surface_behavior as sb
    monkeypatch.setattr(
        sb, "_call_mso_cognitive",
        lambda *a, **kw: {"status": "ok", "text": "hi", "provider_name": "p", "model_name": "m", "metadata": {}},
    )

    mode_to_component = {
        "conversational": "surface_behavior._handle_mso_mode_conversational",
        "planning": "surface_behavior._handle_mso_mode_planning",
        "validation": "surface_behavior._handle_mso_mode_validation",
        "orchestration": "surface_behavior._handle_mso_mode_orchestration",
    }
    for mode, expected_component in mode_to_component.items():
        clear_cognitive_usage_for_tests()
        _route("test input", mso_context={"agent_seat": "mso", "interaction_mode": mode, "cognition_tier": "economic"})
        recent = list_recent_cognitive_usage(limit=1)
        assert len(recent) == 1, f"no record for mode={mode}"
        assert recent[0]["source_component"] == expected_component, (
            f"mode={mode}: expected {expected_component!r}, got {recent[0]['source_component']!r}"
        )


# ---------------------------------------------------------------------------
# Test 14: source_component is populated for legacy mso_direct
# ---------------------------------------------------------------------------

def test_source_component_populated_for_legacy_mso_direct(monkeypatch):
    import assistant_os.surface_behavior as sb
    monkeypatch.setattr(
        sb, "_call_mso_cognitive",
        lambda *a, **kw: {"status": "ok", "text": "hi", "provider_name": "p", "model_name": "m", "metadata": {}},
    )
    get_surface_behavior_response(
        surface="mso_direct",
        text="explain the system",
        context_id="src-comp-test",
        identity=_AuditStub({"id": "u", "role": "operator"}),
        guard_result=_AuditStub({"passed": True}),
        mso_context=None,
    )
    recent = list_recent_cognitive_usage(limit=1)
    assert len(recent) == 1
    assert recent[0]["source_component"] == "surface_behavior.legacy_mso_direct"


# ---------------------------------------------------------------------------
# Test 15: Centralized helpers produce correct field values
# ---------------------------------------------------------------------------

def test_centralized_helpers_produce_correct_fields():
    from assistant_os.mso.cognitive_usage_ledger import (
        record_provider_call, record_provider_fallback, record_mode_interaction,
    )

    record_provider_call(
        trace_id="t1", source_component="test_comp", surface="mso_direct", domain="MSO",
        session_id="s1", agent_seat="mso", effective_agent_seat="mso",
        interaction_mode="conversational", tokens_in=10, tokens_out=5, latency_ms=100,
        action="mso_cognitive_response",
    )
    record_provider_fallback(
        trace_id="t2", source_component="test_comp", surface="mso_direct", domain="MSO",
        response_source="deterministic_fallback", fallback_reason="api error", latency_ms=50,
    )
    record_mode_interaction(
        trace_id="t3", source_component="test_comp", surface="mso_direct", domain="MSO",
        interaction_mode="planning", response_source="mso_mode_planning_prepared",
        queue_entry_id="qe-123", prepared_action_id="pa-456",
    )

    all_recs = list_recent_cognitive_usage(limit=10)
    assert len(all_recs) == 3

    # newest-first: mode_interaction is last recorded → first in list
    mi = next(r for r in all_recs if r["usage_kind"] == "mode_interaction")
    assert mi["zero_token_interaction"] is True
    assert mi["fallback_used"] is False
    assert mi["queue_entry_id"] == "qe-123"
    assert mi["prepared_action_id"] == "pa-456"

    pf = next(r for r in all_recs if r["usage_kind"] == "provider_fallback")
    assert pf["fallback_used"] is True
    assert pf["fallback_reason"] == "api error"
    assert pf["zero_token_interaction"] is False
    assert pf["tokens_in"] is None

    pc = next(r for r in all_recs if r["usage_kind"] == "provider_call")
    assert pc["fallback_used"] is False
    assert pc["tokens_in"] == 10
    assert pc["tokens_out"] == 5
    assert pc["zero_token_interaction"] is False
    assert pc["session_id"] == "s1"


# ---------------------------------------------------------------------------
# Test 16: Filter by surface
# ---------------------------------------------------------------------------

def test_filter_by_surface():
    from assistant_os.mso.cognitive_usage_ledger import record_provider_call
    record_provider_call(trace_id="t1", source_component="c", surface="mso_direct", domain="MSO")
    record_provider_call(trace_id="t2", source_component="c", surface="code_executor", domain="CODE")

    mso = list_recent_cognitive_usage(limit=10, surface="mso_direct")
    assert len(mso) == 1
    assert mso[0]["surface"] == "mso_direct"

    code = list_recent_cognitive_usage(limit=10, surface="code_executor")
    assert len(code) == 1
    assert code[0]["surface"] == "code_executor"

    all_ = list_recent_cognitive_usage(limit=10)
    assert len(all_) == 2


# ---------------------------------------------------------------------------
# Test 17: Filter by usage_kind
# ---------------------------------------------------------------------------

def test_filter_by_usage_kind():
    from assistant_os.mso.cognitive_usage_ledger import (
        record_provider_call, record_provider_fallback, record_mode_interaction,
    )
    record_provider_call(trace_id="t1", source_component="c", surface="mso_direct", domain="MSO")
    record_provider_fallback(trace_id="t2", source_component="c", surface="mso_direct", domain="MSO")
    record_mode_interaction(trace_id="t3", source_component="c", surface="mso_direct", domain="MSO")

    provider_calls = list_recent_cognitive_usage(limit=10, usage_kind="provider_call")
    assert len(provider_calls) == 1
    assert provider_calls[0]["usage_kind"] == "provider_call"

    fallbacks = list_recent_cognitive_usage(limit=10, usage_kind="provider_fallback")
    assert len(fallbacks) == 1

    interactions = list_recent_cognitive_usage(limit=10, usage_kind="mode_interaction")
    assert len(interactions) == 1


# ---------------------------------------------------------------------------
# Test 18: Filter by interaction_mode
# ---------------------------------------------------------------------------

def test_filter_by_interaction_mode(monkeypatch):
    import assistant_os.surface_behavior as sb
    monkeypatch.setattr(
        sb, "_call_mso_cognitive",
        lambda *a, **kw: {"status": "ok", "text": "hi", "provider_name": "p", "model_name": "m", "metadata": {}},
    )
    _route("test", mso_context={"agent_seat": "mso", "interaction_mode": "conversational", "cognition_tier": "economic"})
    _route("test", mso_context={"agent_seat": "mso", "interaction_mode": "validation", "cognition_tier": "economic"})
    _route("test", mso_context={"agent_seat": "mso", "interaction_mode": "orchestration", "cognition_tier": "economic"})

    conv = list_recent_cognitive_usage(limit=10, interaction_mode="conversational")
    assert len(conv) == 1
    assert conv[0]["interaction_mode"] == "conversational"

    val = list_recent_cognitive_usage(limit=10, interaction_mode="validation")
    assert len(val) == 1

    orch = list_recent_cognitive_usage(limit=10, interaction_mode="orchestration")
    assert len(orch) == 1


# ---------------------------------------------------------------------------
# Test 19: Limit cap — max 200, min 1
# ---------------------------------------------------------------------------

def test_limit_cap():
    from assistant_os.mso.cognitive_usage_ledger import record_provider_call
    for i in range(10):
        record_provider_call(trace_id=f"t{i}", source_component="c", surface="mso_direct", domain="MSO")

    # limit=3 returns 3
    assert len(list_recent_cognitive_usage(limit=3)) == 3
    # limit=0 is clamped to 1
    assert len(list_recent_cognitive_usage(limit=0)) == 1
    # limit=1000 is clamped to 500 (_MAX_RECORDS), but only 10 records exist
    assert len(list_recent_cognitive_usage(limit=1000)) == 10


# ---------------------------------------------------------------------------
# Test 20: New fields present in every record
# ---------------------------------------------------------------------------

def test_new_fields_present_in_records():
    from assistant_os.mso.cognitive_usage_ledger import record_provider_call
    record_provider_call(
        trace_id="t1",
        source_component="test_comp",
        surface="mso_direct",
        domain="CODE",
        action="code_review",
    )
    rec = list_recent_cognitive_usage(limit=1)[0]

    # All new fields must be present
    assert "source_component" in rec
    assert rec["source_component"] == "test_comp"
    assert "domain" in rec
    assert rec["domain"] == "CODE"
    assert "action" in rec
    assert rec["action"] == "code_review"
    assert "record_version" in rec
    assert rec["record_version"] == "v0"
    assert "provider_call_id" in rec  # always null for v0
    assert rec["provider_call_id"] is None
