"""S-MSO-INTENT-METADATA-CONTRACT-01: MSO Intent Metadata Contract tests.

Verifies:
1.  Default metadata normalizes to intent_mode=conversation, cognition_level=default, execution_intent=False
2.  Valid metadata preserves planning, advanced, model_seat=anthropic, execution_intent=False
3.  Unknown intent_mode produces warning and safe fallback
4.  Unknown cognition level produces warning and default
5.  execution_intent=True is represented but mso_direct still cannot execute
6.  Unknown model_seat is marked invalid/warning, not silently selected
7.  Entity status exposes intent_contract
8.  mso_direct deterministic status response includes intent_metadata
9.  mso_context conversational maps to intent_mode=conversation
10. mso_context planning maps to intent_mode=planning
11. mso_context validation maps to intent_mode=validation
12. mso_context orchestration maps to intent_mode=orchestration

None of these tests invoke a live LLM, call network services, or start a server.
"""
from __future__ import annotations

import pytest

from assistant_os.mso.intent_contract import normalize_mso_intent_metadata
from assistant_os.mso.entity_status import build_mso_entity_status
from assistant_os.surface_behavior import get_surface_behavior_response


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


class _AuditStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_audit_dict(self) -> dict:
        return dict(self._payload)


# ---------------------------------------------------------------------------
# Autouse fixture — reset MSO state around every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_mso_state():
    try:
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        reset_dynamic_capabilities()
        reset_task_registry()
    except Exception:
        pass
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
    try:
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        reset_dynamic_capabilities()
        reset_task_registry()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------


def _route_mso_direct(text: str, mso_context: dict | None = None) -> dict | None:
    return get_surface_behavior_response(
        surface="mso_direct",
        text=text,
        context_id="ctx-intent-contract-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
        mso_context=mso_context,
    )


# ---------------------------------------------------------------------------
# 1. normalize_mso_intent_metadata — default / None input
# ---------------------------------------------------------------------------


def test_normalize_default_metadata_none_input() -> None:
    """None input must return safe defaults with valid=True."""
    result = normalize_mso_intent_metadata(None)
    assert result["intent_mode"] == "conversation"
    assert result["cognition_level"] == "default"
    assert result["execution_intent"] is False
    assert result["valid"] is True


def test_normalize_default_metadata_empty_dict() -> None:
    """Empty dict must return same safe defaults."""
    result = normalize_mso_intent_metadata({})
    assert result["intent_mode"] == "conversation"
    assert result["cognition_level"] == "default"
    assert result["execution_intent"] is False
    assert result["valid"] is True


# ---------------------------------------------------------------------------
# 2. normalize_mso_intent_metadata — valid input preserved
# ---------------------------------------------------------------------------


def test_normalize_valid_planning_advanced() -> None:
    """planning + advanced + anthropic + False must be preserved exactly."""
    result = normalize_mso_intent_metadata({
        "intent_mode": "planning",
        "cognition_level": "advanced",
        "model_seat": "anthropic",
        "execution_intent": False,
    })
    assert result["intent_mode"] == "planning"
    assert result["cognition_level"] == "advanced"
    assert result["model_seat"] == "anthropic"
    assert result["execution_intent"] is False
    assert result["valid"] is True
    assert result["warnings"] == []


def test_normalize_all_intent_modes_accepted() -> None:
    """All eight supported intent_modes must be accepted without warnings."""
    from assistant_os.mso.intent_contract import (
        INTENT_MODE_CONVERSATION,
        INTENT_MODE_STATUS,
        INTENT_MODE_PLANNING,
        INTENT_MODE_VALIDATION,
        INTENT_MODE_ORCHESTRATION,
        INTENT_MODE_PROPOSAL,
        INTENT_MODE_CONFIRMATION,
        INTENT_MODE_EXECUTION_REQUEST,
    )
    modes = [
        INTENT_MODE_CONVERSATION,
        INTENT_MODE_STATUS,
        INTENT_MODE_PLANNING,
        INTENT_MODE_VALIDATION,
        INTENT_MODE_ORCHESTRATION,
        INTENT_MODE_PROPOSAL,
        INTENT_MODE_CONFIRMATION,
        INTENT_MODE_EXECUTION_REQUEST,
    ]
    for mode in modes:
        result = normalize_mso_intent_metadata({"intent_mode": mode})
        assert result["intent_mode"] == mode, f"mode={mode!r} was not preserved"
        assert result["warnings"] == [], f"unexpected warning for valid mode={mode!r}"


def test_normalize_all_cognition_levels_accepted() -> None:
    """All three cognition levels must be accepted without warnings."""
    from assistant_os.mso.intent_contract import (
        COGNITION_LEVEL_DEFAULT,
        COGNITION_LEVEL_CHEAP,
        COGNITION_LEVEL_ADVANCED,
    )
    for level in [COGNITION_LEVEL_DEFAULT, COGNITION_LEVEL_CHEAP, COGNITION_LEVEL_ADVANCED]:
        result = normalize_mso_intent_metadata({"cognition_level": level})
        assert result["cognition_level"] == level
        assert result["warnings"] == []


