"""Phase 4 Economic Synthesis tests — SPRINT-ALPHA-04.

Tests 1-6:   Prompt structure contracts
Tests 7-10:  surface_behavior cognitive_trace contracts
Tests 11-15: Regression + audit tests
Validation:  mso_chat_provider execution-claim patterns
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_grounding(vault_context=None, version="alpha-02") -> dict:
    return {
        "operational_mode": "NORMAL",
        "seat_provider": "test-provider",
        "prepared_actions_count": 0,
        "prepared_actions_summary": [],
        "next_safe_step": "Continue observing",
        "authority_posture": "MSO → Policy → Police → Pipeline",
        "limitations": "You cannot execute. You cannot issue tokens.",
        "version": version,
        "generated_at": "2026-05-13T00:00:00",
        "capabilities_summary": {},
        "recent_governance": [],
        "active_tasks_brief": [],
        "recent_failures": [],
        "perception_warnings": [],
        "vault_context": vault_context,
    }


def _make_vault_ctx_enabled(tmp_path) -> dict:
    """Build a minimal enabled vault context with one chunk."""
    return {
        "enabled": True,
        "query": "test query",
        "retrieval_method": "keyword_topk",
        "chunks": [
            {
                "note_path": str(tmp_path / "budget.md"),
                "title": "Budget Framework",
                "tags": ["budget", "planning"],
                "frontmatter": {"status": "stable"},
                "content": "Budget planning doctrine and stable principles.",
                "score": 0.9,
            }
        ],
        "vault_sources": [str(tmp_path / "budget.md")],
        "vault_chunks_used": 1,
        "token_budget_used": 10,
        "truncated": False,
        "warnings": [],
    }


def _make_vault_ctx_disabled() -> dict:
    return {
        "enabled": False,
        "query": "test query",
        "retrieval_method": "keyword_topk",
        "chunks": [],
        "vault_sources": [],
        "vault_chunks_used": 0,
        "token_budget_used": 0,
        "truncated": False,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Test 1: Prompt includes ECONOMIC SYNTHESIS TASK section
# ---------------------------------------------------------------------------

def test_prompt_includes_economic_synthesis_task():
    from assistant_os.mso.prompts import build_mso_chat_system_prompt
    grounding = _make_grounding()
    prompt = build_mso_chat_system_prompt(grounding)
    assert "ECONOMIC SYNTHESIS TASK" in prompt


# ---------------------------------------------------------------------------
# Test 2: Prompt keeps SYSTEM PERCEPTION FRAME and VAULT SEMANTIC CONTEXT separate
# ---------------------------------------------------------------------------

def test_prompt_keeps_sections_separate():
    from assistant_os.mso.prompts import build_mso_chat_system_prompt
    grounding = _make_grounding()
    prompt = build_mso_chat_system_prompt(grounding)
    assert "SYSTEM PERCEPTION FRAME" in prompt
    assert "VAULT SEMANTIC CONTEXT" in prompt
    # ECONOMIC SYNTHESIS TASK must come AFTER both data sections
    econ_pos = prompt.find("ECONOMIC SYNTHESIS TASK")
    perception_pos = prompt.find("SYSTEM PERCEPTION FRAME")
    vault_pos = prompt.find("VAULT SEMANTIC CONTEXT")
    assert perception_pos < econ_pos
    assert vault_pos < econ_pos


# ---------------------------------------------------------------------------
# Test 3: Prompt includes Vault source metadata when chunks exist
# ---------------------------------------------------------------------------

def test_prompt_includes_vault_source_metadata_when_chunks_exist(tmp_path):
    from assistant_os.mso.prompts import build_mso_chat_system_prompt
    vault_ctx = _make_vault_ctx_enabled(tmp_path)
    grounding = _make_grounding(vault_context=vault_ctx)
    prompt = build_mso_chat_system_prompt(grounding)
    assert "VAULT SEMANTIC CONTEXT" in prompt
    assert "Budget Framework" in prompt
    assert "Retrieval enabled: yes" in prompt


# ---------------------------------------------------------------------------
# Test 4: Prompt clearly says Vault disabled/empty when no chunks exist
# ---------------------------------------------------------------------------

def test_prompt_vault_disabled_says_no_context():
    from assistant_os.mso.prompts import build_mso_chat_system_prompt
    vault_ctx = _make_vault_ctx_disabled()
    grounding = _make_grounding(vault_context=vault_ctx)
    prompt = build_mso_chat_system_prompt(grounding)
    assert "VAULT SEMANTIC CONTEXT" in prompt
    assert any(phrase in prompt for phrase in [
        "Retrieval enabled: no",
        "No relevant chunks",
        "No stable Vault context",
        "no stable vault context",
    ])


# ---------------------------------------------------------------------------
# Test 5: Prompt instructs model not to invent capabilities/state
# ---------------------------------------------------------------------------

def test_prompt_instructs_model_not_to_invent():
    from assistant_os.mso.prompts import build_mso_chat_system_prompt
    grounding = _make_grounding()
    prompt = build_mso_chat_system_prompt(grounding)
    assert any(phrase in prompt.lower() for phrase in [
        "do not invent",
        "no inventes",
        "not listed in",
    ])


# ---------------------------------------------------------------------------
# Test 6: Prompt instructs model not to claim execution
# ---------------------------------------------------------------------------

def test_prompt_instructs_model_not_to_claim_execution():
    from assistant_os.mso.prompts import build_mso_chat_system_prompt
    grounding = _make_grounding()
    prompt = build_mso_chat_system_prompt(grounding)
    assert any(phrase in prompt.lower() for phrase in [
        "do not claim you have executed",
        "do not claim to have executed",
        "cannot execute",
        "no puede ejecutar",
        "real execution requires",
    ])


# ---------------------------------------------------------------------------
# Validation pattern tests (mso_chat_provider._validate_provider_text)
# ---------------------------------------------------------------------------

def test_validate_rejects_approved_claim():
    from assistant_os.mso.mso_chat_provider import _validate_provider_text
    assert _validate_provider_text("I approved the request.") is not None
    assert _validate_provider_text("He aprobado la acción.") is not None


def test_validate_rejects_token_issued_claim():
    from assistant_os.mso.mso_chat_provider import _validate_provider_text
    assert _validate_provider_text("I issued a token for the operation.") is not None
    assert _validate_provider_text("Se emitió un token automáticamente.") is not None


def test_validate_rejects_system_changed_claim():
    from assistant_os.mso.mso_chat_provider import _validate_provider_text
    assert _validate_provider_text("I changed the system configuration.") is not None
    assert _validate_provider_text("Cambié el sistema de autenticación.") is not None


def test_validate_allows_legitimate_economic_response():
    from assistant_os.mso.mso_chat_provider import _validate_provider_text
    legitimate = (
        "El sistema está en modo NORMAL. No hay acciones pendientes. "
        "El próximo paso seguro es revisar las acciones preparadas antes de confirmar."
    )
    assert _validate_provider_text(legitimate) is None


# ---------------------------------------------------------------------------
# Tests 7-10: surface_behavior cognitive_trace contracts
# ---------------------------------------------------------------------------

def _make_ok_provider_response(text="Sistema en modo NORMAL."):
    return {
        "status": "ok",
        "text": text,
        "provider_name": "anthropic",
        "model_name": "claude-haiku-4-5-20251001",
        "used_execution": False,
        "cognitive_only": True,
        "error": None,
        "metadata": {"tokens_in": 100, "tokens_out": 50},
    }


def _make_unavailable_provider_response(reason="key not configured"):
    return {
        "status": "unavailable",
        "text": "",
        "provider_name": "anthropic",
        "model_name": "claude-haiku-4-5-20251001",
        "used_execution": False,
        "cognitive_only": True,
        "error": reason,
        "metadata": {},
    }


def _disabled_vault(query="test"):
    return {
        "enabled": False,
        "query": query,
        "retrieval_method": "keyword_topk",
        "chunks": [],
        "vault_sources": [],
        "vault_chunks_used": 0,
        "token_budget_used": 0,
        "truncated": False,
        "warnings": [],
    }


def test_llm_economic_response_includes_synthesis_mode_in_cognitive_trace(monkeypatch):
    """Test 7: cognitive_trace must include synthesis_mode='economic' on llm_economic path."""
    from assistant_os import surface_behavior as sb

    monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_ok_provider_response())
    monkeypatch.setattr(sb, "_get_vault_context", lambda query: _disabled_vault(query))

    resp = sb.get_surface_behavior_response(
        surface="mso_direct",
        text="qué ves del sistema",
        context_id="test-ctx",
        identity=None,
        guard_result=None,
    )
    assert resp is not None
    trace = resp.get("cognitive_trace") or {}
    assert trace.get("synthesis_mode") == "economic"


def test_llm_economic_response_includes_vault_trace_fields(monkeypatch):
    """Test 8: cognitive_trace includes all vault trace fields on llm_economic path."""
    from assistant_os import surface_behavior as sb

    vault_ctx = {
        "enabled": True,
        "query": "test",
        "retrieval_method": "keyword_topk",
        "chunks": [],
        "vault_sources": ["/some/note.md"],
        "vault_chunks_used": 1,
        "token_budget_used": 10,
        "truncated": False,
        "warnings": [],
    }
    monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_ok_provider_response())
    monkeypatch.setattr(sb, "_get_vault_context", lambda query: vault_ctx)

    resp = sb.get_surface_behavior_response(
        surface="mso_direct",
        text="qué significa provider_unavailable",
        context_id="test-ctx",
        identity=None,
        guard_result=None,
    )
    assert resp is not None
    trace = resp.get("cognitive_trace") or {}
    assert "vault_enabled" in trace
    assert "vault_chunks_used" in trace
    assert "vault_sources" in trace
    assert "vault_retrieval_method" in trace
    assert "vault_warnings" in trace
    assert "vault_truncated" in trace
    assert trace["vault_chunks_used"] == 1
    assert trace["vault_sources"] == ["/some/note.md"]


def test_fallback_works_when_vault_disabled(monkeypatch):
    """Test 9: fallback to narrative when provider fails and vault is disabled."""
    from assistant_os import surface_behavior as sb

    monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_unavailable_provider_response("ANTHROPIC_API_KEY not configured"))
    monkeypatch.setattr(sb, "_get_vault_context", lambda query: _disabled_vault(query))

    resp = sb.get_surface_behavior_response(
        surface="mso_direct",
        text="cuáles son tus límites",
        context_id="test-ctx",
        identity=None,
        guard_result=None,
    )
    assert resp is not None
    assert resp.get("response_source") in ("provider_unavailable", "deterministic_fallback", "deterministic_narrative")
    assert resp.get("fallback_used") is True


def test_fallback_works_when_vault_retrieval_raises(monkeypatch):
    """Test 10: surface_behavior does not raise when vault retrieval raises."""
    from assistant_os import surface_behavior as sb

    def _raise_vault(query):
        raise RuntimeError("disk error")

    monkeypatch.setattr(sb, "_get_vault_context", _raise_vault)
    monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_unavailable_provider_response())

    # Must not propagate exception — either returns a response or None
    try:
        resp = sb.get_surface_behavior_response(
            surface="mso_direct",
            text="cuál es el próximo paso",
            context_id="test-ctx",
            identity=None,
            guard_result=None,
        )
        # None is acceptable (outer try/except caught the vault error)
    except Exception as exc:
        pytest.fail(f"surface_behavior raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# Tests 11-13: Alpha 1/2/3 regression — provenance and trace fields intact
# ---------------------------------------------------------------------------

def test_alpha1_provenance_fields_intact(monkeypatch):
    """Test 11: llm_economic response preserves Alpha 1 provenance fields."""
    from assistant_os import surface_behavior as sb

    monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_ok_provider_response())
    monkeypatch.setattr(sb, "_get_vault_context", lambda query: _disabled_vault(query))

    resp = sb.get_surface_behavior_response(
        surface="mso_direct",
        text="qué ves del sistema",
        context_id="test-ctx",
        identity=None,
        guard_result=None,
    )
    assert resp is not None
    assert resp.get("response_source") == "llm_economic"
    assert resp.get("execution_status") == "real"
    assert resp.get("provider_used") == "anthropic"
    assert resp.get("model_used") == "claude-haiku-4-5-20251001"
    assert resp.get("cognitive_generation") is True
    assert resp.get("fallback_used") is False
    assert resp.get("execution_allowed") is False
    assert resp.get("can_execute_now") is False


def test_alpha2_perception_frame_fields_in_narrative_context(monkeypatch):
    """Test 12: llm_economic narrative_context includes Alpha 2 perception frame data."""
    from assistant_os import surface_behavior as sb

    monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_ok_provider_response())
    monkeypatch.setattr(sb, "_get_vault_context", lambda query: _disabled_vault(query))

    resp = sb.get_surface_behavior_response(
        surface="mso_direct",
        text="qué ves del sistema",
        context_id="test-ctx",
        identity=None,
        guard_result=None,
    )
    assert resp is not None
    ctx = resp.get("narrative_context") or {}
    assert ctx.get("execution_allowed") is False
    assert ctx.get("can_execute_now") is False


def test_alpha3_vault_trace_fields_present(monkeypatch):
    """Test 13: Alpha 3 vault fields are present in cognitive_trace on llm_economic."""
    from assistant_os import surface_behavior as sb

    monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_ok_provider_response())
    monkeypatch.setattr(sb, "_get_vault_context", lambda query: _disabled_vault(query))

    resp = sb.get_surface_behavior_response(
        surface="mso_direct",
        text="qué ves del sistema",
        context_id="test-ctx",
        identity=None,
        guard_result=None,
    )
    assert resp is not None
    trace = resp.get("cognitive_trace") or {}
    assert "vault_enabled" in trace
    assert "vault_chunks_used" in trace
    assert "vault_sources" in trace
    assert "vault_retrieval_method" in trace
    assert "vault_warnings" in trace
    assert "vault_truncated" in trace


# ---------------------------------------------------------------------------
# Test 14: No second LLM call introduced (audit test)
# ---------------------------------------------------------------------------

def test_no_second_llm_call(monkeypatch):
    """Test 14: Only one call to _call_mso_cognitive per mso_direct request."""
    from assistant_os import surface_behavior as sb

    call_count = {"n": 0}

    def _counting_cognitive(gc, text):
        call_count["n"] += 1
        return _make_ok_provider_response()

    monkeypatch.setattr(sb, "_call_mso_cognitive", _counting_cognitive)
    monkeypatch.setattr(sb, "_get_vault_context", lambda query: _disabled_vault(query))

    sb.get_surface_behavior_response(
        surface="mso_direct",
        text="qué ves del sistema",
        context_id="test-ctx",
        identity=None,
        guard_result=None,
    )
    assert call_count["n"] == 1, f"Expected 1 LLM call, got {call_count['n']}"


# ---------------------------------------------------------------------------
# Test 15: Authority/Police/Machine Operator files not imported in surface_behavior
# ---------------------------------------------------------------------------

def test_no_authority_imports_in_surface_behavior():
    """Test 15: surface_behavior must not import from police, machine_operator_policy, or operator_auth."""
    import ast
    import pathlib

    sb_path = pathlib.Path(__file__).parent.parent / "assistant_os" / "surface_behavior.py"
    tree = ast.parse(sb_path.read_text(encoding="utf-8"))

    forbidden_modules = {
        "machine_operator_policy",
        "operator_auth",
        "police_delegated_seat_validator",
        "machine_operator_adapter",
    }

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                for forbidden in forbidden_modules:
                    assert forbidden not in node.module, (
                        f"surface_behavior.py imports from forbidden module: {node.module}"
                    )
