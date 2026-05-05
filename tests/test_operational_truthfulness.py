"""Truthfulness guardrails for readiness and operational claims."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from assistant_os.contracts import normalize_request
from assistant_os.core.orchestrator import handle_request
from assistant_os.mso.task_registry import reset_task_registry


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
        "context_id": "ctx-operational-truthfulness",
        "created_at": "2026-05-04T00:00:00+00:00",
    }


def _route_code_review_url() -> dict:
    reset_task_registry()
    from assistant_os.pipelines.code_pipeline import register_review_executor

    register_review_executor(None)
    return handle_request(
        normalize_request(
            text="Analiza un repo github https://github.com/JorgeCast31/TTI-LAB",
            metadata={
                "surface": "assistant_chat",
                "routing_context": _code_review_routing_context(),
            },
        )
    )


def _message_text(result: dict) -> str:
    parts = [
        str(result.get("message") or ""),
        str((result.get("data") or {}).get("message") or ""),
        str((result.get("data") or {}).get("analysis") or ""),
    ]
    return "\n".join(parts).lower()


@pytest.mark.xfail(
    reason=(
        "CODE_REVIEW currently returns a successful stub review instead of "
        "truthfully reporting offline/unreadable remote content."
    ),
    strict=True,
)
def test_code_review_url_with_code_api_offline_reports_unavailable_not_repo_review() -> None:
    with patch(
        "assistant_os.codeops.readiness.get_code_readiness",
        return_value={
            "domain": "CODE",
            "feature_enabled": True,
            "code_api_reachable": False,
            "code_api_error": "connection refused",
            "apply_execution_mode": "stub",
            "note": "Readiness is not authority.",
        },
    ):
        result = _route_code_review_url()

    text = _message_text(result)
    assert result.get("execution_status") in {"unavailable", "stub"}
    assert any(term in text for term in ("offline", "unavailable", "no configurado", "no puedo leer"))
    assert "hallazgos tipicos" not in text
    assert "revisé el repo" not in text
    assert "revisado el repo" not in text


@pytest.mark.xfail(
    reason=(
        "A GitHub URL without a real remote-content reader currently falls "
        "through to the CODE_REVIEW stub instead of asking for files/content."
    ),
    strict=True,
)
def test_github_url_without_repo_access_asks_for_content_or_real_pipeline() -> None:
    result = _route_code_review_url()
    text = _message_text(result)

    assert result["domain"] == "CODE"
    assert not (
        result.get("result_type") == "code_review"
        and (result.get("data") or {}).get("executor_live") is False
    )
    assert any(term in text for term in ("archivo", "contenido", "repo path", "no puedo leer"))


@pytest.mark.xfail(
    reason=(
        "System status currently labels registered agents as available even "
        "without health/reachability evidence."
    ),
    strict=True,
)
def test_agent_registry_count_does_not_call_registered_agents_available() -> None:
    from assistant_os.surface_behavior import _system_state_summary

    with patch(
        "assistant_os.operability.build_mso_state_response",
        return_value={
            "ok": True,
            "operational_mode": "NORMAL",
            "agents_available": 3,
            "pending_confirmations": 0,
            "active_executions": 0,
        },
    ):
        message = _system_state_summary().lower()

    assert "agentes disponibles" not in message
    assert "registrados" in message or "sin probe" in message or "estado no verificado" in message


@pytest.mark.xfail(
    reason=(
        "Machine Operator wording can say available/active from adapter/config "
        "state without an explicit reachability probe."
    ),
    strict=True,
)
def test_machine_operator_does_not_claim_reachable_without_probe() -> None:
    from assistant_os.surface_behavior import _machine_operator_summary

    with patch(
        "assistant_os.operability.build_system_capabilities_response",
        return_value={
            "ok": True,
            "features": {"machine_operator": "available"},
            "domains": [],
            "capabilities": [],
        },
    ):
        message = _machine_operator_summary().lower()

    assert "reachable" not in message
    assert "activo" not in message
    assert "probe" in message or "reachability no verificada" in message or "sin verificación" in message
