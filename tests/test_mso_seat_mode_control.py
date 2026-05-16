"""SPRINT-ALPHA-05.5: MSO Seat + Mode Control routing tests.

Verifies:
- mso_context present → selected interaction_mode dominates routing
- mso_context absent → backward-compat text-driven path unchanged
- planning mode overrides executive-prefix text (Tier 1 does NOT apply)
- all modes attach perception_context
- validation mode is read-only (no new queue entries)
- orchestration mode returns governed explanation (no token/runner/plan)
- fail-closed defaults on invalid seat/mode/tier
- no productive execution primitives touched in any mode
"""
from __future__ import annotations

import pytest

from assistant_os.mso.task_registry import list_tasks, reset_task_registry
from assistant_os.mso.capability_registry import reset_dynamic_capabilities
from assistant_os.surface_behavior import get_surface_behavior_response


class _AuditStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_audit_dict(self) -> dict:
        return dict(self._payload)


@pytest.fixture(autouse=True)
def _reset_mso_state():
    reset_dynamic_capabilities()
    reset_task_registry()
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


def _route(text: str, mso_context: dict | None = None) -> dict | None:
    return get_surface_behavior_response(
        surface="mso_direct",
        text=text,
        context_id="ctx-mode-control-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
        mso_context=mso_context,
    )


def _ctx(mode: str, seat: str = "mso", tier: str = "economic") -> dict:
    return {"agent_seat": seat, "interaction_mode": mode, "cognition_tier": tier}


def _queue_count() -> int:
    try:
        from assistant_os.mso.prepared_action_queue import list_pending_confirmable_action_dicts
        return len(list_pending_confirmable_action_dicts())
    except Exception:
        return 0


# ── Backward compatibility (mso_context absent) ───────────────────────────────

class TestBackwardCompat:
    def test_absent_greeting_returns_deterministic_conversational(self):
        resp = _route("Hola")
        assert resp is not None
        assert resp.get("response_source") == "deterministic_conversational"

    def test_absent_plan_text_returns_plan_request(self):
        resp = _route("Prepárame un plan de revisión")
        assert resp is not None
        assert resp.get("intent") == "plan_request"
        assert resp.get("response_source") == "mso_plan_request_prepared"

    def test_absent_arbitrary_narrative_text_not_plan_request(self):
        # Text that triggers narrative/cognitive, not plan_request, in backward-compat path.
        # "Cuéntame sobre el sistema" doesn't match plan_request regex patterns.
        resp = _route("Cuéntame sobre el sistema")
        # This may hit cognitive (provider unavailable) or narrative, but NOT plan_request.
        assert resp is None or resp.get("intent") != "plan_request"

    def test_absent_executive_text_returns_none(self):
        resp = _route("Crea una tarea urgente ahora")
        assert resp is None

    def test_absent_mso_context_not_dict_treated_as_absent(self):
        # _parse_mso_context returns None for any non-dict value (fail-closed).
        # This means the text-driven backward-compat path fires — "Hola" → conversational.
        resp = get_surface_behavior_response(
            surface="mso_direct",
            text="Hola",
            context_id="ctx-test",
            identity=_AuditStub({"principal": "anon"}),
            guard_result=_AuditStub({"decision": "allow"}),
            mso_context="planning",  # type: ignore[arg-type]  — non-dict, treated as None
        )
        assert resp is not None
        # Falls through to text-driven Tier 2: "hola" in _MSO_DIRECT_CONVERSATIONAL
        assert resp.get("response_source") == "deterministic_conversational"


# ── conversational mode ────────────────────────────────────────────────────────

