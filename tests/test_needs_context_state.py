"""Desired contract tests for non-executable needs_context state.

These tests document the current gap: assistant_chat can ask for missing
fields, but there is no request-local/session-persistent context_request that
later turns can complete. The store/resolver is intentionally not implemented
in this sprint.
"""

from __future__ import annotations

import http.client
import json
import time
import uuid
from unittest.mock import patch

import pytest

from assistant_os.config import WEBHOOK_TOKEN
from assistant_os.mso.task_registry import list_tasks, reset_task_registry
from assistant_os.webhook_server import start_server_thread


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    reset_task_registry()
    try:
        from assistant_os.context_store import clear_store

        clear_store()
    except Exception:
        pass
    yield
    reset_task_registry()
    try:
        from assistant_os.context_store import clear_store

        clear_store()
    except Exception:
        pass


@pytest.fixture(scope="module")
def chat_server() -> tuple[object, int]:
    server, port = start_server_thread("127.0.0.1", 0)
    time.sleep(0.1)
    yield server, port
    server.shutdown()
    server.server_close()


def _post_chat(port: int, text: str, *, session_context: dict | None = None) -> dict:
    body: dict = {
        "text": text,
        "surface": "assistant_chat",
        "conversation_id": f"needs-context-{uuid.uuid4()}",
    }
    if session_context is not None:
        body["session_context"] = session_context

    headers = {
        "X-Assistant-Token": WEBHOOK_TOKEN,
        "Content-Type": "application/json",
    }
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/chat/process", body=json.dumps(body).encode("utf-8"), headers=headers)
    response = conn.getresponse()
    raw = response.read().decode("utf-8")
    conn.close()
    assert response.status == 200
    return json.loads(raw)


def _post_chat_no_fin_write(port: int, text: str, *, session_context: dict | None = None) -> dict:
    with patch(
        "assistant_os.pipelines.fin_pipeline._append_expense_to_sheets",
        side_effect=AssertionError("FIN write must not run while building context_request"),
    ):
        return _post_chat(port, text, session_context=session_context)


def _context_request(response: dict) -> dict:
    return (
        response.get("session", {}).get("context_request")
        or response.get("audit", {}).get("context_request")
        or {}
    )


def _assert_no_execution_artifacts(response: dict) -> None:
    assert response.get("plan") == []
    assert response.get("needs_confirmation") is False
    assert response.get("result_type") != "plan_confirmation_required"
    assert list_tasks() == []


@pytest.mark.xfail(
    reason=(
        "FIN assistant_chat does not yet persist a non-executable "
        "context_request for missing responsable/itbms."
    ),
    strict=True,
)
def test_fin_missing_fields_creates_non_executable_context_request(chat_server) -> None:
    _, port = chat_server
    response = _post_chat_no_fin_write(port, "Gasté 15 en comida ayer")
    context_request = _context_request(response)

    assert context_request["domain"] == "FIN"
    assert set(context_request["missing_fields"]) == {"responsable", "itbms"}
    assert context_request["executable"] is False
    _assert_no_execution_artifacts(response)


@pytest.mark.xfail(
    reason="Follow-up text is not yet resolved against a pending FIN context_request.",
    strict=True,
)
def test_fin_followup_completes_itbms_but_not_responsable(chat_server) -> None:
    _, port = chat_server
    first = _post_chat_no_fin_write(port, "Gasté 15 en comida ayer")
    followup = _post_chat_no_fin_write(port, "Yo, sí con itbms", session_context=first["session"])
    context_request = _context_request(followup)

    assert context_request["domain"] == "FIN"
    assert context_request["entities"]["itbms"] is True
    assert "responsable" in context_request["missing_fields"]
    assert "itbms" not in context_request["missing_fields"]
    _assert_no_execution_artifacts(followup)


@pytest.mark.xfail(
    reason="Follow-up text is not yet resolved against a pending FIN context_request.",
    strict=True,
)
def test_fin_second_followup_completes_responsable_and_all_required_fields(chat_server) -> None:
    _, port = chat_server
    first = _post_chat_no_fin_write(port, "Gasté 15 en comida ayer")
    second = _post_chat_no_fin_write(port, "Yo, sí con itbms", session_context=first["session"])
    third = _post_chat_no_fin_write(port, "Jorge", session_context=second["session"])
    context_request = _context_request(third)

    assert context_request["domain"] == "FIN"
    assert context_request["entities"]["responsable"] == "Jorge"
    assert context_request["missing_fields"] == []
    assert context_request["ready_to_submit"] is True
    _assert_no_execution_artifacts(third)


@pytest.mark.xfail(
    reason="CODE assistant_chat clarification does not yet persist context_request state.",
    strict=True,
)
def test_code_missing_repo_url_creates_context_request(chat_server) -> None:
    _, port = chat_server
    response = _post_chat(port, "Analiza un repo github")
    context_request = _context_request(response)

    assert response["result_type"] == "clarification"
    assert context_request["domain"] == "CODE"
    assert context_request["missing_fields"] == ["repo_url"]
    assert context_request["executable"] is False
    _assert_no_execution_artifacts(response)


@pytest.mark.xfail(
    reason="Follow-up URL is not yet resolved against a pending CODE context_request.",
    strict=True,
)
def test_code_followup_github_url_completes_repo_url_without_executing(chat_server) -> None:
    _, port = chat_server
    first = _post_chat(port, "Analiza un repo github")
    followup = _post_chat(
        port,
        "https://github.com/JorgeCast31/TTI-LAB",
        session_context=first["session"],
    )
    context_request = _context_request(followup)

    assert context_request["domain"] == "CODE"
    assert context_request["entities"]["repo_url"] == "https://github.com/JorgeCast31/TTI-LAB"
    assert context_request["missing_fields"] == []
    assert context_request["ready_to_submit"] is True
    _assert_no_execution_artifacts(followup)


def test_url_alone_without_pending_context_does_not_execute(chat_server) -> None:
    _, port = chat_server
    response = _post_chat(port, "https://github.com/JorgeCast31/TTI-LAB")

    assert response["result_type"] in {"clarification", "surface_response", "plan_generated"}
    assert response.get("domain") != "CODE" or response.get("intent") != "executable_intent"
    assert response.get("result_type") != "plan_confirmation_required"
    assert list_tasks() == []
