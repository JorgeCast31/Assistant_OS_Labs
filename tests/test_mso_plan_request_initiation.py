"""SPRINT-ALPHA-05.1: MSO Plan Request Initiation from Chat.

Verifies that the mso_direct surface correctly detects plan_request intent
and returns system-governed plan_request responses with required provenance fields.
None of these tests invoke an LLM or start a server.
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
def _reset_mso_state() -> None:
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


def _route_mso_direct(text: str) -> dict | None:
    return get_surface_behavior_response(
        surface="mso_direct",
        text=text,
        context_id="ctx-mso-plan-request-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
    )


# ---------------------------------------------------------------------------
# 1-3: Basic routing — response presence, intent, result_type
# ---------------------------------------------------------------------------

def test_mso_direct_plan_request_returns_non_none() -> None:
    """mso_direct plan_request phrase returns a response, not None."""
    result = _route_mso_direct("Prepárame un plan para revisar el repo")
    assert result is not None


def test_mso_direct_plan_request_intent_is_plan_request() -> None:
    """mso_direct plan_request response has intent=plan_request."""
    result = _route_mso_direct("preparame un plan para revisar el repo")
    assert result is not None
    assert result["intent"] == "plan_request"


def test_mso_direct_plan_request_result_type_is_surface_response() -> None:
    """mso_direct plan_request result_type is surface_response."""
    result = _route_mso_direct("hazme un plan para el despliegue")
    assert result is not None
    assert result["result_type"] == "surface_response"


# ---------------------------------------------------------------------------
# 4-6: Execution boundary invariants
# ---------------------------------------------------------------------------

def test_mso_direct_plan_request_execution_allowed_false() -> None:
    """plan_request from mso_direct always has execution_allowed=False."""
    result = _route_mso_direct("preparame un plan")
    assert result is not None
    assert result["execution_allowed"] is False


def test_mso_direct_plan_request_can_execute_now_false() -> None:
    """plan_request from mso_direct always has can_execute_now=False."""
    result = _route_mso_direct("Prepárame un plan para revisar el repo")
    assert result is not None
    assert result["can_execute_now"] is False


def test_mso_direct_plan_request_used_execution_false() -> None:
    """plan_request from mso_direct has used_execution=False."""
    result = _route_mso_direct("preparame un plan para el sistema")
    assert result is not None
    assert result.get("used_execution") is False


# ---------------------------------------------------------------------------
# 7-9: queued_prepared_action presence and invariants
# ---------------------------------------------------------------------------

def test_mso_direct_plan_request_includes_queued_prepared_action() -> None:
    """mso_direct plan_request response includes queued_prepared_action key."""
    result = _route_mso_direct("prepara una accion para el sistema")
    assert result is not None
    assert "queued_prepared_action" in result


def test_mso_direct_plan_request_queued_prepared_action_is_not_none() -> None:
    """mso_direct plan_request queued_prepared_action is not None."""
    result = _route_mso_direct("quiero diagnosticar el servicio")
    assert result is not None
    qpa = result.get("queued_prepared_action")
    assert qpa is not None


def test_mso_direct_plan_request_queued_action_execution_allowed_false() -> None:
    """mso_direct plan_request queued_prepared_action.execution_allowed is False."""
    result = _route_mso_direct("diagnosticar el servidor")
    assert result is not None
    qpa = result.get("queued_prepared_action")
    assert qpa is not None
    assert qpa["execution_allowed"] is False


# ---------------------------------------------------------------------------
# 10-12: operation_trace provenance fields
# ---------------------------------------------------------------------------

def test_mso_direct_plan_request_has_operation_trace() -> None:
    """mso_direct plan_request response includes operation_trace key."""
    result = _route_mso_direct("preparame un plan para revisar el repo")
    assert result is not None
    assert "operation_trace" in result


def test_mso_direct_plan_request_operation_trace_plan_request_prepared() -> None:
    """operation_trace.plan_request_prepared is True."""
    result = _route_mso_direct("hazme un plan para el despliegue")
    assert result is not None
    trace = result.get("operation_trace")
    assert trace is not None
    assert trace["plan_request_prepared"] is True


def test_mso_direct_plan_request_operation_trace_source_surface() -> None:
    """operation_trace.source_surface is mso_direct."""
    result = _route_mso_direct("diagnostico del sistema")
    assert result is not None
    trace = result.get("operation_trace")
    assert trace is not None
    assert trace["source_surface"] == "mso_direct"


# ---------------------------------------------------------------------------
# 13-15: No tasks created, executive pass-through intact, greeting intact
# ---------------------------------------------------------------------------

def test_mso_direct_plan_request_does_not_create_tasks() -> None:
    """plan_request from mso_direct must not register any MSO tasks."""
    result = _route_mso_direct("preparame un plan para revisar el repo")
    assert result is not None
    assert list_tasks() == []


def test_mso_direct_executive_still_passes_through_after_plan_request_wiring() -> None:
    """Executive intents on mso_direct still return None (not short-circuited)."""
    result = _route_mso_direct("crea una tarea de revision")
    assert result is None


def test_mso_direct_conversational_still_returns_greeting_after_plan_request_wiring() -> None:
    """Conversational greetings on mso_direct still return the MSO greeting."""
    result = _route_mso_direct("Hola")
    assert result is not None
    assert result["intent"] == "informational_response"
    assert result["execution_allowed"] is False
