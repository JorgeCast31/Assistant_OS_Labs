"""Tests for advisory routing_context consumption in the semantic layer."""

from __future__ import annotations

from assistant_os.contracts import (
    ACTION_COMMAND,
    ACTION_CODE_REVIEW,
    ACTION_FIN_EXPENSE,
    OP_CODE_REVIEW,
    OP_FIN_EXPENSE,
    normalize_request,
)
from assistant_os.core.semantic import classify


def _routing_context(**overrides: object) -> dict:
    ctx = {
        "source": "cognitive_router_v0",
        "authoritative": False,
        "intent_type": "executable_intent",
        "domain": "CODE",
        "action": ACTION_CODE_REVIEW,
        "entities": {"repo_url": "https://github.com/jorgecast31/tti-lab"},
        "missing_fields": [],
        "confidence": 0.91,
        "should_pass_to_kernel": True,
        "safety_flags": [],
        "routing_reason": "repo URL detected",
        "router_version": "v0_deterministic",
        "context_id": "ctx-semantic-hint",
        "created_at": "2026-05-04T00:00:00+00:00",
    }
    ctx.update(overrides)
    return ctx


def _classify_with_hint(text: str, routing_context: dict, surface: str = "assistant_chat") -> dict:
    return classify(
        normalize_request(
            text=text,
            metadata={
                "surface": surface,
                "routing_context": routing_context,
            },
        )
    )


def test_valid_code_routing_context_updates_domain_and_operation_after_classifier() -> None:
    intent = _classify_with_hint(
        "Analiza un repo github https://github.com/JorgeCast31/TTI-LAB",
        _routing_context(),
    )

    assert intent["domain"] == "CODE"
    assert intent["operation"] == OP_CODE_REVIEW
    assert intent["routing_context_used"] is True
    assert intent["reason"].startswith("routing_context:CODE_REVIEW,")


def test_valid_fin_routing_context_updates_domain_and_operation_after_classifier() -> None:
    intent = _classify_with_hint(
        "Gaste 15 en comida ayer",
        _routing_context(
            domain="FIN",
            action=ACTION_FIN_EXPENSE,
            entities={"amount": "15", "category": "comida", "date": "ayer"},
            confidence=0.88,
        ),
    )

    assert intent["domain"] == "FIN"
    assert intent["operation"] == OP_FIN_EXPENSE
    assert intent["routing_context_used"] is True


def test_authoritative_routing_context_is_ignored() -> None:
    intent = _classify_with_hint(
        "Analiza un repo github https://github.com/JorgeCast31/TTI-LAB",
        _routing_context(authoritative=True),
    )

    assert "routing_context_used" not in intent
    assert intent.get("operation") != OP_CODE_REVIEW


def test_command_action_routing_context_is_ignored() -> None:
    intent = _classify_with_hint(
        "Analiza un repo github https://github.com/JorgeCast31/TTI-LAB",
        _routing_context(domain="CODE", action=ACTION_COMMAND),
    )

    assert "routing_context_used" not in intent
    assert intent.get("operation") != OP_CODE_REVIEW


def test_suffix_command_action_routing_context_is_ignored() -> None:
    intent = _classify_with_hint(
        "Analiza un repo github https://github.com/JorgeCast31/TTI-LAB",
        _routing_context(domain="CODE", action="CODE_COMMAND"),
    )

    assert "routing_context_used" not in intent
    assert intent.get("operation") != OP_CODE_REVIEW


def test_low_confidence_routing_context_is_ignored() -> None:
    intent = _classify_with_hint(
        "Analiza un repo github https://github.com/JorgeCast31/TTI-LAB",
        _routing_context(confidence=0.69),
    )

    assert "routing_context_used" not in intent
    assert intent.get("operation") != OP_CODE_REVIEW


def test_non_executable_routing_context_is_ignored() -> None:
    intent = _classify_with_hint(
        "Analiza un repo github https://github.com/JorgeCast31/TTI-LAB",
        _routing_context(intent_type="needs_context"),
    )

    assert "routing_context_used" not in intent
    assert intent.get("operation") != OP_CODE_REVIEW


def test_should_not_pass_to_kernel_routing_context_is_ignored() -> None:
    intent = _classify_with_hint(
        "Analiza un repo github https://github.com/JorgeCast31/TTI-LAB",
        _routing_context(should_pass_to_kernel=False),
    )

    assert "routing_context_used" not in intent
    assert intent.get("operation") != OP_CODE_REVIEW


def test_unallowlisted_action_routing_context_is_ignored() -> None:
    intent = _classify_with_hint(
        "Abre notepad",
        _routing_context(domain="HOST", action="HOST_OPEN_APP", entities={"app": "notepad"}),
    )

    assert "routing_context_used" not in intent


def test_non_assistant_chat_surface_does_not_consume_routing_context() -> None:
    intent = _classify_with_hint(
        "Analiza un repo github https://github.com/JorgeCast31/TTI-LAB",
        _routing_context(),
        surface="system_chat",
    )

    assert "routing_context_used" not in intent
    assert intent.get("operation") != OP_CODE_REVIEW


def test_no_routing_context_preserves_legacy_classification() -> None:
    text = "xyzzy random text"
    legacy = classify(normalize_request(text=text, metadata={"surface": "assistant_chat"}))
    hinted = classify(
        normalize_request(
            text=text,
            metadata={
                "surface": "assistant_chat",
                "routing_context": _routing_context(intent_type="unknown_ambiguous"),
            },
        )
    )

    assert hinted == legacy
