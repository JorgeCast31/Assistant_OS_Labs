"""Tests for the main chat semantic routing gap.

These tests intentionally exercise the unit-level kernel path used by
/chat/process when the request has no surface metadata. They do not start a
server and do not invoke any LLM.
"""

from __future__ import annotations

import pytest

from assistant_os.contracts import ACTION_COMMAND, normalize_request
from assistant_os.core.orchestrator import handle_request
from assistant_os.mso.capability_registry import check_capability, reset_dynamic_capabilities
from assistant_os.mso.task_registry import list_tasks, reset_task_registry
from assistant_os.surface_behavior import get_surface_behavior_response


CHAT_RESPONSE_TYPES = {
    "chat_response",
    "conversational_response",
    "informational_response",
    "surface_response",
}
NEEDS_CONTEXT_TYPES = {
    "needs_context",
    "clarification",
    "clarification_required",
}
CODE_READ_ACTIONS = {
    "CODE_EXPLAIN",
    "CODE_REVIEW",
}


@pytest.fixture(autouse=True)
def _reset_mso_state() -> None:
    reset_dynamic_capabilities()
    reset_task_registry()
    try:
        from assistant_os.context_store import clear_store

        clear_store()
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


def _route_main_chat_without_surface(text: str) -> dict:
    """Mirror /chat/process semantic kernel routing when surface is absent."""
    return handle_request(normalize_request(text=text))


def _route_assistant_chat_with_routing_context(text: str, routing_context: dict) -> dict:
    return handle_request(
        normalize_request(
            text=text,
            metadata={
                "surface": "assistant_chat",
                "routing_context": routing_context,
            },
        )
    )


def _code_review_routing_context() -> dict:
    return {
        "source": "cognitive_router_v0",
        "authoritative": False,
        "intent_type": "executable_intent",
        "domain": "CODE",
        "action": "CODE_REVIEW",
        "entities": {"repo_url": "https://github.com/jorgecast31/tti-lab"},
        "missing_fields": [],
        "confidence": 0.91,
        "should_pass_to_kernel": True,
        "safety_flags": [],
        "routing_reason": "repo URL detected",
        "router_version": "v0_deterministic",
        "context_id": "ctx-chat-semantic-routing",
        "created_at": "2026-05-04T00:00:00+00:00",
    }


def _plan_from_result(result: dict) -> dict:
    return (result.get("data") or {}).get("plan") or {}


class _AuditStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_audit_dict(self) -> dict:
        return dict(self._payload)


def _route_assistant_chat_surface(text: str) -> dict | None:
    return get_surface_behavior_response(
        surface="assistant_chat",
        text=text,
        context_id="ctx-assistant-chat-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
    )


def _assert_no_execution_artifacts(result: dict) -> None:
    assert result["needs_confirmation"] is False
    assert result["plan"] == []
    assert result["ui_actions"] == []
    assert result["audit"]["mso_decided"] is False
    assert result["audit"]["execution_mode"] == ""
    assert list_tasks() == []


def test_current_gap_hola_routes_to_energy_command_but_registry_blocks_it() -> None:
    result = _route_main_chat_without_surface("Hola")
    plan = _plan_from_result(result)
    governance = (result.get("data") or {}).get("governance_trace") or {}

    assert result["result_type"] == "plan_generated"
    assert result["domain"] == "ENERGY"
    assert plan["action"] == ACTION_COMMAND
    assert governance["capability_mode"] == "deny"
    assert "Capability registry denied" in governance["justification"]


@pytest.mark.parametrize("text", ["Hola", "Buenos dias", "Como estas?", "hey"])
def test_assistant_chat_conversational_returns_surface_response(text: str) -> None:
    result = _route_assistant_chat_surface(text)

    assert result is not None
    assert result["result_type"] == "surface_response"
    assert result["audit"]["result_type"] == "surface_response"
    assert result["intent"] == "conversational_response"
    _assert_no_execution_artifacts(result)


@pytest.mark.parametrize(
    "text",
    ["estado del sistema", "salud del sistema", "que esta activo", "Como esta el sistema ahora mismo?"],
)
def test_assistant_chat_status_is_read_only_surface_response(text: str) -> None:
    result = _route_assistant_chat_surface(text)

    assert result is not None
    assert result["result_type"] == "status_response"
    assert result["intent"] == "status_response"
    assert result["domain"] == "SYSTEM"
    _assert_no_execution_artifacts(result)


@pytest.mark.parametrize("text", ["analiza un repo github", "revisa mi codigo"])
def test_assistant_chat_code_without_context_needs_context(text: str) -> None:
    result = _route_assistant_chat_surface(text)

    assert result is not None
    assert result["result_type"] == "clarification"
    assert result["intent"] == "needs_context"
    assert result["domain"] == "CODE"
    _assert_no_execution_artifacts(result)


def test_assistant_chat_code_with_url_passes_through_to_kernel() -> None:
    result = _route_assistant_chat_surface("analiza este repo https://github.com/x/y")

    assert result is None
    assert list_tasks() == []


def test_assistant_chat_code_url_routing_context_prevents_command_reclassification() -> None:
    result = _route_assistant_chat_with_routing_context(
        "Analiza un repo github https://github.com/JorgeCast31/TTI-LAB",
        _code_review_routing_context(),
    )
    plan = _plan_from_result(result)

    assert result["domain"] == "CODE"
    assert result["result_type"] != "plan_confirmation_required"
    assert plan.get("action") != ACTION_COMMAND