# ---------------------------------------------------------------------------
# 3. Unknown intent_mode → warning + safe fallback
# ---------------------------------------------------------------------------


def test_normalize_unknown_intent_mode_produces_warning() -> None:
    """Unknown intent_mode must produce a warning entry."""
    result = normalize_mso_intent_metadata({"intent_mode": "execute_now_please"})
    assert len(result["warnings"]) > 0
    assert any("intent_mode" in w or "execute_now_please" in w for w in result["warnings"])


def test_normalize_unknown_intent_mode_falls_back_to_conversation() -> None:
    """Unknown intent_mode must fall back to 'conversation' (safe default)."""
    result = normalize_mso_intent_metadata({"intent_mode": "totally_unknown"})
    assert result["intent_mode"] == "conversation"


# ---------------------------------------------------------------------------
# 4. Unknown cognition_level → warning + default
# ---------------------------------------------------------------------------


def test_normalize_unknown_cognition_level_produces_warning() -> None:
    """Unknown cognition_level must produce a warning entry."""
    result = normalize_mso_intent_metadata({"cognition_level": "ultra_super"})
    assert len(result["warnings"]) > 0
    assert any("cognition_level" in w or "ultra_super" in w for w in result["warnings"])


def test_normalize_unknown_cognition_level_defaults_to_default() -> None:
    """Unknown cognition_level must default to 'default'."""
    result = normalize_mso_intent_metadata({"cognition_level": "ultra_super"})
    assert result["cognition_level"] == "default"


# ---------------------------------------------------------------------------
# 5. execution_intent=True represented, mso_direct still cannot execute
# ---------------------------------------------------------------------------


def test_normalize_execution_intent_true_is_preserved() -> None:
    """execution_intent=True must be preserved in metadata."""
    result = normalize_mso_intent_metadata({"execution_intent": True})
    assert result["execution_intent"] is True


def test_execution_intent_true_does_not_allow_mso_direct_execution() -> None:
    """Sending execution_intent=True via mso_direct must NOT allow execution.

    mso_direct can_execute_now and execution_allowed must remain False.
    """
    resp = _route_mso_direct(
        "estado del mso",
        mso_context={
            "agent_seat": "mso",
            "interaction_mode": "planning",
            "cognition_tier": "economic",
            "intent_metadata": {
                "intent_mode": "execution_request",
                "execution_intent": True,
            },
        },
    )
    assert resp is not None
    assert resp.get("can_execute_now") is False
    assert resp.get("execution_allowed") is False


# ---------------------------------------------------------------------------
# 6. Unknown model_seat → warning, not silently selected
# ---------------------------------------------------------------------------


def test_normalize_unknown_model_seat_produces_warning() -> None:
    """Unknown model_seat must be marked invalid/warning, not silently selected."""
    result = normalize_mso_intent_metadata({"model_seat": "totally_unknown_provider_xyz"})
    assert len(result["warnings"]) > 0
    assert any("model_seat" in w or "totally_unknown_provider_xyz" in w for w in result["warnings"])


def test_normalize_known_model_seat_no_warning() -> None:
    """Known model_seat (anthropic) must produce no model_seat warning."""
    result = normalize_mso_intent_metadata({"model_seat": "anthropic"})
    seat_warnings = [w for w in result["warnings"] if "model_seat" in w]
    assert seat_warnings == []
    assert result["model_seat"] == "anthropic"


# ---------------------------------------------------------------------------
# 7. Entity status exposes intent_contract
# ---------------------------------------------------------------------------


def test_entity_status_has_intent_contract() -> None:
    """build_mso_entity_status() must include an 'intent_contract' key."""
    result = build_mso_entity_status()
    assert "intent_contract" in result


def test_entity_status_intent_contract_supported_modes() -> None:
    """intent_contract must list all eight supported intent_modes."""
    result = build_mso_entity_status()
    contract = result["intent_contract"]
    modes = contract["supported_intent_modes"]
    expected = {
        "conversation", "status", "planning", "validation",
        "orchestration", "proposal", "confirmation", "execution_request",
    }
    assert set(modes) == expected


def test_entity_status_intent_contract_supported_cognition_levels() -> None:
    """intent_contract must list the three supported cognition levels."""
    result = build_mso_entity_status()
    contract = result["intent_contract"]
    levels = contract["supported_cognition_levels"]
    assert set(levels) == {"default", "cheap", "advanced"}


def test_entity_status_intent_contract_mso_direct_cannot_execute() -> None:
    """intent_contract.mso_direct_can_execute must be False."""
    result = build_mso_entity_status()
    assert result["intent_contract"]["mso_direct_can_execute"] is False


def test_entity_status_intent_contract_execution_requires_governed_path() -> None:
    """intent_contract.execution_requires_governed_path must be True."""
    result = build_mso_entity_status()
    assert result["intent_contract"]["execution_requires_governed_path"] is True


# ---------------------------------------------------------------------------
# 8. mso_direct deterministic status response includes intent_metadata
# ---------------------------------------------------------------------------


