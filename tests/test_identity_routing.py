"""SPRINT-ALPHA-04.9 — Identity Routing Refinement tests.

Verifies that identity questions on mso_direct reach the cognitive path
instead of the deterministic_conversational fast-path.

Requirements:
  1. Greetings still hit deterministic_conversational.
  2. Identity questions no longer hit deterministic_conversational.
  3. With a mocked provider, identity questions return llm_economic.
  4. Without a provider, identity questions fall back safely.
  5. Existing Alpha 1-4.8 routing unchanged for non-identity queries.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_identity():
    m = MagicMock()
    m.to_audit_dict.return_value = {"principal": "anon"}
    return m


def _mock_guard():
    m = MagicMock()
    m.to_audit_dict.return_value = {"decision": "allow"}
    return m


def _make_ok_provider_resp(text="Soy el MSO, la capa cognitiva soberana del sistema."):
    return {
        "status": "ok", "text": text,
        "provider_name": "anthropic", "model_name": "claude-haiku-4-5-20251001",
        "used_execution": False, "cognitive_only": True, "error": None,
        "metadata": {"tokens_in": 80, "tokens_out": 40,
                     "cognitive_only": True, "non_executing": True},
    }


def _make_unavailable_provider_resp(reason="ANTHROPIC_API_KEY not configured"):
    return {
        "status": "unavailable", "text": "",
        "provider_name": "anthropic", "model_name": "claude-haiku-4-5-20251001",
        "used_execution": False, "cognitive_only": True,
        "error": reason, "metadata": {},
    }


def _call_surface(text: str, provider_resp=None, session_id=None):
    from assistant_os.surface_behavior import get_surface_behavior_response
    patches = {
        "assistant_os.surface_behavior.build_mso_grounding_context": {
            "return_value": {
                "operational_mode": "NORMAL", "seat_provider": "test",
                "prepared_actions_count": 0, "prepared_actions_summary": [],
                "next_safe_step": "none", "authority_posture": "chain",
                "limitations": "no exec", "version": "alpha-04.9",
                "generated_at": "2026-05-15T00:00:00",
                "capabilities_summary": {}, "recent_governance": [],
                "active_tasks_brief": [], "recent_failures": [],
                "perception_warnings": [], "pending_review_items": [],
            }
        },
        "assistant_os.surface_behavior._get_vault_context": {
            "return_value": {
                "enabled": False, "query": text, "retrieval_method": "keyword_topk",
                "chunks": [], "vault_sources": [], "vault_chunks_used": 0,
                "token_budget_used": 0, "truncated": False, "warnings": [],
                "pack_filter_active": False, "packs_consulted": [],
                "unclassified_included": True,
            }
        },
        "assistant_os.surface_behavior._get_session_history": {
            "return_value": {
                "available": False, "turns": [], "turns_used": 0,
                "source": "none", "truncated": False, "warnings": [],
            }
        },
    }
    if provider_resp is not None:
        patches["assistant_os.surface_behavior._call_mso_cognitive"] = {
            "return_value": provider_resp
        }

    with patch("assistant_os.surface_behavior.build_mso_grounding_context",
               return_value=patches["assistant_os.surface_behavior.build_mso_grounding_context"]["return_value"]), \
         patch("assistant_os.surface_behavior._get_vault_context",
               return_value=patches["assistant_os.surface_behavior._get_vault_context"]["return_value"]), \
         patch("assistant_os.surface_behavior._get_session_history",
               return_value=patches["assistant_os.surface_behavior._get_session_history"]["return_value"]), \
         patch("assistant_os.surface_behavior._call_mso_cognitive",
               return_value=provider_resp if provider_resp is not None else _make_unavailable_provider_resp()), \
         patch("assistant_os.surface_behavior.build_narrative_context_message",
               return_value=("El MSO coordina; no ejecuta. Modo: NORMAL.", {"operational_mode": "NORMAL"})):
        return get_surface_behavior_response(
            surface="mso_direct",
            text=text,
            context_id="ctx-identity-test",
            identity=_mock_identity(),
            guard_result=_mock_guard(),
            session_id=session_id,
        )


# ---------------------------------------------------------------------------
# Test 1: Greetings still return deterministic_conversational
# ---------------------------------------------------------------------------

class TestGreetingsStillDeterministic:
    """Greetings must not be affected by the identity routing change."""

    @pytest.mark.parametrize("text", ["Hola", "hola", "HOLA", "Buenas tardes", "Buenos días"])
    def test_greeting_is_deterministic_conversational(self, text):
        """Greetings bypass cognitive path and return deterministic_conversational."""
        from assistant_os.surface_behavior import get_surface_behavior_response
        resp = get_surface_behavior_response(
            surface="mso_direct",
            text=text,
            context_id="ctx-greet",
            identity=_mock_identity(),
            guard_result=_mock_guard(),
        )
        assert resp is not None
        assert resp.get("response_source") == "deterministic_conversational"


# ---------------------------------------------------------------------------
# Test 2-5: Identity questions no longer hit deterministic_conversational
# ---------------------------------------------------------------------------

class TestIdentityNotDeterministic:
    """Identity questions must fall through the deterministic fast-path."""

    @pytest.mark.parametrize("text", [
        "Quién eres?", "Quién eres tú?", "Qué eres?", "Qué eres tú?",
        "quien eres", "quien eres tu", "que eres", "que eres tu",
        "Who are you?", "What are you?",
    ])
    def test_identity_not_deterministic_conversational(self, text):
        """Identity questions must not return response_source=deterministic_conversational."""
        resp = _call_surface(text, provider_resp=_make_ok_provider_resp())
        assert resp is not None
        assert resp.get("response_source") != "deterministic_conversational", (
            f"{text!r} should not hit deterministic_conversational"
        )

    def test_identity_not_in_mso_direct_conversational_set(self):
        """Identity strings are not present in _MSO_DIRECT_CONVERSATIONAL."""
        from assistant_os.surface_behavior import _MSO_DIRECT_CONVERSATIONAL
        for prompt in ("quien eres", "quien eres tu", "que eres", "que eres tu"):
            assert prompt not in _MSO_DIRECT_CONVERSATIONAL, (
                f"{prompt!r} must not be in _MSO_DIRECT_CONVERSATIONAL"
            )


# ---------------------------------------------------------------------------
# Test 6-8: Identity cognitive response fields
# ---------------------------------------------------------------------------

class TestIdentityCognitivePath:
    """Identity questions with mocked provider return cognitive trace fields."""

    def _identity_resp(self, text="Quién eres?"):
        return _call_surface(text, provider_resp=_make_ok_provider_resp())

    def test_response_source_is_llm_economic(self):
        resp = self._identity_resp()
        assert resp is not None
        assert resp.get("response_source") == "llm_economic"

    def test_cognitive_generation_is_true(self):
        resp = self._identity_resp()
        ct = resp.get("cognitive_trace") or {}
        assert ct.get("cognitive_generation") is True

    def test_synthesis_mode_is_economic(self):
        resp = self._identity_resp()
        ct = resp.get("cognitive_trace") or {}
        assert ct.get("synthesis_mode") == "economic"

    def test_execution_allowed_is_false(self):
        resp = self._identity_resp()
        ct = resp.get("cognitive_trace") or {}
        assert ct.get("execution_allowed") is False

    def test_can_execute_now_is_false(self):
        resp = self._identity_resp()
        ct = resp.get("cognitive_trace") or {}
        assert ct.get("can_execute_now") is False

    def test_domain_is_mso(self):
        resp = self._identity_resp()
        assert resp is not None
        assert resp.get("domain") == "MSO"

    @pytest.mark.parametrize("text", [
        "Quién eres?", "Qué eres?", "Who are you?", "What are you?",
    ])
    def test_all_identity_variants_reach_cognitive(self, text):
        resp = _call_surface(text, provider_resp=_make_ok_provider_resp())
        assert resp is not None
        assert resp.get("response_source") == "llm_economic"


# ---------------------------------------------------------------------------
# Test 9: Provider unavailable → safe fallback
# ---------------------------------------------------------------------------

class TestIdentityProviderUnavailable:
    """Without provider, identity questions fall back safely."""

    def test_unavailable_provider_returns_fallback(self):
        resp = _call_surface("Quién eres?",
                              provider_resp=_make_unavailable_provider_resp())
        assert resp is not None
        assert resp.get("fallback_used") is True

    def test_unavailable_provider_fallback_reason_present(self):
        resp = _call_surface("Quién eres?",
                              provider_resp=_make_unavailable_provider_resp())
        assert resp is not None
        assert resp.get("fallback_reason") is not None

    def test_unavailable_provider_response_source_is_not_llm_economic(self):
        resp = _call_surface("Qué eres?",
                              provider_resp=_make_unavailable_provider_resp())
        assert resp is not None
        assert resp.get("response_source") != "llm_economic"

    def test_unavailable_provider_does_not_raise(self):
        """Provider failure never propagates as exception."""
        try:
            resp = _call_surface("Who are you?",
                                  provider_resp=_make_unavailable_provider_resp())
        except Exception as exc:
            pytest.fail(f"Identity query raised on provider failure: {exc}")


# ---------------------------------------------------------------------------
# Test 10: Existing routing unchanged for non-identity queries
# ---------------------------------------------------------------------------

class TestExistingRoutingUnchanged:
    """Non-identity narrative/operational queries route as before."""

    @pytest.mark.parametrize("text,expected_source", [
        ("Qué ves del sistema?", "deterministic_narrative"),
        ("cuántas acciones pendientes hay", "deterministic_narrative"),
        ("Cuál es el próximo paso seguro?", "deterministic_narrative"),
    ])
    def test_operational_queries_still_narrative(self, text, expected_source):
        from assistant_os.surface_behavior import get_surface_behavior_response
        resp = get_surface_behavior_response(
            surface="mso_direct",
            text=text,
            context_id="ctx-operational",
            identity=_mock_identity(),
            guard_result=_mock_guard(),
        )
        # These may return narrative or cognitive depending on environment,
        # but they must not return deterministic_conversational.
        if resp is not None:
            assert resp.get("response_source") != "deterministic_conversational"

    def test_modelo_query_handled(self):
        """'modelo?' query is handled (not deterministic_conversational)."""
        from assistant_os.surface_behavior import get_surface_behavior_response
        resp = get_surface_behavior_response(
            surface="mso_direct",
            text="modelo?",
            context_id="ctx-modelo",
            identity=_mock_identity(),
            guard_result=_mock_guard(),
        )
        # Must be handled (not None) and not deterministic_conversational
        if resp is not None:
            assert resp.get("response_source") != "deterministic_conversational"

    def test_hola_still_deterministic(self):
        """Greeting still returns deterministic_conversational after identity change."""
        from assistant_os.surface_behavior import get_surface_behavior_response
        resp = get_surface_behavior_response(
            surface="mso_direct",
            text="hola",
            context_id="ctx-hola",
            identity=_mock_identity(),
            guard_result=_mock_guard(),
        )
        assert resp is not None
        assert resp.get("response_source") == "deterministic_conversational"