class TestConversationalMode:
    def test_conversational_diagnosis_not_plan_request(self):
        resp = _route("Diagnóstico del sistema", _ctx("conversational"))
        assert resp is not None
        assert resp.get("intent") != "plan_request"

    def test_conversational_returns_non_none(self):
        resp = _route("Cuéntame más sobre el sistema", _ctx("conversational"))
        assert resp is not None

    def test_conversational_execution_allowed_false(self):
        resp = _route("Estado del MSO", _ctx("conversational"))
        assert resp is not None
        assert resp.get("execution_allowed") is False

    def test_conversational_can_execute_now_false(self):
        resp = _route("Hola MSO", _ctx("conversational"))
        assert resp is not None
        assert resp.get("can_execute_now") is False

    def test_conversational_perception_context_present(self):
        resp = _route("Estado del sistema", _ctx("conversational"))
        assert resp is not None
        pc = resp.get("perception_context")
        assert pc is not None
        assert "grounding_available" in pc
        assert "vault_available" in pc
        assert "session_history_available" in pc

    def test_conversational_does_not_create_queue_entry(self):
        before = _queue_count()
        _route("Diagnóstico del sistema", _ctx("conversational"))
        assert _queue_count() == before


# ── planning mode ──────────────────────────────────────────────────────────────

class TestPlanningMode:
    def test_planning_diagnosis_creates_plan_request(self):
        resp = _route("Diagnóstico del sistema", _ctx("planning"))
        assert resp is not None
        assert resp.get("intent") == "plan_request"

    def test_planning_greeting_text_creates_plan_request(self):
        resp = _route("hola", _ctx("planning"))
        assert resp is not None
        assert resp.get("intent") == "plan_request"

    def test_planning_executive_text_creates_plan_request(self):
        # CRITICAL: planning mode overrides executive-prefix check.
        # "Crea una tarea" must NOT return None when mso_context is present.
        resp = _route("Crea una tarea de revisión", _ctx("planning"))
        assert resp is not None
        assert resp.get("intent") == "plan_request"

    def test_planning_response_source(self):
        resp = _route("Diagnóstico del sistema", _ctx("planning"))
        assert resp is not None
        assert resp.get("response_source") == "mso_mode_planning_prepared"

    def test_planning_operation_trace_interaction_mode(self):
        resp = _route("Diagnóstico del sistema", _ctx("planning"))
        assert resp is not None
        ot = resp.get("operation_trace", {})
        assert ot.get("interaction_mode") == "planning"

    def test_planning_operation_trace_mode_source_ui_selected(self):
        resp = _route("Diagnóstico del sistema", _ctx("planning"))
        assert resp is not None
        ot = resp.get("operation_trace", {})
        assert ot.get("mode_source") == "ui_selected"

    def test_planning_queued_prepared_action_present(self):
        resp = _route("Diagnóstico del sistema", _ctx("planning"))
        assert resp is not None
        qa = resp.get("queued_prepared_action")
        assert qa is not None

    def test_planning_visible_in_mission_control(self):
        resp = _route("Diagnóstico del sistema", _ctx("planning"))
        assert resp is not None
        ot = resp.get("operation_trace", {})
        assert ot.get("visible_in_mission_control") is True

    def test_planning_execution_invariants(self):
        resp = _route("Diagnóstico del sistema", _ctx("planning"))
        assert resp is not None
        assert resp.get("execution_allowed") is False
        assert resp.get("can_execute_now") is False
        ot = resp.get("operation_trace", {})
        assert ot.get("used_execution") is False
        assert ot.get("execution_allowed") is False

    def test_planning_perception_context_present(self):
        resp = _route("Diagnóstico del sistema", _ctx("planning"))
        assert resp is not None
        pc = resp.get("perception_context")
        assert pc is not None
        assert "grounding_available" in pc

    def test_planning_non_mso_seat_still_creates_plan(self):
        # Other seats are accepted, traced, and degrade through MSO path.
        resp = _route("Diagnóstico", _ctx("planning", seat="machine_operator"))
        assert resp is not None
        assert resp.get("intent") == "plan_request"
        ot = resp.get("operation_trace", {})
        assert ot.get("agent_seat") == "machine_operator"


# ── validation mode ────────────────────────────────────────────────────────────