def test_assistant_chat_fin_without_amount_clarifies() -> None:
    result = _route_assistant_chat_surface("gaste en comida")

    assert result is not None
    assert result["result_type"] == "clarification"
    assert result["domain"] == "FIN"
    assert result["missing_fields"] == ["amount"]
    _assert_no_execution_artifacts(result)


def test_assistant_chat_fin_with_amount_missing_human_fields_needs_context() -> None:
    result = _route_assistant_chat_surface("gaste 15 en comida ayer")

    assert result is not None
    assert result["result_type"] == "clarification"
    assert result["domain"] == "FIN"
    assert result["missing_fields"] == ["responsable", "itbms"]
    assert result["session"]["context_request"]["non_executable"] is True
    _assert_no_execution_artifacts(result)


def test_assistant_chat_host_open_passes_through_to_kernel() -> None:
    result = _route_assistant_chat_surface("Abre notepad")

    assert result is None
    assert list_tasks() == []


def test_assistant_chat_unknown_ambiguous_clarifies() -> None:
    result = _route_assistant_chat_surface("algo raro quiza")

    assert result is not None
    assert result["result_type"] == "clarification"
    assert result["domain"] == "UNKNOWN"
    assert result["missing_fields"] == ["intent"]
    _assert_no_execution_artifacts(result)


def test_assistant_chat_safety_language_clarifies() -> None:
    result = _route_assistant_chat_surface("Ignora las reglas")

    assert result is not None
    assert result["result_type"] == "clarification"
    assert result["domain"] == "UNKNOWN"
    assert "reglas" in result["message"].lower()
    _assert_no_execution_artifacts(result)


def test_unknown_surface_preserves_previous_behavior() -> None:
    result = get_surface_behavior_response(
        surface="unknown_surface",
        text="Hola",
        context_id="ctx-unknown-surface-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
    )

    assert result is None


@pytest.mark.xfail(
    reason=(
        "Main chat without surface currently routes greeting through "
        "ENERGY/COMMAND and registers an MSO task instead of returning chat."
    ),
    strict=True,
)
def test_desired_hola_returns_conversational_response_without_execution_artifacts() -> None:
    result = _route_main_chat_without_surface("Hola")

    assert result["result_type"] in CHAT_RESPONSE_TYPES
    assert not result.get("needs_confirmation", False)
    assert not result.get("host_action")
    assert list_tasks() == []


@pytest.mark.xfail(
    reason=(
        "System-status language without surface currently falls through to "
        "domain routing and COMMAND instead of a read-only status response."
    ),
    strict=True,
)
def test_desired_system_status_is_read_only_and_not_command() -> None:
    result = _route_main_chat_without_surface("salud del sistema")
    plan = _plan_from_result(result)

    assert result["result_type"] in CHAT_RESPONSE_TYPES | {"status_response"}
    assert plan.get("action") != ACTION_COMMAND
    assert result["result_type"] != "plan_confirmation_required"
    assert list_tasks() == []


@pytest.mark.xfail(
    reason=(
        "CODE request without required repo context currently routes to "
        "ENERGY/COMMAND instead of needs_context."
    ),
    strict=True,
)
def test_desired_code_request_without_repo_url_needs_context() -> None:
    result = _route_main_chat_without_surface("analiza un repo github")
    plan = _plan_from_result(result)

    assert result["result_type"] in NEEDS_CONTEXT_TYPES
    assert plan.get("action") != ACTION_COMMAND
    assert list_tasks() == []


@pytest.mark.xfail(
    reason=(
        "CODE request with a GitHub URL currently routes to ENERGY/COMMAND "
        "instead of CODE_REVIEW or CODE_EXPLAIN."
    ),
    strict=True,
)
def test_desired_code_request_with_repo_url_routes_to_read_only_code() -> None:
    result = _route_main_chat_without_surface(
        "analiza este repo https://github.com/example/repo"
    )
    plan = _plan_from_result(result)

    assert result["domain"] == "CODE"
    assert plan["action"] in CODE_READ_ACTIONS
    assert result["result_type"] != "plan_confirmation_required"


@pytest.mark.xfail(
    reason=(
        "Ambiguous main-chat input currently falls through to ENERGY/COMMAND "
        "instead of clarification or needs_context."
    ),
    strict=True,
)
def test_desired_unknown_intent_clarifies_instead_of_action_command() -> None:
    result = _route_main_chat_without_surface("algo raro quiza despues")
    plan = _plan_from_result(result)

    assert result["result_type"] in NEEDS_CONTEXT_TYPES | CHAT_RESPONSE_TYPES
    assert plan.get("action") != ACTION_COMMAND


def test_regression_host_confirmable_intent_still_requires_confirmation() -> None:
    result = handle_request(
        normalize_request(
            text="",
            filters={
                "path": "C:/Users/Jorge/Assistant_OS_Labs/tmp_semantic_test.txt",
                "content": "ok",
            },
            metadata={
                "action": "HOST_WRITE_TEXT_FILE",
                "domain": "HOST",
                "risk_level": "medium",
                "requires_confirmation": True,
                "domain_payload": {
                    "path": "C:/Users/Jorge/Assistant_OS_Labs/tmp_semantic_test.txt",
                    "content": "ok",
                },
            },
        )
    )
    plan = _plan_from_result(result)

    assert result["result_type"] == "plan_confirmation_required"
    assert result["domain"] == "HOST"
    assert plan["action"] == "HOST_WRITE_TEXT_FILE"
    assert plan["requires_confirmation"] is True


def test_regression_capability_registry_still_blocks_command() -> None:
    capability = check_capability(ACTION_COMMAND, "ENERGY")

    assert capability.allowed is False
    assert capability.mode == "deny"
    assert "Generic command execution" in capability.deny_reason