def test_mso_direct_status_response_has_intent_metadata() -> None:
    """mso_direct status query must include 'intent_metadata' in response."""
    resp = _route_mso_direct("mso status")
    assert resp is not None
    assert "intent_metadata" in resp


def test_mso_direct_status_intent_metadata_intent_mode_is_status() -> None:
    """intent_metadata.intent_mode for status query must be 'status'."""
    resp = _route_mso_direct("estado del mso")
    assert resp is not None
    assert resp["intent_metadata"]["intent_mode"] == "status"


def test_mso_direct_status_intent_metadata_execution_intent_false() -> None:
    """intent_metadata.execution_intent for status query must be False."""
    resp = _route_mso_direct("mso status")
    assert resp is not None
    assert resp["intent_metadata"]["execution_intent"] is False


def test_mso_direct_status_intent_metadata_valid_true() -> None:
    """intent_metadata.valid for status query must be True."""
    resp = _route_mso_direct("cual es tu estado")
    assert resp is not None
    assert resp["intent_metadata"]["valid"] is True


# ---------------------------------------------------------------------------
# 9. mso_context conversational → intent_mode = conversation
# ---------------------------------------------------------------------------


def test_mso_context_conversational_maps_to_conversation(monkeypatch) -> None:
    """mso_context interaction_mode=conversational must map to intent_mode=conversation.

    The provider call is expected to fail (no key configured) and fall back to
    the narrative path. Both paths must set intent_metadata.intent_mode=conversation.
    """
    from assistant_os import surface_behavior

    def _fake_cognitive(grounding_context, user_text, history=None):
        return {"status": "error", "error": "key not configured", "text": ""}

    monkeypatch.setattr(surface_behavior, "_call_mso_cognitive", _fake_cognitive)

    resp = _route_mso_direct(
        "hola",
        mso_context={
            "agent_seat": "mso",
            "interaction_mode": "conversational",
            "cognition_tier": "economic",
        },
    )
    assert resp is not None
    assert "intent_metadata" in resp
    assert resp["intent_metadata"]["intent_mode"] == "conversation"


# ---------------------------------------------------------------------------
# 10. mso_context planning → intent_mode = planning
# ---------------------------------------------------------------------------


def test_mso_context_planning_maps_to_planning() -> None:
    """mso_context interaction_mode=planning must produce intent_metadata.intent_mode=planning.

    Also verifies that cognition_tier='economic' (surface vocabulary) maps to
    cognition_level='default' (contract vocabulary) — the bridge is intentional.
    """
    resp = _route_mso_direct(
        "necesito un plan para desplegar el servicio",
        mso_context={
            "agent_seat": "mso",
            "interaction_mode": "planning",
            "cognition_tier": "economic",
        },
    )
    assert resp is not None
    assert "intent_metadata" in resp
    assert resp["intent_metadata"]["intent_mode"] == "planning"
    assert resp["intent_metadata"]["cognition_level"] == "default"


def test_mso_context_planning_execution_intent_false() -> None:
    """Planning mode intent_metadata must have execution_intent=False."""
    resp = _route_mso_direct(
        "planifica el despliegue",
        mso_context={
            "agent_seat": "mso",
            "interaction_mode": "planning",
            "cognition_tier": "economic",
        },
    )
    assert resp is not None
    assert resp["intent_metadata"]["execution_intent"] is False


# ---------------------------------------------------------------------------
# 11. mso_context validation → intent_mode = validation
# ---------------------------------------------------------------------------


def test_mso_context_validation_maps_to_validation() -> None:
    """mso_context interaction_mode=validation must produce intent_metadata.intent_mode=validation."""
    resp = _route_mso_direct(
        "revisa las acciones pendientes",
        mso_context={
            "agent_seat": "mso",
            "interaction_mode": "validation",
            "cognition_tier": "economic",
        },
    )
    assert resp is not None
    assert "intent_metadata" in resp
    assert resp["intent_metadata"]["intent_mode"] == "validation"


# ---------------------------------------------------------------------------
# 12. mso_context orchestration → intent_mode = orchestration
# ---------------------------------------------------------------------------


def test_mso_context_orchestration_maps_to_orchestration() -> None:
    """mso_context interaction_mode=orchestration must produce intent_metadata.intent_mode=orchestration."""
    resp = _route_mso_direct(
        "coordina los agentes",
        mso_context={
            "agent_seat": "mso",
            "interaction_mode": "orchestration",
            "cognition_tier": "economic",
        },
    )
    assert resp is not None
    assert "intent_metadata" in resp
    assert resp["intent_metadata"]["intent_mode"] == "orchestration"


def test_mso_context_orchestration_execution_intent_false() -> None:
    """Orchestration mode intent_metadata must have execution_intent=False."""
    resp = _route_mso_direct(
        "coordina los agentes",
        mso_context={
            "agent_seat": "mso",
            "interaction_mode": "orchestration",
            "cognition_tier": "economic",
        },
    )
    assert resp is not None
    assert resp["intent_metadata"]["execution_intent"] is False