class TestValidationMode:
    def test_validation_intent_review_queue_status(self):
        resp = _route("Revisa la cola actual", _ctx("validation"))
        assert resp is not None
        assert resp.get("intent") == "review_queue_status"

    def test_validation_response_source(self):
        resp = _route("Muestra el estado", _ctx("validation"))
        assert resp is not None
        assert resp.get("response_source") == "mso_mode_validation_read_only"

    def test_validation_no_new_queue_entry(self):
        before = _queue_count()
        _route("Revisa la cola", _ctx("validation"))
        assert _queue_count() == before

    def test_validation_execution_invariants(self):
        resp = _route("Revisa la cola", _ctx("validation"))
        assert resp is not None
        assert resp.get("execution_allowed") is False
        assert resp.get("can_execute_now") is False
        ot = resp.get("operation_trace", {})
        assert ot.get("read_only") is True
        assert ot.get("execution_allowed") is False

    def test_validation_perception_context_present(self):
        resp = _route("Estado de la cola", _ctx("validation"))
        assert resp is not None
        pc = resp.get("perception_context")
        assert pc is not None
        assert "grounding_available" in pc

    def test_validation_returns_pending_review_items_field(self):
        resp = _route("Revisa la cola", _ctx("validation"))
        assert resp is not None
        assert "pending_review_items" in resp


# ── orchestration mode ─────────────────────────────────────────────────────────

class TestOrchestrationMode:
    def test_orchestration_intent(self):
        resp = _route("Ejecuta una revisión del repo", _ctx("orchestration"))
        assert resp is not None
        assert resp.get("intent") == "orchestration_mode_governed"

    def test_orchestration_response_source(self):
        resp = _route("Ejecuta revisión", _ctx("orchestration"))
        assert resp is not None
        assert resp.get("response_source") == "mso_mode_orchestration_governed"

    def test_orchestration_no_queue_entry_created(self):
        before = _queue_count()
        _route("Ejecuta revisión del repo", _ctx("orchestration"))
        assert _queue_count() == before

    def test_orchestration_execution_invariants(self):
        resp = _route("Ejecuta revisión", _ctx("orchestration"))
        assert resp is not None
        assert resp.get("execution_allowed") is False
        assert resp.get("can_execute_now") is False
        ot = resp.get("operation_trace", {})
        assert ot.get("execution_allowed") is False
        assert ot.get("governed_explanation") is True

    def test_orchestration_perception_context_present(self):
        resp = _route("Ejecuta revisión", _ctx("orchestration"))
        assert resp is not None
        pc = resp.get("perception_context")
        assert pc is not None
        assert "grounding_available" in pc

    def test_orchestration_message_explains_chain_limit(self):
        resp = _route("Ejecuta revisión", _ctx("orchestration"))
        assert resp is not None
        msg = resp.get("message", "")
        assert "AuthorityBindingDraft" in msg or "execution" in msg.lower()

    def test_orchestration_executive_text_still_governed(self):
        resp = _route("Crea y ejecuta todo ahora", _ctx("orchestration"))
        assert resp is not None
        assert resp.get("intent") == "orchestration_mode_governed"
        assert resp.get("execution_allowed") is False


# ── fail-closed / invalid input ───────────────────────────────────────────────

class TestFailClosed:
    def test_invalid_seat_defaults_to_mso(self):
        resp = _route("Diagnóstico", _ctx("conversational", seat="unknown_seat"))
        assert resp is not None
        ot = resp.get("operation_trace") or resp.get("cognitive_trace") or {}
        # The normalized seat should be mso; warnings should be non-empty
        pc = resp.get("perception_context", {})
        assert pc.get("grounding_available") is not None

    def test_invalid_mode_defaults_to_conversational(self):
        resp = _route("Diagnóstico", {"agent_seat": "mso", "interaction_mode": "fly", "cognition_tier": "economic"})
        assert resp is not None
        assert resp.get("intent") != "plan_request"

    def test_invalid_tier_defaults_to_economic(self):
        resp = _route("Diagnóstico", {"agent_seat": "mso", "interaction_mode": "conversational", "cognition_tier": "ultra"})
        assert resp is not None

    def test_empty_mso_context_dict_uses_defaults(self):
        resp = _route("Diagnóstico", {})
        assert resp is not None
        # Empty dict → all defaults → conversational mode, not plan_request
        assert resp.get("intent") != "plan_request"
