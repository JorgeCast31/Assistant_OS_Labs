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


def _plan_from_result(result: dict) -> dict:
    return (result.get("data") or {}).get("plan") or {}


def test_current_gap_hola_routes_to_energy_command_but_registry_blocks_it() -> None:
    result = _route_main_chat_without_surface("Hola")
    plan = _plan_from_result(result)
    governance = (result.get("data") or {}).get("governance_trace") or {}

    assert result["result_type"] == "plan_generated"
    assert result["domain"] == "ENERGY"
    assert plan["action"] == ACTION_COMMAND
    assert governance["capability_mode"] == "deny"
    assert "Capability registry denied" in governance["justification"]


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
