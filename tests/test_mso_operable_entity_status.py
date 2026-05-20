"""S-MSO-OPERABLE-ENTITY-01: MSO Entity Status tests.

Verifies that build_mso_entity_status() returns the correct shape and values,
and that the mso_direct surface routes status query phrases to mso_entity_status
responses with the correct invariants.

None of these tests invoke an LLM, mock build_mso_entity_status, or start a
server.
"""
from __future__ import annotations

import pytest

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
def _reset_mso_state() -> None:
    from assistant_os.mso.task_registry import list_tasks, reset_task_registry
    from assistant_os.mso.capability_registry import reset_dynamic_capabilities
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


# ---------------------------------------------------------------------------
# mso_direct routing helper
# ---------------------------------------------------------------------------

def _route_mso_direct(text: str) -> dict | None:
    return get_surface_behavior_response(
        surface="mso_direct",
        text=text,
        context_id="ctx-mso-entity-status-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
    )


# ---------------------------------------------------------------------------
# Unit tests — build_mso_entity_status()
# ---------------------------------------------------------------------------

def test_entity_returns_mso() -> None:
    """entity field must equal 'MSO'."""
    result = build_mso_entity_status()
    assert result["entity"] == "MSO"


def test_kernel_boundary_present() -> None:
    """runtime_boundary.kernel must be a non-empty string containing 'mso.kernel'."""
    result = build_mso_entity_status()
    kernel = result["runtime_boundary"]["kernel"]
    assert isinstance(kernel, str)
    assert kernel  # non-empty
    assert "mso.kernel" in kernel


def test_police_gate_integrated() -> None:
    """authority_chain.police_gate must be True."""
    result = build_mso_entity_status()
    assert result["authority_chain"]["police_gate"] is True


def test_runner_fail_closed() -> None:
    """authority_chain.runner_fail_closed must be True."""
    result = build_mso_entity_status()
    assert result["authority_chain"]["runner_fail_closed"] is True


def test_authority_artifact_version_2() -> None:
    """authority_chain.authority_artifact_version must be '2'."""
    result = build_mso_entity_status()
    assert result["authority_chain"]["authority_artifact_version"] == "2"


def test_mso_direct_cannot_execute() -> None:
    """surfaces.mso_direct.can_execute must be False."""
    result = build_mso_entity_status()
    assert result["surfaces"]["mso_direct"]["can_execute"] is False


def test_assistant_chat_can_execute() -> None:
    """surfaces.assistant_chat.can_execute must be True."""
    result = build_mso_entity_status()
    assert result["surfaces"]["assistant_chat"]["can_execute"] is True


def test_code_api_external_local() -> None:
    """surfaces.code_api.authority_class must be 'external_local'."""
    result = build_mso_entity_status()
    assert result["surfaces"]["code_api"]["authority_class"] == "external_local"


def test_model_seat_has_provider_key() -> None:
    """Result must contain 'model_seat' with a 'provider' key."""
    result = build_mso_entity_status()
    assert "model_seat" in result
    assert "provider" in result["model_seat"]


def test_interaction_modes_includes_status() -> None:
    """'status' must appear in interaction_modes list."""
    result = build_mso_entity_status()
    assert "status" in result["interaction_modes"]


def test_mso_direct_cannot_execute_via_used_execution() -> None:
    """surfaces.mso_direct.used_execution must be False (execution never occurred)."""
    result = build_mso_entity_status()
    assert result["surfaces"]["mso_direct"]["used_execution"] is False


# ---------------------------------------------------------------------------
# mso_direct surface routing tests
# ---------------------------------------------------------------------------

def test_mso_direct_status_query_returns_response() -> None:
    """'estado del mso' must route to a non-None response with intent=mso_entity_status."""
    result = _route_mso_direct("estado del mso")
    assert result is not None
    assert result["intent"] == "mso_entity_status"


def test_mso_direct_status_used_execution_false() -> None:
    """mso_direct status response must carry used_execution=False."""
    result = _route_mso_direct("mso status")
    assert result is not None
    assert result["used_execution"] is False


def test_mso_direct_status_can_execute_now_false() -> None:
    """mso_direct status response must carry can_execute_now=False."""
    result = _route_mso_direct("cual es tu estado")
    assert result is not None
    assert result["can_execute_now"] is False


def test_mso_direct_status_includes_entity_status_dict() -> None:
    """mso_direct status response must include entity_status dict with entity='MSO'."""
    result = _route_mso_direct("mso status")
    assert result is not None
    assert "entity_status" in result
    assert result["entity_status"]["entity"] == "MSO"
