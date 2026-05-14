"""Tests for MSO Economic Perception Frame — Alpha Phase 2 baseline.

Covers build_mso_grounding_context(), build_narrative_context_message(),
is_mso_narrative_intent(), and build_mso_chat_system_prompt() in isolation.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Grounding context shape and invariants
# ---------------------------------------------------------------------------

def test_grounding_context_has_required_keys():
    from assistant_os.mso.narrative_runtime import build_mso_grounding_context
    ctx = build_mso_grounding_context()
    required = {
        "operational_mode", "seat_provider", "prepared_actions_count",
        "next_safe_step", "authority_posture", "limitations",
    }
    assert required.issubset(ctx.keys())


def test_grounding_context_execution_invariants():
    from assistant_os.mso.narrative_runtime import build_mso_grounding_context
    ctx = build_mso_grounding_context()
    assert ctx.get("execution_allowed") is False
    assert ctx.get("can_execute_now") is False
    assert ctx.get("execution_closed") is True


def test_grounding_context_never_raises():
    from assistant_os.mso.narrative_runtime import build_mso_grounding_context
    try:
        ctx = build_mso_grounding_context()
        assert isinstance(ctx, dict)
    except Exception as exc:
        pytest.fail(f"build_mso_grounding_context() raised: {exc}")


def test_grounding_context_seat_provider_is_string():
    from assistant_os.mso.narrative_runtime import build_mso_grounding_context
    ctx = build_mso_grounding_context()
    assert isinstance(ctx.get("seat_provider"), str)


def test_grounding_context_prepared_actions_count_is_int():
    from assistant_os.mso.narrative_runtime import build_mso_grounding_context
    ctx = build_mso_grounding_context()
    assert isinstance(ctx.get("prepared_actions_count"), int)


# ---------------------------------------------------------------------------
# Narrative context message
# ---------------------------------------------------------------------------

def test_narrative_context_message_returns_str_and_dict():
    from assistant_os.mso.narrative_runtime import build_narrative_context_message
    msg, ctx = build_narrative_context_message()
    assert isinstance(msg, str)
    assert len(msg) > 0
    assert isinstance(ctx, dict)


def test_narrative_context_message_execution_invariants():
    from assistant_os.mso.narrative_runtime import build_narrative_context_message
    _msg, ctx = build_narrative_context_message()
    assert ctx.get("execution_allowed") is False
    assert ctx.get("can_execute_now") is False


def test_narrative_context_message_contains_grounding_keys():
    from assistant_os.mso.narrative_runtime import build_narrative_context_message
    _msg, ctx = build_narrative_context_message()
    assert "operational_mode" in ctx
    assert "seat_provider" in ctx


def test_narrative_context_message_never_raises():
    from assistant_os.mso.narrative_runtime import build_narrative_context_message
    try:
        msg, ctx = build_narrative_context_message()
        assert isinstance(msg, str)
        assert isinstance(ctx, dict)
    except Exception as exc:
        pytest.fail(f"build_narrative_context_message() raised: {exc}")


# ---------------------------------------------------------------------------
# Narrative intent detection
# ---------------------------------------------------------------------------

def test_narrative_intent_detects_known_phrases():
    from assistant_os.mso.narrative_runtime import is_mso_narrative_intent, _NARRATIVE_EXACT
    # Test against actual set members to avoid hardcoding strings that may change
    for phrase in list(_NARRATIVE_EXACT)[:3]:
        assert is_mso_narrative_intent(phrase), (
            f"Expected narrative intent for known phrase: {phrase!r}"
        )


def test_narrative_intent_rejects_executive_phrases():
    from assistant_os.mso.narrative_runtime import is_mso_narrative_intent
    non_narrative = ["crea un archivo", "ejecuta el plan", "abre el repo"]
    for phrase in non_narrative:
        assert not is_mso_narrative_intent(phrase), (
            f"Expected NOT narrative intent for: {phrase!r}"
        )


def test_narrative_intent_returns_bool():
    from assistant_os.mso.narrative_runtime import is_mso_narrative_intent
    result = is_mso_narrative_intent("cualquier texto")
    assert isinstance(result, bool)


def test_narrative_intent_never_raises_on_bad_input():
    from assistant_os.mso.narrative_runtime import is_mso_narrative_intent
    for bad_input in ["", "   "]:
        try:
            result = is_mso_narrative_intent(bad_input)
            assert isinstance(result, bool)
        except Exception as exc:
            pytest.fail(f"is_mso_narrative_intent({bad_input!r}) raised: {exc}")


# ---------------------------------------------------------------------------
# System prompt execution boundary (Alpha Phase 3 integration)
# ---------------------------------------------------------------------------

def test_system_prompt_contains_execution_boundary():
    from assistant_os.mso.prompts import build_mso_chat_system_prompt
    from assistant_os.mso.narrative_runtime import build_mso_grounding_context
    ctx = build_mso_grounding_context()
    prompt = build_mso_chat_system_prompt(ctx)
    assert "cannot execute" in prompt.lower() or "You cannot execute" in prompt


def test_system_prompt_contains_perception_frame():
    from assistant_os.mso.prompts import build_mso_chat_system_prompt
    from assistant_os.mso.narrative_runtime import build_mso_grounding_context
    ctx = build_mso_grounding_context()
    prompt = build_mso_chat_system_prompt(ctx)
    assert "SYSTEM PERCEPTION FRAME" in prompt


def test_system_prompt_contains_vault_section():
    from assistant_os.mso.prompts import build_mso_chat_system_prompt
    from assistant_os.mso.narrative_runtime import build_mso_grounding_context
    ctx = build_mso_grounding_context()
    prompt = build_mso_chat_system_prompt(ctx)
    assert "VAULT SEMANTIC CONTEXT" in prompt


def test_system_prompt_is_string_and_non_empty():
    from assistant_os.mso.prompts import build_mso_chat_system_prompt
    from assistant_os.mso.narrative_runtime import build_mso_grounding_context
    ctx = build_mso_grounding_context()
    prompt = build_mso_chat_system_prompt(ctx)
    assert isinstance(prompt, str)
    assert len(prompt) > 100
